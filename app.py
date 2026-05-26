import ctypes
import json
import math
import socket
import sys
import threading
import time
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import ttk

try:
    import hid
except ImportError:
    hid = None

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None


APP_NAME = "JoyConGyroAirMouse"
SINGLE_INSTANCE_MUTEX = "Local\\JoyConGyroAirMouseSingleInstance"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 47631
SETTINGS_PATH = Path.home() / "AppData" / "Roaming" / APP_NAME / "settings.json"
NINTENDO_VENDOR_ID = 0x057E
SWITCH_PRODUCT_IDS = {
    0x2006: "Joy-Con Left",
    0x2007: "Joy-Con Right",
    0x2009: "Switch Pro Controller",
}

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
WHEEL_DELTA = 120
KEYEVENTF_KEYUP = 0x0002
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_KEY_NAMES = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "ALT": 0x12,
    "PAUSE": 0x13,
    "CAPSLOCK": 0x14,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "WIN": 0x5B,
    "WINDOWS": 0x5B,
    "NUMLOCK": 0x90,
    "SCROLLLOCK": 0x91,
}
for index in range(1, 13):
    VK_KEY_NAMES[f"F{index}"] = 0x6F + index

GYRO_SCALE_DEG_PER_SEC = 936.0 / 32767.0
LARGE_CURSOR_SIZE = 64
SPI_SETCURSORS = 0x0057
MANUAL_CALIBRATION_SAMPLE_COUNT = 60
STARTUP_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ERROR_ALREADY_EXISTS = 183


def send_mouse(flags, dx=0, dy=0, data=0):
    extra = ctypes.c_ulong(0)
    mouse_input = MOUSEINPUT(dx, dy, data, flags, 0, ctypes.pointer(extra))
    input_data = INPUT(INPUT_MOUSE, INPUT_UNION(mi=mouse_input))
    user32.SendInput(1, ctypes.byref(input_data), ctypes.sizeof(input_data))


def send_key_down(vk):
    extra = ctypes.c_ulong(0)
    input_data = INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(vk, 0, 0, 0, ctypes.pointer(extra))))
    user32.SendInput(1, ctypes.byref(input_data), ctypes.sizeof(INPUT))


def send_key_up(vk):
    extra = ctypes.c_ulong(0)
    input_data = INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))))
    user32.SendInput(1, ctypes.byref(input_data), ctypes.sizeof(INPUT))


def send_key(vk):
    send_key_down(vk)
    send_key_up(vk)


def parse_key_macro(text):
    parts = [part.strip() for part in text.replace("+", " ").split() if part.strip()]
    keys = []
    for part in parts:
        vk = key_name_to_vk(part)
        if vk is None:
            return None
        keys.append(vk)
    return keys


def key_name_to_vk(name):
    normalized = name.strip().upper()
    if len(normalized) == 1 and "A" <= normalized <= "Z":
        return ord(normalized)
    if len(normalized) == 1 and "0" <= normalized <= "9":
        return ord(normalized)
    return VK_KEY_NAMES.get(normalized)


def send_key_macro(text):
    keys = parse_key_macro(text)
    if not keys:
        return False

    for vk in keys:
        send_key_down(vk)
    for vk in reversed(keys):
        send_key_up(vk)
    return True


def create_single_instance_mutex():
    handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
    already_running = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    return handle, already_running


def notify_existing_instance():
    try:
        with socket.create_connection((CONTROL_HOST, CONTROL_PORT), timeout=0.5) as sock:
            sock.sendall(b"show\n")
        return True
    except OSError:
        return False


def center_mouse():
    screen_width = user32.GetSystemMetrics(0)
    screen_height = user32.GetSystemMetrics(1)
    user32.SetCursorPos(screen_width // 2, screen_height // 2)


def load_system_cursors():
    user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, 0)


def get_cursor_size():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as key:
            value, _ = winreg.QueryValueEx(key, "CursorBaseSize")
            return int(value)
    except OSError:
        return None


def set_cursor_size(size):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "CursorBaseSize", 0, winreg.REG_DWORD, int(size))
    load_system_cursors()


def delete_cursor_size_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors", 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, "CursorBaseSize")
    except OSError:
        pass
    load_system_cursors()


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --startup'

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    launcher = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{launcher}" "{Path(__file__).resolve()}" --startup'


def enable_startup():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
    except OSError:
        pass


def load_settings():
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings):
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SETTINGS_PATH.open("w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2)
    except OSError:
        pass


def clamp(value, low, high):
    return max(low, min(high, value))


def read_i16_le(data, offset):
    value = data[offset] | (data[offset + 1] << 8)
    if value >= 32768:
        value -= 65536
    return value


def parse_stick(data, offset):
    x = data[offset] | ((data[offset + 1] & 0x0F) << 8)
    y = (data[offset + 1] >> 4) | (data[offset + 2] << 4)
    return x, y


def normalize_stick(value):
    centered = (value - 2048) / 2048.0
    if abs(centered) < 0.18:
        return 0.0
    return clamp(centered, -1.0, 1.0)


class JoyCon:
    def __init__(self):
        self.device = None
        self.name = ""
        self.side = "unknown"
        self.product_id = None
        self.packet_number = 0
        self.last_report = None

    def close(self):
        if self.device:
            try:
                self.device.close()
            except OSError:
                pass
        self.device = None
        self.name = ""
        self.side = "unknown"
        self.product_id = None

    def connect_first(self):
        self.close()
        for info in self.find_devices():
            try:
                dev = hid.device()
                dev.open_path(info["path"])
                dev.set_nonblocking(True)
                self.device = dev
                self.product_id = info.get("product_id")
                self.name = info.get("product_string") or SWITCH_PRODUCT_IDS.get(self.product_id, "Switch Controller")
                self.side = self.detect_side(self.product_id, self.name)
                self.initialize_imu()
                return True
            except OSError:
                self.close()
        return False

    @staticmethod
    def find_devices():
        devices = []
        if hid is None:
            return devices

        for info in hid.enumerate():
            vendor_id = info.get("vendor_id")
            product_id = info.get("product_id")
            product = (info.get("product_string") or "").lower()

            looks_like_switch = (
                vendor_id == NINTENDO_VENDOR_ID
                or product_id in SWITCH_PRODUCT_IDS
                or "joy-con" in product
                or "pro controller" in product
                or "switch" in product
                or "shanwan" in product
            )
            if looks_like_switch:
                devices.append(info)

        return devices

    @staticmethod
    def detect_side(product_id, name):
        lowered = (name or "").lower()
        if product_id == 0x2006 or "left" in lowered:
            return "left"
        if product_id == 0x2007 or "right" in lowered:
            return "right"
        return "pro"

    def write_subcommand(self, subcommand, payload=b""):
        if not self.device:
            return

        rumble = [0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40]
        packet = [0x01, self.packet_number & 0x0F, *rumble, subcommand, *payload]
        packet.extend([0x00] * (49 - len(packet)))
        self.device.write(bytes(packet))
        self.packet_number = (self.packet_number + 1) & 0x0F
        time.sleep(0.04)

    def initialize_imu(self):
        self.write_subcommand(0x03, b"\x30")  # full report mode
        self.write_subcommand(0x40, b"\x01")  # enable IMU
        self.write_subcommand(0x48, b"\x01")  # player light

    def read_report(self):
        if not self.device:
            return None

        try:
            for _ in range(8):
                data = self.device.read(64)
                if not data:
                    break
                if data[0] == 0x30 and len(data) >= 49:
                    report = self.parse_report(data)
                    self.last_report = report
                    return report
        except OSError:
            self.close()
            return None

        return self.last_report

    def parse_report(self, data):
        buttons_right = data[3]
        buttons_shared = data[4]
        buttons_left = data[5]
        left_x_raw, left_y_raw = parse_stick(data, 6)
        right_x_raw, right_y_raw = parse_stick(data, 9)

        # Full mode contains three IMU samples. Averaging makes cursor movement smoother.
        samples = []
        for offset in (13, 25, 37):
            if offset + 11 >= len(data):
                continue
            accel = (
                read_i16_le(data, offset),
                read_i16_le(data, offset + 2),
                read_i16_le(data, offset + 4),
            )
            gyro = (
                read_i16_le(data, offset + 6),
                read_i16_le(data, offset + 8),
                read_i16_le(data, offset + 10),
            )
            samples.append((accel, gyro))

        if samples:
            gyro = tuple(sum(sample[1][axis] for sample in samples) / len(samples) for axis in range(3))
            accel = tuple(sum(sample[0][axis] for sample in samples) / len(samples) for axis in range(3))
        else:
            gyro = (0.0, 0.0, 0.0)
            accel = (0.0, 0.0, 0.0)

        return {
            "right_buttons": buttons_right,
            "shared_buttons": buttons_shared,
            "left_buttons": buttons_left,
            "left_stick": (normalize_stick(left_x_raw), normalize_stick(left_y_raw)),
            "right_stick": (normalize_stick(right_x_raw), normalize_stick(right_y_raw)),
            "gyro_raw": gyro,
            "gyro_dps": tuple(axis * GYRO_SCALE_DEG_PER_SEC for axis in gyro),
            "accel_raw": accel,
        }


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Joy-Con Gyro Air Mouse")
        self.root.geometry("650x590")
        self.root.minsize(590, 520)

        self.joycon = JoyCon()
        self.running = False
        self.left_pressed = False
        self.right_pressed = False
        self.middle_pressed = False
        self.button_debounce = {}
        self.tray_icon = None
        self.tray_available = False
        self.control_server = None
        self.quitting = False
        self.cursor_original_size = None
        self.cursor_size_changed = False
        self.last_buttons = (0, 0, 0)
        self.last_scroll_time = time.perf_counter()
        self.last_hscroll_time = time.perf_counter()
        self.mouse_remainder_x = 0.0
        self.mouse_remainder_y = 0.0
        self.drift_yaw = 0.0
        self.drift_roll = 0.0
        self.bias_ready = False
        self.bias_samples = []
        self.stationary_score = 0.0
        self.last_accel_raw = None
        self.motion_energy = 0.0
        self.filtered_yaw = 0.0
        self.filtered_roll = 0.0
        self.calibrating = False
        self.calibration_required = False
        self.calibration_samples = []
        self.settings = load_settings()
        self.loading_settings = True

        self.sensitivity = tk.DoubleVar(value=self.setting("sensitivity", 0.5))
        self.deadzone = tk.DoubleVar(value=self.setting("deadzone", 0.5))
        self.smart_stabilization = tk.BooleanVar(value=self.setting("smart_stabilization", True))
        self.scroll_speed = tk.DoubleVar(value=self.setting("scroll_speed", 1.0))
        self.invert_y = tk.BooleanVar(value=self.setting("invert_y", True))
        self.invert_roll = tk.BooleanVar(value=self.setting("invert_roll", False))
        self.convert_direction = tk.BooleanVar(value=self.setting("convert_direction", False))
        self.left_stick_scroll = tk.BooleanVar(value=self.setting("left_stick_scroll", True))
        self.dpad_nudge = tk.BooleanVar(value=self.setting("dpad_nudge", True))
        self.a_action = tk.StringVar(value=self.setting("a_action", "None"))
        self.b_action = tk.StringVar(value=self.setting("b_action", "Win+H"))

        self.status_text = tk.StringVar(value="Stopped")
        self.controller_text = tk.StringVar(value="No Joy-Con / Switch controller connected yet")
        self.gyro_text = tk.StringVar(value="gyro x 0.0  y 0.0  z 0.0 deg/s")
        self.mouse_gyro_text = tk.StringVar(value="mouse yaw 0.0  roll 0.0")
        self.stick_text = tk.StringVar(value="LX 0.000  LY 0.000    RX 0.000  RY 0.000")
        self.button_text = tk.StringVar(value="Buttons: none")
        self.runtime_text = tk.StringVar(value="Runtime: idle")
        self.loading_text = tk.StringVar(value="")

        self.build_ui()
        self.bind_settings()
        self.loading_settings = False
        self.start_control_server()
        enable_startup()
        self.setup_tray()
        if self.tray_available and "--startup" in sys.argv:
            self.root.withdraw()
        self.root.after(200, self.connect)
        self.root.after(500, self.auto_connect_loop)
        self.root.after(50, self.poll)

    def setting(self, name, default):
        return self.settings.get(name, default)

    def bind_settings(self):
        for name, variable in (
            ("sensitivity", self.sensitivity),
            ("deadzone", self.deadzone),
            ("smart_stabilization", self.smart_stabilization),
            ("scroll_speed", self.scroll_speed),
            ("invert_y", self.invert_y),
            ("invert_roll", self.invert_roll),
            ("convert_direction", self.convert_direction),
            ("left_stick_scroll", self.left_stick_scroll),
            ("dpad_nudge", self.dpad_nudge),
            ("a_action", self.a_action),
            ("b_action", self.b_action),
        ):
            variable.trace_add("write", lambda *_args, key=name, var=variable: self.save_setting(key, var))

    def save_setting(self, name, variable):
        if self.loading_settings:
            return
        self.settings[name] = variable.get()
        save_settings(self.settings)

    def build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Joy-Con Gyro Air Mouse", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Switch mode required. Hold one Joy-Con vertically. ZR/ZL left click, R/L right click, X/Up resets while pointed at screen center.",
            wraplength=560,
        ).pack(anchor="w", pady=(4, 16))

        controls = ttk.LabelFrame(outer, text="Controls", padding=12)
        controls.pack(fill="x")

        self.add_slider(controls, "Gyro sensitivity", self.sensitivity, 0.02, 1.5)
        self.add_slider(controls, "Drift filter", self.deadzone, 0.0, 5.0)
        self.add_slider(controls, "Scroll speed", self.scroll_speed, 0.5, 12.0)

        ttk.Checkbutton(controls, text="Smart stabilization", variable=self.smart_stabilization).pack(anchor="w", pady=3)
        ttk.Checkbutton(controls, text="Invert vertical movement", variable=self.invert_y).pack(anchor="w", pady=3)
        ttk.Checkbutton(controls, text="Invert roll / vertical gyro", variable=self.invert_roll).pack(anchor="w", pady=3)
        ttk.Checkbutton(controls, text="Convert direction", variable=self.convert_direction).pack(anchor="w", pady=3)
        ttk.Checkbutton(controls, text="Use stick as vertical and horizontal scroll wheel", variable=self.left_stick_scroll).pack(anchor="w", pady=3)
        ttk.Checkbutton(controls, text="Use D-pad for small pointer nudges", variable=self.dpad_nudge).pack(anchor="w", pady=3)

        button_map = ttk.Frame(controls)
        button_map.pack(fill="x", pady=(8, 2))
        ttk.Label(button_map, text="A button").pack(side="left")
        self.add_action_combo(button_map, self.a_action)
        ttk.Label(button_map, text="B button").pack(side="left", padx=(16, 0))
        self.add_action_combo(button_map, self.b_action)

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=16)

        self.connect_button = ttk.Button(buttons, text="Connect", command=self.connect)
        self.connect_button.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.start_button = ttk.Button(buttons, text="Start", command=self.start)
        self.start_button.pack(side="left", expand=True, fill="x", padx=6)

        self.reset_button = ttk.Button(buttons, text="Reset Mouse", command=self.reset_mouse)
        self.reset_button.pack(side="left", expand=True, fill="x", padx=6)

        self.calibrate_button = ttk.Button(buttons, text="Calibrate Gyro", command=self.begin_manual_calibration)
        self.calibrate_button.pack(side="left", expand=True, fill="x", padx=6)

        self.stop_button = ttk.Button(buttons, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", expand=True, fill="x", padx=(6, 0))

        debug = ttk.LabelFrame(outer, text="Debug", padding=12)
        debug.pack(fill="both", expand=True)
        ttk.Label(debug, textvariable=self.status_text).pack(anchor="w")
        ttk.Label(debug, textvariable=self.controller_text).pack(anchor="w", pady=(6, 0))
        ttk.Label(debug, textvariable=self.gyro_text, font=("Consolas", 11)).pack(anchor="w", pady=(6, 0))
        ttk.Label(debug, textvariable=self.mouse_gyro_text, font=("Consolas", 11)).pack(anchor="w", pady=(6, 0))
        ttk.Label(debug, textvariable=self.stick_text, font=("Consolas", 11)).pack(anchor="w", pady=(6, 0))
        ttk.Label(debug, textvariable=self.button_text, font=("Consolas", 11)).pack(anchor="w", pady=(6, 0))
        ttk.Label(debug, textvariable=self.runtime_text, font=("Consolas", 11)).pack(anchor="w", pady=(6, 0))
        ttk.Label(debug, textvariable=self.loading_text, font=("Consolas", 11)).pack(anchor="w", pady=(6, 0))

    @staticmethod
    def add_slider(parent, label, variable, low, high):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=label).pack(side="left")
        scale = tk.Scale(
            row,
            from_=low,
            to=high,
            variable=variable,
            orient="horizontal",
            showvalue=False,
            resolution=0.01,
            highlightthickness=0,
        )
        scale.pack(side="left", fill="x", expand=True, padx=10)
        scale.bind("<Button-1>", lambda event, s=scale, v=variable, a=low, b=high: App.jump_slider(event, s, v, a, b), add="+")
        ttk.Label(row, textvariable=variable, width=6).pack(side="right")

    @staticmethod
    def jump_slider(event, scale, variable, low, high):
        slider_length = 30
        usable_width = max(1, scale.winfo_width() - slider_length)
        x = clamp(event.x - slider_length / 2, 0.0, usable_width)
        ratio = x / usable_width
        variable.set(low + (high - low) * ratio)
        return None

    @staticmethod
    def add_action_combo(parent, variable):
        actions = (
            "None",
            "Left Click",
            "Right Click",
            "Reset Mouse",
            "Pause Gyro",
            "Space",
            "Enter",
            "Esc",
            "Ctrl+C",
            "Ctrl+V",
            "Alt+Tab",
            "Win+H",
        )
        ttk.Combobox(parent, textvariable=variable, values=actions, width=14).pack(side="left", padx=(6, 0))

    def connect(self):
        if hid is None:
            self.controller_text.set("Missing dependency: hidapi. Run with run.bat to install it automatically.")
            return

        if self.joycon.connect_first():
            self.controller_text.set(f"Connected: {self.joycon.name} ({self.joycon.side})")
            self.reset_bias_estimator()
            self.reset_air_mouse_state()
            self.calibrating = False
            self.calibration_required = True
            self.calibration_samples.clear()
            self.loading_text.set("Auto calibration starting - hold the Joy-Con still")
            self.calibrate_button.configure(text="Calibrate Gyro", state="normal")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self.status_text.set("Connected. Calibrating gyro.")
            self.begin_manual_calibration()
        else:
            self.controller_text.set("No Joy-Con / Switch controller found. Pair it in Switch mode, then press Connect.")

    def auto_connect_loop(self):
        if not self.quitting and not self.joycon.device:
            self.connect()
        self.root.after(3000, self.auto_connect_loop)

    def start_control_server(self):
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((CONTROL_HOST, CONTROL_PORT))
            server.listen(1)
            self.control_server = server
        except OSError:
            return

        thread = threading.Thread(target=self.control_server_loop, daemon=True)
        thread.start()

    def control_server_loop(self):
        while not self.quitting and self.control_server:
            try:
                client, _ = self.control_server.accept()
            except OSError:
                break
            with client:
                try:
                    command = client.recv(64).decode("utf-8", errors="ignore").strip()
                except OSError:
                    command = ""
            if command == "show":
                self.root.after(0, self.show_window)

    def start(self):
        if not self.joycon.device:
            self.connect()
        if not self.joycon.device:
            return
        if self.calibration_required:
            self.status_text.set("Calibrate gyro before Start.")
            self.runtime_text.set("Runtime: calibration required - do not shake")
            self.loading_text.set("Click Calibrate Gyro while holding the Joy-Con still")
            return
        self.running = True
        self.status_text.set("Running")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.make_cursor_large()

    def stop(self):
        self.running = False
        self.release_mouse_buttons()
        self.restore_cursor_size()
        self.status_text.set("Stopped")
        self.start_button.configure(state="disabled" if self.calibration_required else "normal")
        self.stop_button.configure(state="disabled")

    def make_cursor_large(self):
        if self.cursor_size_changed:
            return

        self.cursor_original_size = get_cursor_size()
        try:
            set_cursor_size(LARGE_CURSOR_SIZE)
            self.cursor_size_changed = True
        except OSError:
            self.status_text.set("Running. Could not change cursor size.")

    def restore_cursor_size(self):
        if not self.cursor_size_changed:
            return

        try:
            if self.cursor_original_size is None:
                delete_cursor_size_value()
            else:
                set_cursor_size(self.cursor_original_size)
        except OSError:
            pass

        self.cursor_size_changed = False

    def reset_mouse(self):
        center_mouse()
        self.reset_air_mouse_state()
        self.loading_text.set("")
        self.reset_button.configure(text="Reset Mouse")
        self.status_text.set("Mouse centered.")

    def poll(self):
        if not self.joycon.device:
            self.root.after(250, self.poll)
            return

        report = self.joycon.read_report()
        if not self.joycon.device:
            self.stop()
            self.controller_text.set("Controller disconnected")
            self.root.after(250, self.poll)
            return

        if report:
            self.handle_report(report)

        self.root.after(8, self.poll)

    def handle_report(self, report):
        right_buttons = report["right_buttons"]
        shared_buttons = report["shared_buttons"]
        left_buttons = report["left_buttons"]
        buttons = (right_buttons, shared_buttons, left_buttons)
        debounced = self.build_debounced_buttons(right_buttons, shared_buttons, left_buttons)
        gyro_x, gyro_y, gyro_z = report["gyro_dps"]
        left_x, left_y = report["left_stick"]
        right_x, right_y = report["right_stick"]
        accel = report["accel_raw"]
        stick_x, stick_y = self.active_stick(left_x, left_y, right_x, right_y)
        yaw, roll = self.map_gyro(gyro_x, gyro_y, gyro_z)

        self.handle_start_toggle(debounced)
        self.handle_mouse_reset(debounced)
        if self.calibrating:
            self.update_manual_calibration(yaw, roll)
        else:
            self.update_bias_estimator(yaw, roll, accel)

        corrected_yaw = yaw - self.drift_yaw
        corrected_roll = roll - self.drift_roll
        filtered_yaw, filtered_roll = self.apply_residual_filter(corrected_yaw, corrected_roll)

        self.gyro_text.set(
            f"gyro x {gyro_x:+.1f}  y {gyro_y:+.1f}  z {gyro_z:+.1f} deg/s"
            f"    bias yaw {self.drift_yaw:+.2f} roll {self.drift_roll:+.2f}"
        )
        self.mouse_gyro_text.set(f"mouse yaw {filtered_yaw:+.2f}  roll {filtered_roll:+.2f}")
        self.stick_text.set(f"LX {left_x:+.3f}  LY {left_y:+.3f}    RX {right_x:+.3f}  RY {right_y:+.3f}")
        self.button_text.set(self.describe_buttons(right_buttons, shared_buttons, left_buttons))

        gyro_pause = self.is_gyro_pause_pressed(debounced)
        self.handle_custom_button_actions(debounced)

        if self.running and not self.calibrating:
            if gyro_pause:
                self.reset_air_mouse_state()
                self.runtime_text.set("Runtime: gyro paused")
            else:
                self.move_mouse_from_gyro(yaw, roll)
                self.runtime_text.set("Runtime: moving enabled")
            self.update_mouse_buttons(debounced)
            if self.left_stick_scroll.get():
                self.scroll_and_arrows_from_stick(stick_x, stick_y)
            self.update_middle_button(debounced)
            if self.dpad_nudge.get():
                self.move_from_dpad(left_buttons)
        else:
            self.release_mouse_buttons()
            if self.calibrating:
                self.runtime_text.set("Runtime: calibrating - do not shake")
            elif not self.running:
                self.runtime_text.set("Runtime: stopped")

        self.last_buttons = buttons

    def active_stick(self, left_x, left_y, right_x, right_y):
        if self.joycon.side == "right":
            return right_x, right_y
        return left_x, left_y

    def map_gyro(self, gyro_x, gyro_y, gyro_z):
        yaw = gyro_z
        roll = gyro_y
        if self.joycon.side == "left":
            yaw = -yaw

        if self.invert_roll.get():
            roll = -roll

        if self.convert_direction.get():
            yaw = -yaw
            roll = -roll

        return yaw, roll

    def move_mouse_from_gyro(self, yaw, roll):
        yaw -= self.drift_yaw
        roll -= self.drift_roll
        yaw, roll = self.apply_residual_filter(yaw, roll)

        if yaw == 0.0 and roll == 0.0:
            self.mouse_remainder_x = 0.0
            self.mouse_remainder_y = 0.0
            return

        dx_float = yaw * self.sensitivity.get() + self.mouse_remainder_x
        dy_value = -roll if self.invert_y.get() else roll
        dy_float = dy_value * self.sensitivity.get() + self.mouse_remainder_y

        dx = math.trunc(dx_float)
        dy = math.trunc(dy_float)
        self.mouse_remainder_x = dx_float - dx
        self.mouse_remainder_y = dy_float - dy

        if dx or dy:
            send_mouse(MOUSEEVENTF_MOVE, dx, dy)

    def apply_residual_filter(self, yaw, roll):
        if not self.smart_stabilization.get():
            threshold = self.deadzone.get()
            if threshold > 0:
                if abs(yaw) < threshold:
                    yaw = 0.0
                if abs(roll) < threshold:
                    roll = 0.0
            return yaw, roll

        magnitude = math.hypot(yaw, roll)
        self.motion_energy = self.motion_energy * 0.82 + magnitude * 0.18

        quiet_threshold = max(0.15, self.deadzone.get())
        moving_threshold = quiet_threshold * 3.0
        if magnitude < quiet_threshold:
            self.filtered_yaw *= 0.72
            self.filtered_roll *= 0.72
            if abs(self.filtered_yaw) < 0.03:
                self.filtered_yaw = 0.0
            if abs(self.filtered_roll) < 0.03:
                self.filtered_roll = 0.0
            return self.filtered_yaw, self.filtered_roll

        response = 0.84 if self.motion_energy > moving_threshold else 0.68
        self.filtered_yaw = self.filtered_yaw * (1.0 - response) + yaw * response
        self.filtered_roll = self.filtered_roll * (1.0 - response) + roll * response
        return self.filtered_yaw, self.filtered_roll

    def update_bias_estimator(self, yaw, roll, accel):
        if not self.smart_stabilization.get():
            self.bias_samples.clear()
            self.stationary_score = 0.0
            self.last_accel_raw = accel
            return

        accel_delta = 0.0
        if self.last_accel_raw is not None:
            accel_delta = math.sqrt(sum((accel[index] - self.last_accel_raw[index]) ** 2 for index in range(3)))
        self.last_accel_raw = accel

        corrected_yaw = yaw - self.drift_yaw
        corrected_roll = roll - self.drift_roll
        corrected_magnitude = math.hypot(corrected_yaw, corrected_roll)

        if self.bias_ready:
            gyro_limit = max(0.65, self.deadzone.get() * 1.25)
            stationary = corrected_magnitude < gyro_limit and accel_delta < 350.0
        else:
            stationary = math.hypot(yaw, roll) < 1.8 and accel_delta < 350.0

        if stationary:
            self.stationary_score = min(1.0, self.stationary_score + 0.08)
        else:
            self.stationary_score = max(0.0, self.stationary_score - 0.18)
            if not self.bias_ready:
                self.bias_samples.clear()

        if self.stationary_score < 0.85:
            return

        if not self.bias_ready:
            self.bias_samples.append((yaw, roll))
            if len(self.bias_samples) < 45:
                self.runtime_text.set("Runtime: stabilizing mouse - do not shake")
                return

            self.drift_yaw = self.median(sample[0] for sample in self.bias_samples)
            self.drift_roll = self.median(sample[1] for sample in self.bias_samples)
            self.bias_samples.clear()
            self.bias_ready = True
            self.reset_air_mouse_state()
            self.runtime_text.set("Runtime: mouse stabilized")
            return

        correction_rate = 0.01
        self.drift_yaw = self.drift_yaw * (1.0 - correction_rate) + yaw * correction_rate
        self.drift_roll = self.drift_roll * (1.0 - correction_rate) + roll * correction_rate

    def build_debounced_buttons(self, right_buttons, shared_buttons, left_buttons):
        raw = {
            "Y": bool(right_buttons & 0x01),
            "X": bool(right_buttons & 0x02),
            "B": bool(right_buttons & 0x04),
            "A": bool(right_buttons & 0x08),
            "R": bool(right_buttons & 0x40),
            "ZR": bool(right_buttons & 0x80),
            "-": bool(shared_buttons & 0x01),
            "+": bool(shared_buttons & 0x02),
            "RStick": bool(shared_buttons & 0x04),
            "LStick": bool(shared_buttons & 0x08),
            "Down": bool(left_buttons & 0x01),
            "Up": bool(left_buttons & 0x02),
            "Right": bool(left_buttons & 0x04),
            "Left": bool(left_buttons & 0x08),
            "L": bool(left_buttons & 0x40),
            "ZL": bool(left_buttons & 0x80),
        }
        return {name: self.debounce_button(name, pressed) for name, pressed in raw.items()}

    def debounce_button(self, name, pressed):
        now = time.perf_counter()
        state = self.button_debounce.get(name)
        if state is None:
            state = {
                "raw": pressed,
                "stable": pressed,
                "changed_at": now,
            }
            self.button_debounce[name] = state
            return pressed, False

        if pressed != state["raw"]:
            state["raw"] = pressed
            state["changed_at"] = now

        edge = False
        debounce_time = 0.028
        if state["stable"] != state["raw"] and now - state["changed_at"] >= debounce_time:
            state["stable"] = state["raw"]
            edge = state["stable"]

        return state["stable"], edge

    def update_mouse_buttons(self, buttons):
        if self.joycon.side == "left":
            want_left = buttons["ZL"][0]
            want_right = buttons["L"][0]
        else:
            want_left = buttons["ZR"][0]
            want_right = buttons["R"][0]

        if self.joycon.side != "left":
            want_left = want_left or self.custom_button_held(buttons, "Left Click")
            want_right = want_right or self.custom_button_held(buttons, "Right Click")

        if want_left != self.left_pressed:
            send_mouse(MOUSEEVENTF_LEFTDOWN if want_left else MOUSEEVENTF_LEFTUP)
            self.left_pressed = want_left

        if want_right != self.right_pressed:
            send_mouse(MOUSEEVENTF_RIGHTDOWN if want_right else MOUSEEVENTF_RIGHTUP)
            self.right_pressed = want_right

    def release_mouse_buttons(self):
        if self.left_pressed:
            send_mouse(MOUSEEVENTF_LEFTUP)
            self.left_pressed = False
        if self.right_pressed:
            send_mouse(MOUSEEVENTF_RIGHTUP)
            self.right_pressed = False
        if self.middle_pressed:
            send_mouse(MOUSEEVENTF_MIDDLEUP)
            self.middle_pressed = False

    def scroll_and_arrows_from_stick(self, stick_x, stick_y):
        now = time.perf_counter()
        interval = max(0.04, 0.18 / self.scroll_speed.get())
        if abs(stick_y) >= 0.35 and now - self.last_scroll_time >= interval:
            send_mouse(MOUSEEVENTF_WHEEL, data=int(math.copysign(WHEEL_DELTA, stick_y)))
            self.last_scroll_time = now

        if abs(stick_x) >= 0.35 and now - self.last_hscroll_time >= interval:
            send_key(VK_RIGHT if stick_x > 0 else VK_LEFT)
            self.last_hscroll_time = now

    def update_middle_button(self, buttons):
        want_middle = buttons["RStick"][0] or buttons["LStick"][0]
        if want_middle != self.middle_pressed:
            send_mouse(MOUSEEVENTF_MIDDLEDOWN if want_middle else MOUSEEVENTF_MIDDLEUP)
            self.middle_pressed = want_middle

    def move_from_dpad(self, left_buttons):
        dx = 0
        dy = 0
        if left_buttons & 0x08:
            dx -= 3
        if left_buttons & 0x04:
            dx += 3
        if left_buttons & 0x02:
            dy -= 3
        if left_buttons & 0x01:
            dy += 3
        if dx or dy:
            send_mouse(MOUSEEVENTF_MOVE, dx, dy)

    def handle_start_toggle(self, buttons):
        if buttons["+"][1]:
            if self.running:
                self.stop()
            else:
                self.start()

    def is_gyro_pause_pressed(self, buttons):
        if self.joycon.side == "left":
            return False
        return buttons["Y"][0] or self.custom_button_held(buttons, "Pause Gyro")

    def handle_mouse_reset(self, buttons):
        if self.joycon.side == "left":
            reset_edge = buttons["Up"][1]
        else:
            reset_edge = buttons["X"][1]

        if reset_edge:
            self.reset_mouse()

    def handle_custom_button_actions(self, buttons):
        if self.joycon.side == "left":
            return

        for name, variable in (("A", self.a_action), ("B", self.b_action)):
            if buttons[name][1]:
                self.run_custom_button_action(variable.get())

    def custom_button_held(self, buttons, action):
        if self.a_action.get() == action and buttons["A"][0]:
            return True
        if self.b_action.get() == action and buttons["B"][0]:
            return True
        return False

    def run_custom_button_action(self, action):
        action = action.strip()
        if not action or action == "None":
            return
        if action == "Reset Mouse":
            self.reset_mouse()
            return
        if action in ("Left Click", "Right Click", "Pause Gyro"):
            return
        if not send_key_macro(action):
            self.runtime_text.set(f"Runtime: unknown macro '{action}'")

    def reset_air_mouse_state(self):
        self.mouse_remainder_x = 0.0
        self.mouse_remainder_y = 0.0
        self.motion_energy = 0.0
        self.filtered_yaw = 0.0
        self.filtered_roll = 0.0
        self.stationary_score = 0.0
        self.last_accel_raw = None

    def begin_manual_calibration(self):
        if not self.joycon.device:
            self.status_text.set("Connect a controller before calibrating.")
            self.loading_text.set("")
            return

        if self.running:
            self.stop()
        self.release_mouse_buttons()
        self.reset_bias_estimator()
        self.reset_air_mouse_state()
        self.calibration_samples.clear()
        self.calibrating = True
        self.status_text.set("Calibrating gyro. Hold the Joy-Con still.")
        self.runtime_text.set("Runtime: calibrating - do not shake")
        self.calibrate_button.configure(text="Calibrating...", state="disabled")
        self.update_calibration_progress()

    def update_manual_calibration(self, yaw, roll):
        if not self.calibrating:
            return

        self.calibration_samples.append((yaw, roll))
        if len(self.calibration_samples) < MANUAL_CALIBRATION_SAMPLE_COUNT:
            self.update_calibration_progress()
            return

        self.drift_yaw = self.median(sample[0] for sample in self.calibration_samples)
        self.drift_roll = self.median(sample[1] for sample in self.calibration_samples)
        self.bias_ready = True
        self.calibrating = False
        self.calibration_required = False
        self.calibration_samples.clear()
        self.reset_air_mouse_state()
        self.loading_text.set("")
        self.calibrate_button.configure(text="Calibrate Gyro", state="normal")
        self.start_button.configure(state="normal")
        self.status_text.set("Gyro calibrated.")
        self.runtime_text.set("Runtime: gyro calibrated")

    def update_calibration_progress(self):
        progress = min(1.0, len(self.calibration_samples) / MANUAL_CALIBRATION_SAMPLE_COUNT)
        filled = int(progress * 12)
        bar = "#" * filled + "-" * (12 - filled)
        percent = int(progress * 100)
        self.loading_text.set(f"Calibrating [{bar}] {percent:3d}% - do not shake")

    def reset_bias_estimator(self):
        self.drift_yaw = 0.0
        self.drift_roll = 0.0
        self.bias_ready = False
        self.bias_samples.clear()
        self.stationary_score = 0.0
        self.last_accel_raw = None

    @staticmethod
    def median(values):
        sorted_values = sorted(values)
        if not sorted_values:
            return 0.0
        middle = len(sorted_values) // 2
        if len(sorted_values) % 2:
            return sorted_values[middle]
        return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0

    @staticmethod
    def describe_buttons(right_buttons, shared_buttons, left_buttons):
        names = []
        for bit, name in (
            (0x01, "Y"), (0x02, "X"), (0x04, "B"), (0x08, "A"),
            (0x40, "R"), (0x80, "ZR"),
        ):
            if right_buttons & bit:
                names.append(name)
        for bit, name in ((0x01, "-"), (0x02, "+"), (0x10, "Home"), (0x20, "Capture")):
            if shared_buttons & bit:
                names.append(name)
        for bit, name in (
            (0x01, "Down"), (0x02, "Up"), (0x04, "Right"), (0x08, "Left"),
            (0x40, "L"), (0x80, "ZL"),
        ):
            if left_buttons & bit:
                names.append(name)
        pressed = ", ".join(names) if names else "none"
        return f"Buttons: {pressed}    raw R={right_buttons:02X} S={shared_buttons:02X} L={left_buttons:02X}"

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def on_close(self):
        if not self.quitting and self.tray_available:
            self.root.withdraw()
            return

        self.quit_app()

    def quit_app(self):
        self.quitting = True
        self.stop()
        self.restore_cursor_size()
        self.joycon.close()
        if self.tray_icon:
            self.tray_icon.stop()
        if self.control_server:
            try:
                self.control_server.close()
            except OSError:
                pass
        self.root.destroy()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def setup_tray(self):
        if pystray is None or Image is None or ImageDraw is None:
            self.tray_available = False
            return

        image = self.create_tray_image()
        menu = pystray.Menu(
            pystray.MenuItem("Open", lambda icon, item: self.root.after(0, self.show_window), default=True),
            pystray.MenuItem("Start", lambda icon, item: self.root.after(0, self.start)),
            pystray.MenuItem("Stop", lambda icon, item: self.root.after(0, self.stop)),
            pystray.MenuItem("Reset Mouse", lambda icon, item: self.root.after(0, self.reset_mouse)),
            pystray.MenuItem("Quit", lambda icon, item: self.root.after(0, self.quit_app)),
        )
        self.tray_icon = pystray.Icon(APP_NAME, image, APP_NAME, menu)

        try:
            self.tray_icon.run_detached()
            self.tray_available = True
        except Exception:
            self.tray_available = False

    @staticmethod
    def create_tray_image():
        image = Image.new("RGBA", (64, 64), (16, 20, 24, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((10, 8, 54, 56), radius=13, outline=(45, 212, 191), width=4, fill=(15, 41, 48))
        draw.ellipse((25, 17, 39, 31), outline=(229, 231, 235), width=3)
        draw.ellipse((23, 38, 31, 46), fill=(143, 211, 255))
        draw.ellipse((34, 38, 42, 46), fill=(143, 211, 255))
        return image


if __name__ == "__main__":
    mutex_handle, already_running = create_single_instance_mutex()
    if already_running:
        notify_existing_instance()
        sys.exit(0)

    try:
        App().run()
    finally:
        if mutex_handle:
            kernel32.CloseHandle(mutex_handle)

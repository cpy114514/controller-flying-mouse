import ctypes
import math
import time
import tkinter as tk
import winreg
from tkinter import ttk

try:
    import hid
except ImportError:
    hid = None


NINTENDO_VENDOR_ID = 0x057E
SWITCH_PRODUCT_IDS = {
    0x2006: "Joy-Con Left",
    0x2007: "Joy-Con Right",
    0x2009: "Switch Pro Controller",
}

INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x01000
WHEEL_DELTA = 120

GYRO_SCALE_DEG_PER_SEC = 936.0 / 32767.0
LARGE_CURSOR_SIZE = 64
SPI_SETCURSORS = 0x0057
CALIBRATION_SAMPLE_COUNT = 60


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]


user32 = ctypes.windll.user32


def send_mouse(flags, dx=0, dy=0, data=0):
    extra = ctypes.c_ulong(0)
    mouse_input = MOUSEINPUT(dx, dy, data, flags, 0, ctypes.pointer(extra))
    input_data = INPUT(INPUT_MOUSE, INPUT_UNION(mi=mouse_input))
    user32.SendInput(1, ctypes.byref(input_data), ctypes.sizeof(input_data))


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
        self.cursor_original_size = None
        self.cursor_size_changed = False
        self.last_buttons = (0, 0, 0)
        self.last_scroll_time = time.perf_counter()
        self.last_hscroll_time = time.perf_counter()
        self.mouse_remainder_x = 0.0
        self.mouse_remainder_y = 0.0
        self.drift_yaw = 0.0
        self.drift_roll = 0.0
        self.calibration_samples = []
        self.calibrating = False

        self.sensitivity = tk.DoubleVar(value=0.5)
        self.deadzone = tk.DoubleVar(value=0.5)
        self.scroll_speed = tk.DoubleVar(value=4.0)
        self.invert_y = tk.BooleanVar(value=True)
        self.invert_roll = tk.BooleanVar(value=False)
        self.convert_direction = tk.BooleanVar(value=False)
        self.left_stick_scroll = tk.BooleanVar(value=True)
        self.dpad_nudge = tk.BooleanVar(value=True)
        self.a_action = tk.StringVar(value="None")
        self.b_action = tk.StringVar(value="None")

        self.status_text = tk.StringVar(value="Stopped")
        self.controller_text = tk.StringVar(value="No Joy-Con / Switch controller connected yet")
        self.gyro_text = tk.StringVar(value="gyro x 0.0  y 0.0  z 0.0 deg/s")
        self.mouse_gyro_text = tk.StringVar(value="mouse yaw 0.0  roll 0.0")
        self.stick_text = tk.StringVar(value="LX 0.000  LY 0.000    RX 0.000  RY 0.000")
        self.button_text = tk.StringVar(value="Buttons: none")
        self.runtime_text = tk.StringVar(value="Runtime: idle")
        self.loading_text = tk.StringVar(value="")

        self.build_ui()
        self.root.after(50, self.poll)

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
        self.add_slider(controls, "Scroll speed", self.scroll_speed, 1.0, 12.0)

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
        actions = ("None", "Left Click", "Right Click", "Reset Mouse", "Pause Gyro")
        ttk.Combobox(parent, textvariable=variable, values=actions, width=12, state="readonly").pack(side="left", padx=(6, 0))

    def connect(self):
        if hid is None:
            self.controller_text.set("Missing dependency: hidapi. Run with run.bat to install it automatically.")
            return

        if self.joycon.connect_first():
            self.controller_text.set(f"Connected: {self.joycon.name} ({self.joycon.side})")
            self.begin_drift_calibration()
        else:
            self.controller_text.set("No Joy-Con / Switch controller found. Pair it in Switch mode, then press Connect.")

    def start(self):
        if not self.joycon.device:
            self.connect()
        if not self.joycon.device:
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
        self.start_button.configure(state="normal")
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
        self.begin_drift_calibration()
        self.status_text.set("Mouse centered. Hold still to calibrate drift.")

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
        gyro_x, gyro_y, gyro_z = report["gyro_dps"]
        left_x, left_y = report["left_stick"]
        right_x, right_y = report["right_stick"]
        stick_x, stick_y = self.active_stick(left_x, left_y, right_x, right_y)
        yaw, roll = self.map_gyro(gyro_x, gyro_y, gyro_z)

        self.handle_start_toggle(right_buttons, shared_buttons)
        self.handle_mouse_reset(right_buttons, left_buttons)
        self.update_drift_calibration(yaw, roll)

        corrected_yaw = yaw - self.drift_yaw
        corrected_roll = roll - self.drift_roll
        filtered_yaw, filtered_roll = self.apply_residual_filter(corrected_yaw, corrected_roll)

        self.gyro_text.set(
            f"gyro x {gyro_x:+.1f}  y {gyro_y:+.1f}  z {gyro_z:+.1f} deg/s"
            f"    drift yaw {self.drift_yaw:+.2f} roll {self.drift_roll:+.2f}"
        )
        self.mouse_gyro_text.set(f"mouse yaw {filtered_yaw:+.2f}  roll {filtered_roll:+.2f}")
        self.stick_text.set(f"LX {left_x:+.3f}  LY {left_y:+.3f}    RX {right_x:+.3f}  RY {right_y:+.3f}")
        self.button_text.set(self.describe_buttons(right_buttons, shared_buttons, left_buttons))

        gyro_pause = self.is_gyro_pause_pressed(right_buttons)
        self.handle_custom_button_actions(right_buttons)

        if self.running and not self.calibrating:
            if gyro_pause:
                self.reset_air_mouse_state()
                self.runtime_text.set("Runtime: gyro paused")
            else:
                self.move_mouse_from_gyro(yaw, roll)
                self.runtime_text.set("Runtime: moving enabled")
            self.update_mouse_buttons(right_buttons, left_buttons)
            if self.left_stick_scroll.get():
                self.scroll_from_stick(stick_x, stick_y)
            if self.dpad_nudge.get():
                self.move_from_dpad(left_buttons)
        else:
            self.release_mouse_buttons()
            if self.calibrating:
                self.runtime_text.set("Runtime: calibrating, hold still")
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
        threshold = self.deadzone.get()
        if threshold > 0:
            if abs(yaw) < threshold:
                yaw = 0.0
            if abs(roll) < threshold:
                roll = 0.0
        return yaw, roll

    def update_mouse_buttons(self, right_buttons, left_buttons):
        if self.joycon.side == "left":
            want_left = bool(left_buttons & 0x80)   # ZL, large trigger
            want_right = bool(left_buttons & 0x40)  # L, small shoulder
        else:
            want_left = bool(right_buttons & 0x80)   # ZR, large trigger
            want_right = bool(right_buttons & 0x40)  # R, small shoulder

        if self.joycon.side != "left":
            want_left = want_left or self.custom_button_held(right_buttons, "Left Click")
            want_right = want_right or self.custom_button_held(right_buttons, "Right Click")

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

    def scroll_from_stick(self, stick_x, stick_y):
        now = time.perf_counter()
        interval = max(0.015, 0.09 / self.scroll_speed.get())
        if abs(stick_y) >= 0.35 and now - self.last_scroll_time >= interval:
            send_mouse(MOUSEEVENTF_WHEEL, data=int(math.copysign(WHEEL_DELTA, stick_y)))
            self.last_scroll_time = now

        if abs(stick_x) >= 0.35 and now - self.last_hscroll_time >= interval:
            send_mouse(MOUSEEVENTF_HWHEEL, data=int(math.copysign(WHEEL_DELTA, stick_x)))
            self.last_hscroll_time = now

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

    def handle_start_toggle(self, right_buttons, shared_buttons):
        plus_pressed = bool(shared_buttons & 0x02)
        plus_was_pressed = bool(self.last_buttons[1] & 0x02)

        if plus_pressed and not plus_was_pressed:
            if self.running:
                self.stop()
            else:
                self.start()

    def is_gyro_pause_pressed(self, right_buttons):
        if self.joycon.side == "left":
            return False
        return bool(right_buttons & 0x01) or self.custom_button_held(right_buttons, "Pause Gyro")  # Y

    def handle_mouse_reset(self, right_buttons, left_buttons):
        if self.joycon.side == "left":
            reset_pressed = bool(left_buttons & 0x02)  # Up
            reset_was_pressed = bool(self.last_buttons[2] & 0x02)
        else:
            reset_pressed = bool(right_buttons & 0x02)  # X
            reset_was_pressed = bool(self.last_buttons[0] & 0x02)

        if reset_pressed and not reset_was_pressed:
            self.reset_mouse()

    def handle_custom_button_actions(self, right_buttons):
        if self.joycon.side == "left":
            return

        for bit, variable in ((0x08, self.a_action), (0x04, self.b_action)):
            pressed = bool(right_buttons & bit)
            was_pressed = bool(self.last_buttons[0] & bit)
            if pressed and not was_pressed and variable.get() == "Reset Mouse":
                self.reset_mouse()

    def custom_button_held(self, right_buttons, action):
        if self.a_action.get() == action and right_buttons & 0x08:
            return True
        if self.b_action.get() == action and right_buttons & 0x04:
            return True
        return False

    def reset_air_mouse_state(self):
        self.mouse_remainder_x = 0.0
        self.mouse_remainder_y = 0.0

    def begin_drift_calibration(self):
        self.reset_air_mouse_state()
        self.calibration_samples = []
        self.calibrating = True
        self.status_text.set("Calibrating drift. Hold the Joy-Con still.")
        self.update_loading_animation()

    def update_drift_calibration(self, yaw, roll):
        if not self.calibrating:
            return

        self.calibration_samples.append((yaw, roll))
        if len(self.calibration_samples) < CALIBRATION_SAMPLE_COUNT:
            self.update_loading_animation()
            return

        yaw_values = [sample[0] for sample in self.calibration_samples]
        roll_values = [sample[1] for sample in self.calibration_samples]
        self.drift_yaw = self.trimmed_mean(yaw_values)
        self.drift_roll = self.trimmed_mean(roll_values)
        self.calibrating = False
        self.loading_text.set("")
        self.reset_button.configure(text="Reset Mouse")
        self.status_text.set("Running" if self.running else "Stopped")

    def update_loading_animation(self):
        if not self.calibrating:
            return

        progress = min(1.0, len(self.calibration_samples) / CALIBRATION_SAMPLE_COUNT)
        filled = int(progress * 12)
        bar = "#" * filled + "-" * (12 - filled)
        dots = "." * ((len(self.calibration_samples) // 6) % 4)
        self.loading_text.set(f"Reset/calibrating [{bar}] {int(progress * 100):3d}%{dots}")
        self.reset_button.configure(text="Calibrating...")

    @staticmethod
    def trimmed_mean(values):
        ordered = sorted(values)
        trim = max(1, len(ordered) // 5)
        middle = ordered[trim:-trim] if len(ordered) > trim * 2 else ordered
        return sum(middle) / len(middle)

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
        self.stop()
        self.restore_cursor_size()
        self.joycon.close()
        self.root.destroy()


if __name__ == "__main__":
    App().run()

# Joy-Con Gyro Air Mouse

Python GUI app for Joy-Con, Switch Pro Controller, and some third-party Switch-mode controllers.

## Run

Double-click:

```text
run.bat
```

Or run manually:

```powershell
py -3 app.py
```

When started by Windows startup, the app starts hidden in the system tray. When launched manually, the window opens. Use the tray icon menu to open the window, start/stop, reset the mouse, or quit.

When the app starts, it registers itself in the current Windows user's startup apps. It also keeps trying to connect in the background if no controller is connected.

Only one instance can run at a time. If the app is already running and you launch it again, the existing window is shown instead of starting another copy.

The app is designed for one controller. There is no add-controller step:

1. Put the controller in Switch mode.
2. Pair/connect it in Windows Bluetooth or USB.
3. Open the app.
4. Click Connect.
5. Click Start, or press the controller + button.

This app assumes you hold one Joy-Con vertically, like a small remote.

## Controls

- Gyro yaw/pitch: move mouse
- Yaw controls left/right mouse movement
- Roll controls up/down mouse movement
- Right Joy-Con: ZR, the large trigger, is left click
- Right Joy-Con: R, the small shoulder button, is right click
- Right Joy-Con: X moves the mouse to the center of the screen
- Right Joy-Con: hold Y to pause gyro mouse movement
- Right Joy-Con: A/B actions are configurable in the GUI as mouse actions or key macros
- Left Joy-Con: ZL is left click
- Left Joy-Con: L is right click
- Left Joy-Con: Up moves the mouse to the center of the screen
- Stick up/down: vertical scroll wheel
- Stick left/right: keyboard left/right arrow
- Stick press: middle mouse button
- D-pad: small pointer nudges
- + button: start/stop mouse control
- Smart stabilization: suppresses resting drift while keeping motion responsive

## A/B Macros

The A and B fields accept built-in actions or key macros:

- `Left Click`
- `Right Click`
- `Reset Mouse`
- `Pause Gyro`
- `Space`
- `Enter`
- `Ctrl+C`
- `Ctrl+V`
- `Alt+Tab`
- `Win+H` for Windows voice typing
- Any single letter or number

## Notes

`run.bat` installs `hidapi` into `.deps/python` automatically. It does not install anything globally.

Xbox/XInput mode does not expose gyro. Use Switch mode for gyro.

The reset key does not recalibrate gyro drift. It only centers the mouse and clears smoothing state, which matches normal air-mouse behavior.

The app uses:

- Tkinter for the GUI
- hidapi for Joy-Con / Switch HID input
- Win32 `SendInput` through `ctypes`

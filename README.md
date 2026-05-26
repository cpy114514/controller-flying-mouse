# Joy-Con Gyro Air Mouse

Windows air mouse app for one Joy-Con, Switch Pro Controller, or compatible Switch-mode controller.

## How to Use

1. Put the controller in Switch mode.
2. Pair it with Windows over Bluetooth or USB.
3. Double-click `run.bat`, or use `dist/JoyConGyroAirMouse.exe`.
4. Click `Connect`.
5. Hold the controller still while auto calibration finishes.
6. Click `Start`, or press the controller `+` button.

## Controls

- Yaw: move mouse left/right
- Roll: move mouse up/down
- Right Joy-Con: `ZR` left click, `R` right click, `X` center mouse
- Left Joy-Con: `ZL` left click, `L` right click, `Up` center mouse
- Hold `Y`: pause gyro movement
- Stick up/down: scroll
- Stick left/right: left/right arrow keys
- Stick press: middle mouse button
- `+`: start/stop mouse control
- `A` and `B`: configurable actions/macros

## Notes

- Keep the controller still during calibration.
- Reconnect requires calibration again.
- Xbox/XInput mode does not expose gyro; use Switch mode.
- `Reset Mouse` only centers the cursor. It does not calibrate gyro.
- The app starts with Windows and hides to the system tray on startup.
- Only one app instance can run at a time.

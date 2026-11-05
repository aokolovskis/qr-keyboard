# QRKeyboard: cross-platform (Windows, macOS, Linux)

Same app as the native macOS version in the parent folder: scans QR codes with the camera and **types
them as keyboard input** into the focused window, like a USB barcode scanner. It includes the
MembershipWorks check-in mode.

## Run it (no installs needed)
| OS | Start |
|---|---|
| Windows | double-click `run.bat` (or run it in a terminal) |
| macOS / Linux | `./run.sh` |

On first start the launcher downloads everything into this folder and nowhere else:
- `.tools/`: [uv](https://github.com/astral-sh/uv) 0.9.5 (pinned), a private Python 3.12, and a download cache
- `.venv/`: the libraries pinned in `uv.lock` (OpenCV, numpy; python-xlib on Linux)

This needs internet once, about 350 MB. To remove everything, delete the folder. Settings are saved to
`settings.json` in this folder.

## Window
- **MembershipWorks check-in only:** type only MembershipWorks event check-in codes; others are ignored (beep)
- **Press Enter:** press Enter after each code (MembershipWorks needs it)
- **Setup…:** check-in steps, plus "Turn On & Open MembershipWorks" (ticks the checkbox and opens the admin
  login in your browser); "OK" just closes the dialog
- If the QRKeyboard window itself has keyboard focus, a scan is **not** typed. Click into the target window first.

## Options
    run.bat / ./run.sh [--membershipworks] [--no-enter] [--cooldown S] [--key-delay MS]
                       [--camera N] [--type TEXT] [--decode IMAGE]

- `--camera N`: pick another camera (default 0)
- `--type TEXT`: no camera; type TEXT into the focused window after 3 s and quit (to test typing)
- `--decode IMAGE`: no camera; print the QR codes in an image file and quit (to test decoding)

## Per-OS notes
**Windows.** Keys are sent with `SendInput`, using the real key of your keyboard layout, so browsers see normal
key presses. The window is set to never take focus, so clicking its checkboxes doesn't pull focus from the
browser. Windows can't type into apps running as Administrator unless QRKeyboard also runs as Administrator.

**macOS.** The app you start it from (e.g. Terminal) needs **Camera** and **Accessibility** permission
(System Settings → Privacy & Security). Restart Terminal after granting them.

**Linux.** Needs an **X11** session; keys are sent with XTest. On **Wayland**, apps can't send keys to other
apps. Log in with an "X11"/"Xorg" session, or start the browser under XWayland
(e.g. `google-chrome --ozone-platform=x11`). Camera access requires your user to be in the `video` group
(usually the default).

## MembershipWorks check-in
1. In the MembershipWorks admin, open the event → **Dashboard** → **Scan QR Code** ("Awaiting Scan…").
2. Click into that browser window and keep it in front.
3. Start QRKeyboard with **MembershipWorks check-in only** ticked, then show attendees' QR codes to the camera.

See the parent folder's README for how MembershipWorks validates check-in codes.

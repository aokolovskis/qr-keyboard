# QRKeyboard

Tiny macOS app: watches the camera, decodes QR codes, and **types the contents as keyboard input**
into whatever app has focus, like a USB barcode scanner. No dependencies; it's a single Swift file
that uses AVFoundation for detection and CGEvent for keystrokes.

## Build & run
    ./build.sh
    open build/QRKeyboard.app

Options (run the binary directly):
    build/QRKeyboard.app/Contents/MacOS/QRKeyboard [--no-enter] [--cooldown SECONDS]

- `--no-enter`: don't press Return after each code (Return is on by default)
- `--cooldown`: how many seconds before the same code can be typed again (default 3)

## Permissions (first launch)
- **Camera**: macOS asks for it.
- **Accessibility**: needed to send keystrokes. Enable QRKeyboard under System Settings → Privacy & Security →
  Accessibility, then relaunch.

The preview is a floating panel that never takes focus, so click into your target app and scan.

## Troubleshooting: scans beep but nothing is typed
macOS drops synthetic keystrokes without Accessibility permission (the app now shows
"NOT typed: no Accessibility permission" and plays a Basso sound instead of Tink).
- Launched from Terminal → **Terminal** needs Accessibility.
- Launched with `open` / Finder → **QRKeyboard** needs Accessibility.
- The app is ad-hoc signed, so **every rebuild invalidates the permission**: remove the old QRKeyboard
  entry with the "−" button, add `build/QRKeyboard.app` again with "+", then relaunch.

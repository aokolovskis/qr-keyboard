# QRKeyboard

Tiny macOS app: watches the camera, decodes QR codes, and **types the contents as keyboard input**
into whatever app has focus, like a USB barcode scanner. No dependencies; it's a single Swift file
that uses AVFoundation for detection and CGEvent for keystrokes.

**Windows / Linux / macOS:** see [`cross-platform/`](cross-platform/README.md) for a Python version with
the same features. It runs from `run.bat` / `run.sh` and downloads everything it needs into its own folder.

## Build & run (native macOS version)
    ./build.sh
    open build/QRKeyboard.app

Options (run the binary directly):
    build/QRKeyboard.app/Contents/MacOS/QRKeyboard [--membershipworks] [--no-enter] [--cooldown S] [--key-delay MS] [--type TEXT]

- `--membershipworks`: only type MembershipWorks event check-in codes; other QR codes are ignored
- `--no-enter`: don't press Return after each code (Return is on by default)
- `--cooldown`: how many seconds before the same code can be typed again (default 3)
- `--key-delay`: milliseconds between keystrokes (default 8)
- `--type TEXT`: no camera; type TEXT into the focused window after 3 s and quit (for testing)

## MembershipWorks event check-in
Everything can be set in the window: tick **MembershipWorks check-in only** (keep **Press Enter** on), or click
**Setup…** for the steps plus an "Turn On & Open MembershipWorks" button (ticks the checkbox and opens the admin login in your browser; "OK" just closes the dialog). Settings are remembered; CLI flags override them.

1. Log in at https://membershipworks.com/admin/, open the event, go to **Dashboard** and click **Scan QR Code**
   ("Awaiting Scan..." appears). Keep that Chrome window focused.
2. Start the scanner: `open build/QRKeyboard.app` with the checkbox ticked
   (or `build/QRKeyboard.app/Contents/MacOS/QRKeyboard --membershipworks`)
3. Show attendees' confirmation-email QR codes to the camera. Each one is checked in and its details are shown;
   just keep scanning, there's no need to close the dialog.

How MembershipWorks reads the scan (from its admin JS): a `keydown` listener on `window` appends `event.key`
when it is a single character and submits on Enter (keyCode 13). The buffer must be
`https://membershipworks.com/a/#ec/<code>`, where `<code>` encodes the event ID (chars 0–19) and the
registration ID (chars 20–39) in base 36. A code from another event is rejected with "Check-in code does not match
current event". That's why QRKeyboard sends **one key event per character** (multi-character events are ignored).
Docs: https://support.membershipworks.com/portal/en/kb/articles/check-in-attendees-with-a-qr-code

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

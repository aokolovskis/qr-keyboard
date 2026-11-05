#!/usr/bin/env python3
"""QRKeyboard (cross-platform): scan QR codes with the camera and type their contents as
keyboard input into the focused window, like a USB barcode scanner.

Runs on Windows, macOS and Linux (X11). Start it with run.bat (Windows) or run.sh (macOS/Linux);
those download everything it needs into this folder.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS_FILE = HERE / "settings.json"
MW_ADMIN_URL = "https://membershipworks.com/admin/"
# MembershipWorks' "Scan QR Code" mode accepts exactly this shape (see README).
MW_CHECKIN = re.compile(r"^https://membershipworks\.com/a/#ec/[a-z0-9]{20,}$")

SETUP_TEXT = """\
1. Log in to the MembershipWorks admin and open your event.
2. Go to the event's Dashboard and click "Scan QR Code". "Awaiting Scan…" appears.
3. Click into that browser window and keep it in front. Don't click other apps while scanning.
4. Hold each attendee's QR code (from their confirmation email) up to the camera. Each scan
   checks the attendee in; keep scanning without closing the dialog.

"MembershipWorks check-in only" types only check-in codes, so other QR codes can't interfere.
"Press Enter" must stay on; it submits each code.

One-time event setup (Event → Advanced / Ticketing): add the [qec] tag to the confirmation
email, add the system Email question to each ticket, and enable "Send confirmation email
to all attendees"."""


# ----------------------------------------------------------------------------- settings
class Settings:
    """Window settings, saved to settings.json next to this file. CLI flags override them."""

    def __init__(self) -> None:
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        self.membershipworks_only = bool(data.get("membershipworks_only", False))
        self.send_enter = bool(data.get("send_enter", True))

    def save(self) -> None:
        data = {"membershipworks_only": self.membershipworks_only, "send_enter": self.send_enter}
        try:
            SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass


def text_to_type(code: str, membershipworks_only: bool) -> str | None:
    """Returns the text to type for a scanned code, or None if it should be ignored."""
    text = code.strip()
    if not text:
        return None
    if membershipworks_only and not MW_CHECKIN.match(text):
        return None
    return text


# ----------------------------------------------------------------------------- keyboard
# Every backend sends one real key event per character. Web pages that read KeyboardEvent.key
# (e.g. MembershipWorks scan mode) ignore events that carry several characters at once.

class MacKeyboard:
    """CoreGraphics CGEvents (same mechanism as the native macOS app)."""

    def __init__(self) -> None:
        import ctypes

        self.ct = ctypes
        cg = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cg.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        cg.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        cg.CGEventKeyboardSetUnicodeString.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)]
        cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cg.AXIsProcessTrusted.restype = ctypes.c_bool
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cg, self.cf = cg, cf

    def permission_problem(self) -> str | None:
        if self.cg.AXIsProcessTrusted():
            return None
        return ("No Accessibility permission. Allow the app you started this from (e.g. Terminal) "
                "in System Settings > Privacy & Security > Accessibility, then restart it.")

    def _post(self, keycode: int, text: str | None = None) -> None:
        units = None
        if text:
            raw = text.encode("utf-16-le")
            units = (self.ct.c_uint16 * (len(raw) // 2)).from_buffer_copy(raw)
        for down in (True, False):
            ev = self.cg.CGEventCreateKeyboardEvent(None, keycode, down)
            if units is not None:
                self.cg.CGEventKeyboardSetUnicodeString(ev, len(units), units)
            self.cg.CGEventPost(0, ev)  # kCGHIDEventTap
            self.cf.CFRelease(ev)

    def char(self, ch: str) -> None:
        self._post(0, ch)

    def enter(self) -> None:
        self._post(0x24)  # kVK_Return


class WindowsKeyboard:
    """Win32 SendInput with the real virtual key of the current keyboard layout."""

    VK_SHIFT, VK_CONTROL, VK_MENU, VK_RETURN = 0x10, 0x11, 0x12, 0x0D
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x2, 0x4

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        ulong_ptr = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ulong_ptr)]

        class MOUSEINPUT(ctypes.Structure):  # largest union member; fixes sizeof(INPUT)
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ulong_ptr)]

        class _INPUTUNION(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
        user32.VkKeyScanW.restype = ctypes.c_short
        user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        user32.MapVirtualKeyW.restype = wintypes.UINT
        self.user32, self.INPUT, self.KEYBDINPUT, self.ct = user32, INPUT, KEYBDINPUT, ctypes

    def permission_problem(self) -> str | None:
        return None

    def _send(self, events: list[tuple[int, int, int]]) -> None:
        arr = (self.INPUT * len(events))()
        for i, (vk, scan, flags) in enumerate(events):
            arr[i].type = 1  # INPUT_KEYBOARD
            arr[i].u.ki = self.KEYBDINPUT(vk, scan, flags, 0, 0)
        self.user32.SendInput(len(events), arr, self.ct.sizeof(self.INPUT))

    def _vk(self, vk: int, up: bool) -> tuple[int, int, int]:
        return (vk, self.user32.MapVirtualKeyW(vk, 0), self.KEYEVENTF_KEYUP if up else 0)

    def char(self, ch: str) -> None:
        res = self.user32.VkKeyScanW(ch) if ord(ch) <= 0xFFFF else -1
        if res == -1:  # not on this keyboard layout: send as a Unicode character
            units = ch.encode("utf-16-le")
            ev = []
            for i in range(0, len(units), 2):
                code = int.from_bytes(units[i:i + 2], "little")
                ev += [(0, code, self.KEYEVENTF_UNICODE),
                       (0, code, self.KEYEVENTF_UNICODE | self.KEYEVENTF_KEYUP)]
            self._send(ev)
            return
        vk, mods = res & 0xFF, (res >> 8) & 0xFF
        mod_vks = [m for bit, m in ((1, self.VK_SHIFT), (2, self.VK_CONTROL), (4, self.VK_MENU))
                   if mods & bit]
        self._send([self._vk(m, False) for m in mod_vks] + [self._vk(vk, False), self._vk(vk, True)]
                   + [self._vk(m, True) for m in reversed(mod_vks)])

    def enter(self) -> None:
        self._send([self._vk(self.VK_RETURN, False), self._vk(self.VK_RETURN, True)])


class X11Keyboard:
    """X11 XTest key events (pure Python via python-xlib)."""

    def __init__(self) -> None:
        if not os.environ.get("DISPLAY"):
            raise RuntimeError("No X11 display (DISPLAY is not set). On Wayland, start an X11 "
                               "session or run the target app under XWayland.")
        from Xlib import XK, X, display
        from Xlib.ext import xtest

        self.X, self.XK, self.xtest = X, XK, xtest
        self.d = display.Display()
        if not self.d.has_extension("XTEST"):
            raise RuntimeError("The X server has no XTEST extension; cannot send key events.")
        self.shift = self.d.keysym_to_keycode(XK.XK_Shift_L)
        self._spare: int | None = None

    def permission_problem(self) -> str | None:
        return None

    @staticmethod
    def _keysym(ch: str) -> int:
        o = ord(ch)
        return o if (0x20 <= o <= 0x7E or 0xA0 <= o <= 0xFF) else 0x01000000 | o

    def _spare_keycode(self) -> int:
        """An unused keycode we can temporarily map to characters missing from the layout."""
        if self._spare is None:
            first = self.d.display.info.min_keycode
            count = self.d.display.info.max_keycode - first + 1
            for i, syms in enumerate(self.d.get_keyboard_mapping(first, count)):
                if not any(syms):
                    self._spare = first + i
                    break
            else:
                self._spare = self.d.display.info.max_keycode
        return self._spare

    def _tap(self, keycode: int, shift: bool = False) -> None:
        fake = self.xtest.fake_input
        if shift:
            fake(self.d, self.X.KeyPress, self.shift)
        fake(self.d, self.X.KeyPress, keycode)
        fake(self.d, self.X.KeyRelease, keycode)
        if shift:
            fake(self.d, self.X.KeyRelease, self.shift)
        self.d.sync()

    def char(self, ch: str) -> None:
        ks = self._keysym(ch)
        for keycode, index in self.d.keysym_to_keycodes(ks):
            if index in (0, 1):  # plain or Shift level
                self._tap(keycode, shift=index == 1)
                return
        keycode = self._spare_keycode()  # not on the layout: remap a spare key to it
        self.d.change_keyboard_mapping(keycode, [(ks, ks)])
        self.d.sync()
        time.sleep(0.02)
        self._tap(keycode)

    def enter(self) -> None:
        self._tap(self.d.keysym_to_keycode(self.XK.XK_Return))


def make_keyboard():
    if sys.platform == "darwin":
        return MacKeyboard()
    if sys.platform == "win32":
        return WindowsKeyboard()
    return X11Keyboard()


def type_text(kb, text: str, enter: bool, delay_s: float) -> None:
    for ch in text:
        kb.char(ch)
        time.sleep(delay_s)
    if enter:
        kb.enter()


# ----------------------------------------------------------------------------- camera
def decode_qr(detector, frame) -> list[str]:
    try:
        ok, texts, _, _ = detector.detectAndDecodeMulti(frame)
        if ok:
            return [t for t in texts if t]
    except Exception:
        pass
    text, _, _ = detector.detectAndDecode(frame)
    return [text] if text else []


class Scanner(threading.Thread):
    """Reads the camera on a background thread, keeps the latest frame and queues decoded codes."""

    def __init__(self, camera_index: int) -> None:
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.codes: queue.Queue[str] = queue.Queue()
        self.frame = None
        self.error: str | None = None
        self.running = True

    def run(self) -> None:
        import cv2

        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.camera_index, backend)
        if not cap.isOpened():
            self.error = (f"Could not open camera {self.camera_index}. Check camera permission "
                          "(macOS: allow Terminal under Privacy & Security > Camera, then restart).")
            return
        detector = cv2.QRCodeDetector()
        last_decode = 0.0
        while self.running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            self.frame = frame
            now = time.monotonic()
            if now - last_decode >= 0.1:  # ~10 decodes per second is plenty
                last_decode = now
                for text in decode_qr(detector, frame):
                    self.codes.put(text)
        cap.release()


# ----------------------------------------------------------------------------- UI
class App:
    WIDTH, HEIGHT = 320, 240

    def __init__(self, settings: Settings, kb, kb_error: str | None, scanner: Scanner,
                 cooldown: float, key_delay: float) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk = tk, ttk
        self.settings, self.kb, self.kb_error, self.scanner = settings, kb, kb_error, scanner
        self.cooldown, self.key_delay = cooldown, key_delay
        self.last_code, self.last_time = "", 0.0
        self.typing = False

        self.root = root = tk.Tk()
        root.title("QR → Keyboard")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        self.video = tk.Label(root, bg="black", width=self.WIDTH, height=self.HEIGHT)
        self.video.grid(row=0, column=0, columnspan=2)
        self.photo = None

        self.mw_var = tk.BooleanVar(value=settings.membershipworks_only)
        self.enter_var = tk.BooleanVar(value=settings.send_enter)
        ttk.Checkbutton(root, text="MembershipWorks check-in only", variable=self.mw_var,
                        command=self.toggle_mw).grid(row=1, column=0, columnspan=2, sticky="w",
                                                     padx=8, pady=(6, 0))
        ttk.Checkbutton(root, text="Press Enter", variable=self.enter_var,
                        command=self.toggle_enter).grid(row=2, column=0, sticky="w", padx=8)
        ttk.Button(root, text="Setup…", command=self.show_setup).grid(row=2, column=1, sticky="e",
                                                                       padx=8)
        self.status = ttk.Label(root, text=self.ready_message(), width=44)
        self.status.grid(row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 8))
        if kb_error:
            self.set_status(kb_error)

        self._no_activate()
        root.after(33, self.poll)

    # Windows: never take focus from the browser, even when a checkbox is clicked.
    def _no_activate(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        self.root.update_idletasks()
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(self.root.winfo_id())
        GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                              | WS_EX_NOACTIVATE)

    def ready_message(self) -> str:
        if self.settings.membershipworks_only:
            return 'MembershipWorks: keep "Awaiting Scan…" in front'
        return "Point a QR code at the camera…"

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def toggle_mw(self) -> None:
        self.settings.membershipworks_only = self.mw_var.get()
        if self.settings.membershipworks_only:  # MembershipWorks needs Enter to submit
            self.settings.send_enter = True
            self.enter_var.set(True)
        self.settings.save()
        self.set_status(self.ready_message())

    def toggle_enter(self) -> None:
        self.settings.send_enter = self.enter_var.get()
        self.settings.save()

    def show_setup(self) -> None:
        tk, ttk = self.tk, self.ttk
        win = tk.Toplevel(self.root)
        win.title("MembershipWorks event check-in")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        ttk.Label(win, text=SETUP_TEXT, justify="left", wraplength=520).pack(padx=16, pady=16)
        row = ttk.Frame(win)
        row.pack(fill="x", padx=16, pady=(0, 16))

        def turn_on() -> None:
            self.mw_var.set(True)
            self.toggle_mw()
            webbrowser.open(MW_ADMIN_URL)
            win.destroy()

        ttk.Button(row, text="OK", command=win.destroy).pack(side="right")
        ttk.Button(row, text="Turn On & Open MembershipWorks", command=turn_on).pack(
            side="right", padx=(0, 8))
        win.focus_force()

    def show_frame(self) -> None:
        import cv2

        frame = self.scanner.frame
        if frame is None:
            return
        h, w = frame.shape[:2]
        target = self.WIDTH / self.HEIGHT
        if w / h > target:  # crop to 4:3, then scale
            cw = int(h * target)
            frame = frame[:, (w - cw) // 2:(w - cw) // 2 + cw]
        else:
            ch = int(w / target)
            frame = frame[(h - ch) // 2:(h - ch) // 2 + ch]
        frame = cv2.resize(frame, (self.WIDTH, self.HEIGHT))
        ok, png = cv2.imencode(".png", frame)
        if ok:
            self.photo = self.tk.PhotoImage(data=base64.b64encode(png.tobytes()))
            self.video.configure(image=self.photo, width=self.WIDTH, height=self.HEIGHT)

    def poll(self) -> None:
        self.show_frame()
        if self.scanner.error:
            self.set_status(self.scanner.error)
        while True:
            try:
                code = self.scanner.codes.get_nowait()
            except queue.Empty:
                break
            self.handle(code)
        self.root.after(33, self.poll)

    def handle(self, code: str) -> None:
        now = time.monotonic()
        if code == self.last_code and now - self.last_time < self.cooldown:
            return
        self.last_code, self.last_time = code, now
        print(code, flush=True)

        text = text_to_type(code, self.settings.membershipworks_only)
        if text is None:
            self.set_status("Ignored (not a check-in code)")
            self.root.bell()
            return
        problem = self.kb_error or (self.kb.permission_problem() if self.kb else "No keyboard")
        if problem:
            self.set_status("NOT typed: " + problem)
            print("Not typed: " + problem, file=sys.stderr, flush=True)
            self.root.bell()
            return
        if self.root.focus_get() is not None:  # our own window has focus: keys would land here
            self.set_status("NOT typed: click into the target window first")
            self.root.bell()
            return
        if self.typing:
            return
        self.set_status(f"Typed: {text}")
        self.typing = True

        def work() -> None:
            try:
                type_text(self.kb, text, self.settings.send_enter, self.key_delay)
            finally:
                self.typing = False

        threading.Thread(target=work, daemon=True).start()

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self.scanner.running = False


# ----------------------------------------------------------------------------- main
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--membershipworks", action="store_true",
                   help="only type MembershipWorks event check-in codes")
    p.add_argument("--no-enter", action="store_true", help="don't press Enter after each code")
    p.add_argument("--cooldown", type=float, default=3.0,
                   help="seconds before the same code is typed again (default 3)")
    p.add_argument("--key-delay", type=float, default=8.0,
                   help="milliseconds between keystrokes (default 8)")
    p.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    p.add_argument("--type", metavar="TEXT",
                   help="no camera: type TEXT into the focused window after 3 s, then quit")
    p.add_argument("--decode", metavar="IMAGE",
                   help="no camera: print the QR codes found in an image file, then quit")
    a = p.parse_args()

    settings = Settings()
    if a.membershipworks:
        settings.membershipworks_only = True
    if a.no_enter:
        settings.send_enter = False

    if a.decode:
        import cv2

        img = cv2.imread(a.decode)
        if img is None:
            print(f"Cannot read {a.decode}", file=sys.stderr)
            return 1
        codes = decode_qr(cv2.QRCodeDetector(), img)
        for c in codes:
            print(c)
        return 0 if codes else 2

    kb, kb_error = None, None
    try:
        kb = make_keyboard()
    except Exception as e:  # e.g. no X11 display
        kb_error = str(e)

    if a.type is not None:
        problem = kb_error or kb.permission_problem()
        if problem:
            print(problem, file=sys.stderr)
            return 1
        print("Typing in 3 s — focus the target window…", flush=True)
        time.sleep(3)
        type_text(kb, a.type, settings.send_enter, a.key_delay / 1000)
        return 0

    scanner = Scanner(a.camera)
    scanner.start()
    App(settings, kb, kb_error, scanner, a.cooldown, a.key_delay / 1000).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

// QRKeyboard — scans QR codes from the camera and types their contents
// into whatever app currently has keyboard focus (like a USB barcode scanner).
import AppKit
import AVFoundation
import ApplicationServices
import Vision

// MARK: - Config (CLI flags)
let args = CommandLine.arguments
func flagValue(_ name: String) -> String? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}
let sendEnter = !args.contains("--no-enter")                         // press Return after each code
let cooldown = TimeInterval(flagValue("--cooldown") ?? "") ?? 3      // ignore the same code for N seconds
let keyDelayMs = UInt32(flagValue("--key-delay") ?? "") ?? 8         // pause between keystrokes
// --membershipworks: only type MembershipWorks event check-in codes; ignore any other QR code.
let membershipWorksOnly = args.contains("--membershipworks")
// --type TEXT: no camera; type TEXT into the focused app after 3 s, then quit (for testing).
let typeOnce = flagValue("--type")

/// MembershipWorks' "Scan QR Code" mode accepts exactly this shape (see README).
let mwCheckIn = try! NSRegularExpression(pattern: "^https://membershipworks\\.com/a/#ec/[a-z0-9]{20,}$")

/// Returns the text to type for a scanned code, or nil if it should be ignored.
func textToType(for code: String) -> String? {
    let text = code.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty else { return nil }
    if membershipWorksOnly {
        let range = NSRange(text.startIndex..., in: text)
        guard mwCheckIn.firstMatch(in: text, range: range) != nil else { return nil }
    }
    return text
}

// MARK: - Keyboard output
enum Keyboard {
    static let source = CGEventSource(stateID: .hidSystemState)

    /// Types one key event per character, like a hardware scanner. Web pages that read
    /// `KeyboardEvent.key` (e.g. MembershipWorks scan mode) ignore multi-character events.
    static func type(_ text: String) {
        for ch in text {
            let units = Array(String(ch).utf16)
            for down in [true, false] {
                guard let ev = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down) else { continue }
                ev.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units)
                ev.post(tap: .cghidEventTap)
            }
            usleep(keyDelayMs * 1000)
        }
        if sendEnter { press(key: 0x24) } // kVK_Return -> keyCode 13
    }

    static func press(key: CGKeyCode) {
        CGEvent(keyboardEventSource: source, virtualKey: key, keyDown: true)?.post(tap: .cghidEventTap)
        CGEvent(keyboardEventSource: source, virtualKey: key, keyDown: false)?.post(tap: .cghidEventTap)
    }
}

// MARK: - Camera + QR detection (Vision; AVCaptureMetadataOutput has no QR support on macOS)
final class Scanner: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()
    var onCode: ((String) -> Void)?
    private var lastCode = ""
    private var lastTime = Date.distantPast
    private var lastFrame = Date.distantPast
    private let queue = DispatchQueue(label: "qr.frames")
    private lazy var request: VNDetectBarcodesRequest = {
        let r = VNDetectBarcodesRequest()
        r.symbologies = [.qr]
        return r
    }()

    func start() throws {
        guard let device = AVCaptureDevice.default(for: .video) else {
            throw NSError(domain: "QRKeyboard", code: 1, userInfo: [NSLocalizedDescriptionKey: "No camera found"])
        }
        let input = try AVCaptureDeviceInput(device: device)
        session.beginConfiguration()
        session.sessionPreset = .high
        if session.canAddInput(input) { session.addInput(input) }
        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) { session.addOutput(output) }
        session.commitConfiguration()
        DispatchQueue.global(qos: .userInitiated).async { self.session.startRunning() }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        let now = Date()
        guard now.timeIntervalSince(lastFrame) > 0.1,               // ~10 scans/sec is plenty
              let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastFrame = now
        try? VNImageRequestHandler(cvPixelBuffer: pixels, options: [:]).perform([request])
        for obs in request.results ?? [] {
            guard let value = obs.payloadStringValue, !value.isEmpty else { continue }
            if value == lastCode && now.timeIntervalSince(lastTime) < cooldown { continue }
            lastCode = value
            lastTime = now
            DispatchQueue.main.async { self.onCode?(value) }
        }
    }
}

// MARK: - UI: small floating, non-activating preview panel
final class AppDelegate: NSObject, NSApplicationDelegate {
    let scanner = Scanner()
    var panel: NSPanel!
    let status = NSTextField(labelWithString: "Point a QR code at the camera…")

    func applicationDidFinishLaunching(_ note: Notification) {
        // Ask for Accessibility permission (needed to synthesize key presses).
        let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        if !AXIsProcessTrustedWithOptions(opts) {
            status.stringValue = "Grant Accessibility access, then relaunch."
        }

        // Non-activating panel so keystrokes go to the app you were using, not to us.
        panel = NSPanel(contentRect: NSRect(x: 0, y: 0, width: 320, height: 270),
                        styleMask: [.titled, .closable, .nonactivatingPanel, .utilityWindow],
                        backing: .buffered, defer: false)
        panel.title = "QR → Keyboard"
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true

        let content = NSView(frame: panel.contentRect(forFrameRect: panel.frame))
        let preview = NSView(frame: NSRect(x: 0, y: 30, width: 320, height: 240))
        preview.wantsLayer = true
        let layer = AVCaptureVideoPreviewLayer(session: scanner.session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = preview.bounds
        preview.layer = layer
        status.frame = NSRect(x: 8, y: 6, width: 304, height: 18)
        status.lineBreakMode = .byTruncatingTail
        content.addSubview(preview)
        content.addSubview(status)
        panel.contentView = content
        panel.setFrameTopLeftPoint(NSPoint(x: 40, y: (NSScreen.main?.visibleFrame.maxY ?? 800) - 40))
        panel.orderFrontRegardless()

        scanner.onCode = { [weak self] code in
            print(code); fflush(stdout)
            guard let text = textToType(for: code) else {
                self?.status.stringValue = "Ignored (not a check-in code)"
                NSSound(named: "Funk")?.play()
                return
            }
            guard AXIsProcessTrusted() else {
                // macOS silently drops synthetic keystrokes without Accessibility permission.
                self?.status.stringValue = "NOT typed: no Accessibility permission"
                FileHandle.standardError.write(Data((
                    "Not typed: no Accessibility permission. Enable it in System Settings > Privacy & Security > " +
                    "Accessibility for QRKeyboard (via `open`) or for Terminal (if run from Terminal), then relaunch.\n").utf8))
                NSSound(named: "Basso")?.play()
                return
            }
            self?.status.stringValue = "Typed: \(text)"
            Keyboard.type(text)
            NSSound(named: "Tink")?.play()
        }

        AVCaptureDevice.requestAccess(for: .video) { granted in
            DispatchQueue.main.async {
                guard granted else { self.status.stringValue = "Camera access denied."; return }
                do { try self.scanner.start() } catch { self.status.stringValue = error.localizedDescription }
            }
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
}

if let text = typeOnce {
    guard AXIsProcessTrusted() else {
        FileHandle.standardError.write(Data("No Accessibility permission; cannot type.\n".utf8)); exit(1)
    }
    print("Typing in 3 s — focus the target window…"); fflush(stdout)
    sleep(3)
    Keyboard.type(text)
    exit(0)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory) // no Dock icon, never steals focus
let delegate = AppDelegate()
app.delegate = delegate
app.run()

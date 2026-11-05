// QRKeyboard — scans QR codes from the camera and types their contents
// into whatever app currently has keyboard focus (like a USB barcode scanner).
import AppKit
import AVFoundation
import ApplicationServices
import Vision

// MARK: - Config (via env vars or CLI flags)
let args = CommandLine.arguments
let sendEnter = !args.contains("--no-enter")          // press Return after each code
let cooldown: TimeInterval = {                       // ignore the same code for N seconds
    if let i = args.firstIndex(of: "--cooldown"), i + 1 < args.count, let v = Double(args[i + 1]) { return v }
    return 3
}()

// MARK: - Keyboard output
enum Keyboard {
    static let source = CGEventSource(stateID: .hidSystemState)

    static func type(_ text: String) {
        // CGEvent accepts up to ~20 UTF-16 units per event, so send in chunks.
        let units = Array(text.utf16)
        var i = 0
        while i < units.count {
            let chunk = Array(units[i..<min(i + 20, units.count)])
            for down in [true, false] {
                guard let ev = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down) else { continue }
                ev.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk)
                ev.post(tap: .cghidEventTap)
            }
            usleep(2000)
            i += 20
        }
        if sendEnter { press(key: 0x24) } // kVK_Return
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
            guard AXIsProcessTrusted() else {
                // macOS silently drops synthetic keystrokes without Accessibility permission.
                self?.status.stringValue = "NOT typed: no Accessibility permission"
                FileHandle.standardError.write(Data((
                    "Not typed: no Accessibility permission. Enable it in System Settings > Privacy & Security > " +
                    "Accessibility for QRKeyboard (via `open`) or for Terminal (if run from Terminal), then relaunch.\n").utf8))
                NSSound(named: "Basso")?.play()
                return
            }
            self?.status.stringValue = "Typed: \(code)"
            Keyboard.type(code)
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

let app = NSApplication.shared
app.setActivationPolicy(.accessory) // no Dock icon, never steals focus
let delegate = AppDelegate()
app.delegate = delegate
app.run()

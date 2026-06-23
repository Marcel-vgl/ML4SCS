import Foundation
import WatchConnectivity

enum AppMode: String {
    case label
    case predict
}

/// Steuert die Uhr (Start/Stop + Session-Name + Modus), empfängt Live-Batches und
/// die am Ende übertragene CSV-Datei. Im Predict-Modus werden die Live-Batches ans
/// Mac-Dashboard weitergeleitet.
final class PhoneWatchBridge: NSObject, ObservableObject, WCSessionDelegate {
    private let labelStartLeadTime: TimeInterval = 1.25

    @Published var watchReachable = false
    @Published var receivedSamples = 0
    @Published var lastSampleRate = 0.0
    @Published var isRunning = false
    @Published var mode: AppMode = .label
    @Published var lastTransport = "wartet"
    /// Optional: im Predict-Modus zusätzlich ans Mac-Dashboard senden (Standard aus,
    /// da die Erkennung jetzt on-device läuft).
    @Published var alsoSendToMac = false

    let mac: MacHTTPClient
    let store: RecordingStore
    let video: LabelVideoRecorder
    let predictor: StrokePredictor

    private var rateWindowStart = Date()
    private var rateWindowCount = 0

    init(mac: MacHTTPClient, store: RecordingStore, video: LabelVideoRecorder, predictor: StrokePredictor) {
        self.mac = mac
        self.store = store
        self.video = video
        self.predictor = predictor
        super.init()
        self.video.onRecordingFinished = { [weak store] in
            store?.refresh()
        }
        activate()
    }

    func activate() {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
    }

    // MARK: - Steuerung

    func start(session: String) {
        receivedSamples = 0
        if mode == .label {
            video.startRecording(sessionID: session) { [weak self] started in
                guard let self else { return }
                guard started else {
                    self.isRunning = false
                    return
                }
                let sessionAnchorUnix = Date().timeIntervalSince1970 + self.labelStartLeadTime
                self.video.setSessionAnchor(sessionAnchorUnix)
                self.isRunning = true
                let payload: [String: Any] = [
                    "command": "start",
                    "session": session,
                    "mode": self.mode.rawValue,
                    "start_at_unix_s": sessionAnchorUnix,
                    "session_anchor_unix_s": sessionAnchorUnix,
                ]
                self.sendToWatch(payload)
            }
            return
        }

        isRunning = true
        predictor.start()
        let payload: [String: Any] = ["command": "start", "session": session, "mode": mode.rawValue]
        sendToWatch(payload)
    }

    func stop() {
        isRunning = false
        if mode == .label {
            video.stopRecording()
        } else {
            predictor.stop()
        }
        sendToWatch(["command": "stop"])
    }

    private func sendToWatch(_ payload: [String: Any]) {
        let session = WCSession.default
        guard session.activationState == .activated else { return }
        // Live, wenn die Uhr erreichbar ist ...
        if session.isReachable {
            session.sendMessage(payload, replyHandler: nil, errorHandler: nil)
        }
        // ... und zusätzlich als Application-Context (kommt auch verzögert an).
        try? session.updateApplicationContext(payload)
    }

    // MARK: - Datenempfang

    private func handle(batch: SensorBatch, transport: String) {
        let count = batch.samples.count
        if mode == .predict {
            // On-device Erkennung (ersetzt das Mac-Dashboard).
            predictor.add(batch.samples)
            // Optional zusätzlich ans Mac senden (Vergleich/Backup).
            if alsoSendToMac {
                var forwarded = batch
                forwarded.source = "iphone_bridge"
                forwarded.bridge_received_unix_s = Date().timeIntervalSince1970
                mac.send(forwarded)
            }
        }
        DispatchQueue.main.async {
            self.receivedSamples += count
            self.rateWindowCount += count
            self.lastTransport = transport
            let elapsed = Date().timeIntervalSince(self.rateWindowStart)
            if elapsed >= 1.0 {
                self.lastSampleRate = Double(self.rateWindowCount) / elapsed
                self.rateWindowStart = Date()
                self.rateWindowCount = 0
            }
        }
    }

    // MARK: - WCSessionDelegate

    func session(_ session: WCSession,
                 activationDidCompleteWith activationState: WCSessionActivationState,
                 error: Error?) {
        DispatchQueue.main.async { self.watchReachable = session.isReachable }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async { self.watchReachable = session.isReachable }
    }

    func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any] = [:]) {
        if let data = userInfo["batch"] as? Data,
           let batch = try? JSONDecoder().decode(SensorBatch.self, from: data) {
            handle(batch: batch, transport: "Hintergrund")
        }
    }

    func session(_ session: WCSession, didReceiveMessageData messageData: Data) {
        if let batch = try? JSONDecoder().decode(SensorBatch.self, from: messageData) {
            handle(batch: batch, transport: "live")
        }
    }

    /// Empfängt die komplette CSV-Datei von der Uhr am Ende der Session.
    func session(_ session: WCSession, didReceive file: WCSessionFile) {
        let sessionName = file.metadata?["session"] as? String
        let modeName = file.metadata?["mode"] as? String
        let fileMode = modeName.flatMap(AppMode.init(rawValue:)) ?? .label
        store.saveReceived(file: file.fileURL, session: sessionName, mode: fileMode)
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        WCSession.default.activate()
    }
}

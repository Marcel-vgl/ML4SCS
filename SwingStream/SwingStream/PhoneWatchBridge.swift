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
    @Published var watchReachable = false
    @Published var receivedSamples = 0
    @Published var lastSampleRate = 0.0
    @Published var isRunning = false
    @Published var mode: AppMode = .label

    let mac: MacHTTPClient
    let store: RecordingStore

    private var rateWindowStart = Date()
    private var rateWindowCount = 0

    init(mac: MacHTTPClient, store: RecordingStore) {
        self.mac = mac
        self.store = store
        super.init()
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
        isRunning = true
        receivedSamples = 0
        let payload: [String: Any] = ["command": "start", "session": session, "mode": mode.rawValue]
        sendToWatch(payload)
    }

    func stop() {
        isRunning = false
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

    private func handle(batch: SensorBatch) {
        let count = batch.samples.count
        if mode == .predict {
            var forwarded = batch
            forwarded.source = "iphone_bridge"
            forwarded.bridge_received_unix_s = Date().timeIntervalSince1970
            mac.send(forwarded)
        }
        DispatchQueue.main.async {
            self.receivedSamples += count
            self.rateWindowCount += count
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
            handle(batch: batch)
        }
    }

    /// Empfängt die komplette CSV-Datei von der Uhr am Ende der Session.
    func session(_ session: WCSession, didReceive file: WCSessionFile) {
        let sessionName = file.metadata?["session"] as? String
        store.saveReceived(file: file.fileURL, session: sessionName)
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        WCSession.default.activate()
    }
}

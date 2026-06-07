import Foundation
import WatchConnectivity

/// WatchConnectivity-Verbindung der Uhr:
/// - empfängt Start/Stop-Befehle (mit Session-Name) vom iPhone,
/// - überträgt Live-Batches per `transferUserInfo` (Hintergrund-fähig, Bluetooth),
/// - schickt am Ende die komplette CSV-Datei per `transferFile` ans iPhone.
final class WatchConnectivitySender: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = WatchConnectivitySender()

    @Published var phoneReachable = false
    @Published var sentBatches = 0

    /// Befehl vom iPhone: ("start"/"stop", sessionName).
    var onCommand: ((String, String) -> Void)?

    private override init() {
        super.init()
        activate()
    }

    func activate() {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
    }

    /// Live-Batch (für Vorschau / Predict-Weiterleitung). Verlustfreiheit kommt aus
    /// der lokalen Datei, daher ist ein gelegentlich verworfener Live-Batch egal.
    func send(_ batch: SensorBatch) {
        let session = WCSession.default
        guard session.activationState == .activated else { return }
        guard let data = try? JSONEncoder().encode(batch) else { return }
        session.transferUserInfo(["batch": data])
        DispatchQueue.main.async {
            self.sentBatches += 1
            self.phoneReachable = session.isReachable
        }
    }

    /// Überträgt die fertige CSV-Datei ans iPhone (persistent, auch im Hintergrund).
    func transferFile(_ url: URL, session: String) {
        WCSession.default.transferFile(url, metadata: ["session": session])
    }

    private func handle(_ payload: [String: Any]) {
        guard let command = payload["command"] as? String else { return }
        let session = (payload["session"] as? String) ?? ""
        DispatchQueue.main.async { self.onCommand?(command, session) }
    }

    // MARK: - WCSessionDelegate

    func session(_ session: WCSession,
                 activationDidCompleteWith activationState: WCSessionActivationState,
                 error: Error?) {
        DispatchQueue.main.async { self.phoneReachable = session.isReachable }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        DispatchQueue.main.async { self.phoneReachable = session.isReachable }
    }

    func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        handle(message)
    }

    func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        handle(applicationContext)
    }
}

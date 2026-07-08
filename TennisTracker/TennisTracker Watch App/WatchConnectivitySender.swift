import Foundation
import WatchConnectivity

/// WatchConnectivity-Verbindung der Uhr:
/// - empfängt Start/Stop-Befehle (mit Session-Name) vom iPhone,
/// - überträgt Live-Batches live per `sendMessageData`, mit `transferUserInfo`
///   als Hintergrund-Fallback,
/// - schickt am Ende die komplette CSV-Datei per `transferFile` ans iPhone.
final class WatchConnectivitySender: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = WatchConnectivitySender()

    @Published var phoneReachable = false
    @Published var sentBatches = 0
    @Published var queuedBatches = 0
    @Published var failedBatches = 0

    /// Befehl vom iPhone: ("start"/"stop", sessionName, geplanter Startzeitpunkt, Modus).
    var onCommand: ((String, String, Double?, String?) -> Void)?

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
        if session.isReachable {
            session.sendMessageData(data, replyHandler: nil) { [weak self] _ in
                self?.queue(batchData: data)
            }
            DispatchQueue.main.async {
                self.sentBatches += 1
                self.phoneReachable = true
            }
            return
        }
        queue(batchData: data)
    }

    private func queue(batchData data: Data) {
        WCSession.default.transferUserInfo(["batch": data])
        DispatchQueue.main.async {
            self.queuedBatches += 1
            self.phoneReachable = WCSession.default.isReachable
        }
    }

    /// Überträgt die fertige CSV-Datei ans iPhone (persistent, auch im Hintergrund).
    func transferFile(_ url: URL, session: String, mode: String) {
        WCSession.default.transferFile(url, metadata: ["session": session, "mode": mode])
    }

    private func handle(_ payload: [String: Any]) {
        guard let command = payload["command"] as? String else { return }
        let session = (payload["session"] as? String) ?? ""
        let mode = payload["mode"] as? String
        let startAtUnix = Self.doubleValue(payload["start_at_unix_s"])
            ?? Self.doubleValue(payload["session_anchor_unix_s"])
        DispatchQueue.main.async { self.onCommand?(command, session, startAtUnix, mode) }
    }

    private static func doubleValue(_ value: Any?) -> Double? {
        if let value = value as? Double { return value }
        if let value = value as? NSNumber { return value.doubleValue }
        if let value = value as? String { return Double(value) }
        return nil
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

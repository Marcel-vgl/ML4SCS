import Foundation
import WatchConnectivity

/// Sendet Sensor-Batches von der Watch ans iPhone über `WCSession.sendMessageData`.
/// Batches werden nur gesendet, wenn das iPhone erreichbar ist; andernfalls werden
/// sie verworfen (Live-Streaming – fehlende Samples sind über `sequence` erkennbar).
final class WatchConnectivitySender: NSObject, ObservableObject, WCSessionDelegate {
    static let shared = WatchConnectivitySender()

    @Published var phoneReachable = false
    @Published var sentBatches = 0
    @Published var droppedBatches = 0

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

    func send(_ batch: SensorBatch) {
        let session = WCSession.default
        guard session.activationState == .activated, session.isReachable else {
            DispatchQueue.main.async { self.droppedBatches += 1 }
            return
        }
        guard let data = try? JSONEncoder().encode(batch) else { return }
        session.sendMessageData(data, replyHandler: nil) { [weak self] _ in
            DispatchQueue.main.async { self?.droppedBatches += 1 }
        }
        DispatchQueue.main.async { self.sentBatches += 1 }
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
}

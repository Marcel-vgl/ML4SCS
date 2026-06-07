import Foundation
import WatchConnectivity

/// Empfängt Sensor-Batches der Watch über `WCSession`, ergänzt Bridge-Metadaten
/// und leitet sie per HTTP an das Mac-Dashboard weiter.
final class PhoneWatchBridge: NSObject, ObservableObject, WCSessionDelegate {
    @Published var watchReachable = false
    @Published var receivedSamples = 0
    @Published var receivedBatches = 0
    @Published var lastSampleRate = 0.0

    let mac: MacHTTPClient

    private var rateWindowStart = Date()
    private var rateWindowCount = 0

    init(mac: MacHTTPClient) {
        self.mac = mac
        super.init()
        activate()
    }

    func activate() {
        guard WCSession.isSupported() else { return }
        let session = WCSession.default
        session.delegate = self
        session.activate()
    }

    private func handle(data: Data) {
        guard var batch = try? JSONDecoder().decode(SensorBatch.self, from: data) else {
            return
        }
        batch.source = "iphone_bridge"
        batch.bridge_received_unix_s = Date().timeIntervalSince1970

        let count = batch.samples.count
        mac.send(batch)

        DispatchQueue.main.async {
            self.receivedBatches += 1
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

    func session(_ session: WCSession, didReceiveMessageData messageData: Data) {
        handle(data: messageData)
    }

    func session(_ session: WCSession,
                 didReceiveMessageData messageData: Data,
                 replyHandler: @escaping (Data) -> Void) {
        handle(data: messageData)
        replyHandler(Data())
    }

    // iOS verlangt diese beiden Stubs für Session-Reaktivierung (App-Wechsel).
    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        WCSession.default.activate()
    }
}

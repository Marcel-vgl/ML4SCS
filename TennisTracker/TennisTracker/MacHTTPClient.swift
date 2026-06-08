import Foundation
import Combine

/// Sendet Sensor-Batches per HTTP POST an das Mac-Dashboard (`/api/ingest`).
/// Host und Port werden in den UserDefaults gespeichert.
final class MacHTTPClient: ObservableObject {
    @Published var host: String {
        didSet { UserDefaults.standard.set(host, forKey: "mac_host") }
    }
    @Published var port: Int {
        didSet { UserDefaults.standard.set(port, forKey: "mac_port") }
    }

    @Published var reachable = false
    @Published var sentBatches = 0
    @Published var failedBatches = 0
    @Published var lastError = ""

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 5
        config.waitsForConnectivity = false
        return URLSession(configuration: config)
    }()
    private let encoder = JSONEncoder()

    init() {
        let defaults = UserDefaults.standard
        host = defaults.string(forKey: "mac_host") ?? "192.168.1.50"
        let savedPort = defaults.integer(forKey: "mac_port")
        port = savedPort == 0 ? 8788 : savedPort
    }

    private var ingestURL: URL? {
        URL(string: "http://\(host):\(port)/api/ingest")
    }

    func send(_ batch: SensorBatch) {
        guard let url = ingestURL, let body = try? encoder.encode(batch) else {
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        session.dataTask(with: request) { [weak self] _, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                if let error {
                    self.reachable = false
                    self.failedBatches += 1
                    self.lastError = error.localizedDescription
                    return
                }
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    self.reachable = true
                    self.sentBatches += 1
                } else {
                    self.reachable = false
                    self.failedBatches += 1
                    self.lastError = "HTTP \( (response as? HTTPURLResponse)?.statusCode ?? -1)"
                }
            }
        }.resume()
    }

    /// Einfacher Verbindungstest (leerer Batch).
    func ping() {
        send(SensorBatch(source: "iphone_bridge", session_id: "ping", samples: []))
    }
}

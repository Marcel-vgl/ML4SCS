import Foundation
import Combine
import Network

/// Sendet Sensor-Batches per HTTP POST an das Mac-Dashboard (`/api/ingest`).
/// Host und Port werden in den UserDefaults gespeichert. Findet das Dashboard
/// zusätzlich automatisch per Bonjour – funktioniert im WLAN und im iPhone-Hotspot.
final class MacHTTPClient: ObservableObject {
    /// Ein automatisch gefundenes Mac-Dashboard.
    struct DiscoveredMac: Identifiable, Equatable {
        let id: String      // Bonjour-Servicename
        let name: String
        let host: String
        let port: Int
    }

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

    @Published var discovered: [DiscoveredMac] = []
    @Published var discovering = false

    private let bonjourType = "_tennistracker._tcp"
    private var browser: NWBrowser?
    private var resolvers: [NWConnection] = []

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

    // MARK: - Automatische Suche (Bonjour)

    /// Startet die Suche nach Mac-Dashboards im lokalen Netz / Hotspot.
    func startDiscovery() {
        stopDiscovery()
        DispatchQueue.main.async {
            self.discovered = []
            self.discovering = true
        }
        let params = NWParameters.tcp
        params.includePeerToPeer = true
        let browser = NWBrowser(for: .bonjour(type: bonjourType, domain: nil), using: params)
        self.browser = browser
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            self?.resolvers.forEach { $0.cancel() }
            self?.resolvers = []
            for result in results { self?.resolve(result) }
        }
        browser.stateUpdateHandler = { [weak self] state in
            switch state {
            case .failed, .cancelled:
                DispatchQueue.main.async { self?.discovering = false }
            default:
                break
            }
        }
        browser.start(queue: .main)
    }

    /// Beendet die Suche (z. B. wenn die Mac-Option ausgeschaltet wird).
    func stopDiscovery() {
        browser?.cancel()
        browser = nil
        resolvers.forEach { $0.cancel() }
        resolvers = []
        DispatchQueue.main.async { self.discovering = false }
    }

    /// Übernimmt ein gefundenes Dashboard als aktuelles Ziel.
    func apply(_ mac: DiscoveredMac) {
        host = mac.host
        port = mac.port
    }

    private func resolve(_ result: NWBrowser.Result) {
        let serviceName: String
        if case let .service(name, _, _, _) = result.endpoint {
            serviceName = name
        } else {
            serviceName = "Mac"
        }
        // Kurz verbinden, um die echte IP+Port aufzulösen, dann sofort schließen.
        let connection = NWConnection(to: result.endpoint, using: .tcp)
        resolvers.append(connection)
        connection.stateUpdateHandler = { [weak self, weak connection] state in
            guard let self, let connection else { return }
            switch state {
            case .ready:
                if let endpoint = connection.currentPath?.remoteEndpoint,
                   case let .hostPort(host, port) = endpoint,
                   let ip = Self.ipv4String(host) {
                    let found = DiscoveredMac(id: serviceName, name: serviceName, host: ip, port: Int(port.rawValue))
                    DispatchQueue.main.async { self.addDiscovered(found) }
                }
                connection.cancel()
            case .failed, .cancelled:
                connection.cancel()
            default:
                break
            }
        }
        connection.start(queue: .global())
    }

    private func addDiscovered(_ mac: DiscoveredMac) {
        if let index = discovered.firstIndex(where: { $0.id == mac.id }) {
            discovered[index] = mac
        } else {
            discovered.append(mac)
        }
        // Genau ein Mac gefunden → automatisch übernehmen (kein Tippen nötig).
        if discovered.count == 1 {
            apply(mac)
        }
    }

    private static func ipv4String(_ host: NWEndpoint.Host) -> String? {
        switch host {
        case .ipv4(let address):
            return "\(address)"
        case .name(let name, _):
            return name
        default:
            return nil   // IPv6 hier ignorieren (HTTP-URL-Aufbau umständlich)
        }
    }
}

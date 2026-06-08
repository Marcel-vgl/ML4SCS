import Foundation

/// Schreibt jedes Sample direkt in eine lokale CSV-Datei auf der Uhr.
/// Das ist die verlustfreie Quelle der Wahrheit – unabhängig von Bluetooth/Stream.
/// Am Ende der Session wird die Datei per `transferFile` ans iPhone übertragen.
final class WatchLocalRecorder {
    private var handle: FileHandle?
    private(set) var fileURL: URL?

    static func recordingsDir() -> URL {
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("recordings", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    @discardableResult
    func start(session: String) -> URL? {
        let safe = session.replacingOccurrences(of: "/", with: "_")
        let url = WatchLocalRecorder.recordingsDir().appendingPathComponent("\(safe).csv")
        FileManager.default.createFile(atPath: url.path, contents: CanonicalCSV.header.data(using: .utf8))
        guard let h = try? FileHandle(forWritingTo: url) else { return nil }
        h.seekToEndOfFile()
        handle = h
        fileURL = url
        return url
    }

    func append(_ samples: [SensorSample]) {
        guard let handle, !samples.isEmpty else { return }
        if let data = CanonicalCSV.rows(samples).data(using: .utf8) {
            handle.write(data)
        }
    }

    /// Schließt die Datei und gibt ihre URL zurück (zum Übertragen ans iPhone).
    @discardableResult
    func close() -> URL? {
        try? handle?.synchronize()
        try? handle?.close()
        handle = nil
        return fileURL
    }
}

import Foundation
import Combine

/// Verwaltet die aufgezeichneten Dateien auf dem iPhone (CSV von der Uhr, später
/// auch Videos). Liegt im Dokumentenverzeichnis und ist über die „Dateien"-App
/// sichtbar (UIFileSharingEnabled).
final class RecordingStore: ObservableObject {
    @Published var recordings: [URL] = []
    @Published var lastSaved: String = ""

    static func dir() -> URL {
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("recordings", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    init() { refresh() }

    func refresh() {
        let dir = RecordingStore.dir()
        let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.contentModificationDateKey]))
            ?? []
        let sorted = files
            .filter { ["csv", "mov", "mp4"].contains($0.pathExtension.lowercased()) }
            .sorted { (a, b) in
                let da = (try? a.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                let db = (try? b.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return da > db
            }
        DispatchQueue.main.async { self.recordings = sorted }
    }

    /// Speichert eine von der Uhr empfangene Datei dauerhaft.
    @discardableResult
    func saveReceived(file url: URL, session: String?) -> URL? {
        let name: String
        if let session, !session.isEmpty {
            name = session.hasSuffix(".csv") ? session : "\(session).csv"
        } else {
            name = url.lastPathComponent
        }
        let dest = RecordingStore.dir().appendingPathComponent(name)
        try? FileManager.default.removeItem(at: dest)
        do {
            try FileManager.default.copyItem(at: url, to: dest)
        } catch {
            return nil
        }
        DispatchQueue.main.async {
            self.lastSaved = name
            self.refresh()
        }
        return dest
    }
}

import Foundation
import Combine

struct RecordingBundle: Identifiable {
    let id: String
    let baseName: String
    let csvURL: URL?
    let videoURL: URL?
    let metadataURL: URL?
    let date: Date
    let mode: AppMode

    var urls: [URL] {
        [csvURL, videoURL, metadataURL].compactMap { $0 }
    }

    var shareURLs: [URL] {
        urls
    }

    var hasVideo: Bool { videoURL != nil }
    var hasCSV: Bool { csvURL != nil }
}

private struct StoredVideoMetadata: Decodable {
    let video_start_unix_s: Double?
}

/// Verwaltet die aufgezeichneten Dateien auf dem iPhone (CSV von der Uhr, später
/// auch Videos). Liegt im Dokumentenverzeichnis und ist über die „Dateien"-App
/// sichtbar (UIFileSharingEnabled).
final class RecordingStore: ObservableObject {
    @Published var recordings: [URL] = []
    @Published var lastSaved: String = ""

    var csvRecordings: [URL] {
        recordings
            .filter { $0.pathExtension.lowercased() == "csv" }
            .sorted { Self.recordingDate(for: $0) > Self.recordingDate(for: $1) }
    }

    var recordingBundles: [RecordingBundle] {
        let grouped = Dictionary(grouping: recordings, by: Self.bundleKey(for:))
        return grouped.map { key, urls in
            let baseName = Self.bundleBaseName(for: urls[0])
            let csv = urls.first { $0.pathExtension.lowercased() == "csv" }
            let video = urls.first { ["mov", "mp4"].contains($0.pathExtension.lowercased()) }
            let metadata = urls.first { $0.lastPathComponent.hasSuffix("_video_metadata.json") }
            let date = csv.map(Self.recordingDate(for:))
                ?? video.flatMap(Self.filenameDate(for:))
                ?? video.flatMap(Self.fileModifiedDate(for:))
                ?? urls.compactMap(Self.fileModifiedDate(for:)).max()
                ?? .distantPast
            return RecordingBundle(
                id: key,
                baseName: baseName,
                csvURL: csv,
                videoURL: video,
                metadataURL: metadata,
                date: date,
                mode: Self.mode(for: urls)
            )
        }
        .filter { $0.hasCSV || $0.hasVideo }
        .sorted { $0.date > $1.date }
    }

    var labelRecordingBundles: [RecordingBundle] {
        recordingBundles.filter { $0.mode == .label }
    }

    var predictRecordingBundles: [RecordingBundle] {
        recordingBundles.filter { $0.mode == .predict }
    }

    private static let filenameStampFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = .current
        f.dateFormat = "yyyyMMdd_HHmmss"
        return f
    }()

    private static let csvISOFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func dir() -> URL {
        let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("recordings", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static func dir(for mode: AppMode) -> URL {
        switch mode {
        case .label:
            return dir()
        case .predict:
            let dir = dir().appendingPathComponent("predict", isDirectory: true)
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            return dir
        }
    }

    init() { refresh() }

    func refresh() {
        let dir = RecordingStore.dir()
        let files = Self.recordingFiles(in: dir)
        let sorted = files
            .filter { ["csv", "mov", "mp4", "json"].contains($0.pathExtension.lowercased()) }
            .sorted { (a, b) in
                let da = (try? a.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                let db = (try? b.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                return da > db
            }
        DispatchQueue.main.async { self.recordings = sorted }
    }

    private static func recordingFiles(in dir: URL) -> [URL] {
        guard let enumerator = FileManager.default.enumerator(
            at: dir,
            includingPropertiesForKeys: [.contentModificationDateKey, .isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return []
        }
        return enumerator.compactMap { item in
            guard let url = item as? URL else { return nil }
            let values = try? url.resourceValues(forKeys: [.isDirectoryKey])
            return values?.isDirectory == true ? nil : url
        }
    }

    static func recordingDate(for url: URL) -> Date {
        filenameDate(for: url)
            ?? csvStartDate(for: url)
            ?? fileModifiedDate(for: url)
            ?? .distantPast
    }

    static func filenameDate(for url: URL) -> Date? {
        filenameDate(in: url.deletingPathExtension().lastPathComponent)
    }

    static func filenameDate(in name: String) -> Date? {
        let parts = name.split(separator: "_")
        guard parts.count >= 2 else { return nil }
        let stamp = "\(parts[parts.count - 2])_\(parts[parts.count - 1])"
        return filenameStampFormatter.date(from: stamp)
    }

    static func csvStartDate(for url: URL) -> Date? {
        guard url.pathExtension.lowercased() == "csv",
              let handle = try? FileHandle(forReadingFrom: url)
        else { return nil }
        defer { try? handle.close() }

        let data = handle.readData(ofLength: 8192)
        guard let text = String(data: data, encoding: .utf8) else { return nil }
        let lines = text.split(whereSeparator: \.isNewline)
        guard lines.count >= 2,
              let firstField = lines[1].split(separator: ",", maxSplits: 1).first
        else { return nil }
        return csvISOFormatter.date(from: String(firstField))
    }

    static func fileModifiedDate(for url: URL) -> Date? {
        guard let values = try? url.resourceValues(forKeys: [.contentModificationDateKey]) else { return nil }
        return values.contentModificationDate
    }

    static func fileSize(for url: URL) -> Int {
        (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
    }

    static func videoStartDate(for metadataURL: URL) -> Date? {
        guard let data = try? Data(contentsOf: metadataURL),
              let metadata = try? JSONDecoder().decode(StoredVideoMetadata.self, from: data),
              let start = metadata.video_start_unix_s
        else { return nil }
        return Date(timeIntervalSince1970: start)
    }

    func deleteCSVRecordings(at offsets: IndexSet) {
        let urls = csvRecordings
        let selected = offsets.compactMap { urls.indices.contains($0) ? urls[$0] : nil }
        delete(selected)
    }

    func deleteRecordingBundles(at offsets: IndexSet) {
        let bundles = recordingBundles
        deleteRecordingBundles(offsets, in: bundles)
    }

    func deleteRecordingBundles(_ offsets: IndexSet, in bundles: [RecordingBundle]) {
        let urls = offsets
            .compactMap { bundles.indices.contains($0) ? bundles[$0] : nil }
            .flatMap(\.urls)
        delete(urls)
    }

    func delete(_ urls: [URL]) {
        for url in urls {
            try? FileManager.default.removeItem(at: url)
        }
        refresh()
    }

    static func bundleBaseName(for url: URL) -> String {
        let name = url.deletingPathExtension().lastPathComponent
        if name.hasSuffix("_video_metadata") {
            return String(name.dropLast("_video_metadata".count))
        }
        return name
    }

    static func bundleKey(for url: URL) -> String {
        "\(mode(for: [url]).rawValue)/\(bundleBaseName(for: url))"
    }

    static func mode(for urls: [URL]) -> AppMode {
        urls.contains { $0.deletingLastPathComponent().lastPathComponent == "predict" } ? .predict : .label
    }

    /// Speichert eine von der Uhr empfangene Datei dauerhaft.
    @discardableResult
    func saveReceived(file url: URL, session: String?, mode: AppMode = .label) -> URL? {
        let name: String
        if let session, !session.isEmpty {
            name = session.hasSuffix(".csv") ? session : "\(session).csv"
        } else {
            name = url.lastPathComponent
        }
        let dest = RecordingStore.dir(for: mode).appendingPathComponent(name)
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

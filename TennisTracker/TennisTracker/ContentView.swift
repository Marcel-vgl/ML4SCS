import AVKit
import SwiftUI

struct ContentView: View {
    @StateObject private var mac: MacHTTPClient
    @StateObject private var store: RecordingStore
    @StateObject private var video: LabelVideoRecorder
    @StateObject private var predictor: StrokePredictor
    @StateObject private var bridge: PhoneWatchBridge
    @State private var sessionNameInput = ""
    @State private var portText = ""

    init() {
        let mac = MacHTTPClient()
        let store = RecordingStore()
        let video = LabelVideoRecorder()
        let predictor = StrokePredictor()
        _mac = StateObject(wrappedValue: mac)
        _store = StateObject(wrappedValue: store)
        _video = StateObject(wrappedValue: video)
        _predictor = StateObject(wrappedValue: predictor)
        _bridge = StateObject(wrappedValue: PhoneWatchBridge(mac: mac, store: store, video: video, predictor: predictor))
    }

    private static let stampFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd_HHmmss"
        return f
    }()

    private var sessionId: String {
        let base = sessionNameInput.trimmingCharacters(in: .whitespaces)
        let name = base.isEmpty ? "session" : base.replacingOccurrences(of: " ", with: "-")
        return "\(name)_\(Self.stampFormatter.string(from: Date()))"
    }

    var body: some View {
        NavigationStack {
            GeometryReader { proxy in
                let isLandscape = proxy.size.width > proxy.size.height
                let useSplitLayout = isLandscape && bridge.mode == .label
                
                let layout = useSplitLayout
                    ? AnyLayout(HStackLayout(spacing: 0))
                    : AnyLayout(VStackLayout(spacing: 0))
                
                layout {
                    if bridge.mode == .label {
                        cameraPreviewContainer(isLandscape: isLandscape)
                            .frame(
                                width: isLandscape ? proxy.size.width * 0.64 : proxy.size.width,
                                height: isLandscape ? proxy.size.height : min(max(proxy.size.height * 0.45, 320), 400)
                            )
                            .id("tennistracker.camera.preview")
                        
                        if isLandscape {
                            Divider()
                        }
                    }
                    
                    mainForm()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .navigationTitle("TennisTracker")
            .toolbar(.hidden, for: .navigationBar)
        }
        .onAppear {
            portText = String(mac.port)
            if bridge.mode == .label {
                video.prepare()
            }
        }
        .onChange(of: bridge.mode) { _, newMode in
            if newMode == .label {
                video.prepare()
            }
        }
    }

    private func cameraPreviewContainer(isLandscape: Bool) -> some View {
        VStack(spacing: 0) {
            cameraPreview(isLandscape: isLandscape)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            HStack {
                Label(video.statusText, systemImage: bridge.isRunning ? "record.circle.fill" : "video")
                    .foregroundStyle(bridge.isRunning ? .red : .primary)
                Spacer()
                Text(video.selectedCamera.title)
                    .foregroundStyle(.secondary)
                Text(video.selectedQuality.title)
                    .foregroundStyle(.secondary)
            }
            .font(.footnote)
            .padding(.horizontal, 14)
            .padding(.vertical, isLandscape ? 10 : 6)
            .background(.bar)
        }
        .background(Color.black)
    }

    private func cameraPreview(isLandscape: Bool) -> some View {
        LabelCameraPreview(session: video.captureSession, rotationAngle: video.videoRotationAngle)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.black)
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private func mainForm() -> some View {
        Form {
            Section("Modus") {
                Picker("Modus", selection: $bridge.mode) {
                    Text("Label (aufzeichnen)").tag(AppMode.label)
                    Text("Predict (live an Mac)").tag(AppMode.predict)
                }
                .pickerStyle(.segmented)
                .disabled(bridge.isRunning)
            }

            Section("Status") {
                statusRow("Watch", ok: bridge.watchReachable,
                          text: bridge.watchReachable ? "live erreichbar" : "Hintergrund")
                LabeledContent("Empfangen", value: "\(bridge.receivedSamples) Samples")
                LabeledContent("Rate", value: "\(Int(bridge.lastSampleRate.rounded())) Hz")
                LabeledContent("Transport", value: bridge.lastTransport)
            }

            Section(bridge.mode == .label ? "Aufnahme" : "Live-Vorhersage") {
                if bridge.mode == .label {
                    TextField("Session-Name (z. B. fritz_vorhand)", text: $sessionNameInput)
                        .autocorrectionDisabled()
                        .disabled(bridge.isRunning)
                    Picker("Kamera", selection: $video.selectedCamera) {
                        ForEach(video.availableCameras) { camera in
                            Text(camera.title).tag(camera)
                        }
                    }
                    .disabled(bridge.isRunning)
                    Picker("Qualitaet", selection: $video.selectedQuality) {
                        ForEach(LabelVideoQuality.allCases) { quality in
                            Text(quality.title).tag(quality)
                        }
                    }
                    .disabled(bridge.isRunning)
                    LabeledContent("Video", value: video.statusText)
                    if let error = video.lastError {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }
                if bridge.isRunning {
                    Button(role: .destructive) { bridge.stop() } label: {
                        Label("Stop", systemImage: "stop.circle.fill")
                    }
                } else {
                    Button { bridge.start(session: sessionId) } label: {
                        Label(bridge.mode == .label ? "Aufnahme starten" : "Vorhersage starten",
                               systemImage: "record.circle")
                    }
                }
                Text(bridge.mode == .label
                     ? "Die Uhr startet eine Workout-Session fuer den Hintergrundbetrieb und nimmt 100 Hz verlustfrei auf. Das iPhone speichert parallel ein Video und eine Sync-JSON."
                     : "Die Uhr streamt Live-Daten ans iPhone, das Vorhand/Rückhand direkt on-device erkennt – kein Mac nötig.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }

            if bridge.mode == .predict {
                Section("Live-Erkennung (on-device)") {
                    PredictDashboardView(predictor: predictor)
                        .listRowInsets(EdgeInsets(top: 10, leading: 14, bottom: 12, trailing: 14))
                    LabeledContent("Schläge erkannt", value: "\(predictor.totalStrokes)")
                }

                Section {
                    Toggle("Auch ans Mac-Dashboard senden", isOn: $bridge.alsoSendToMac)
                } footer: {
                    Text("Optional: zusätzlich die Rohdaten ans Mac senden (Vergleich/Backup). Die Schlagerkennung läuft unabhängig davon direkt auf dem iPhone.")
                }

                if bridge.alsoSendToMac {
                    Section("Mac-Dashboard (WLAN)") {
                        HStack {
                            Text("IP")
                            Spacer()
                            TextField("192.168.0.105", text: $mac.host)
                                .multilineTextAlignment(.trailing)
                                .keyboardType(.numbersAndPunctuation)
                                .autocorrectionDisabled()
                        }
                        HStack {
                            Text("Port")
                            Spacer()
                            TextField("8788", text: $portText)
                                .multilineTextAlignment(.trailing)
                                .keyboardType(.numberPad)
                                .onChange(of: portText) { _, new in
                                    if let v = Int(new) { mac.port = v }
                                }
                        }
                        LabeledContent("Mac", value: mac.reachable ? "verbunden" : "getrennt")
                        LabeledContent("Gesendet", value: "\(mac.sentBatches) ok · \(mac.failedBatches) Fehler")
                        if !mac.lastError.isEmpty {
                            Text(mac.lastError)
                                .font(.footnote)
                                .foregroundStyle(.red)
                        }
                        Button("Verbindung testen") { mac.ping() }
                    }
                }
            }

            Section("Aufnahmen") {
                NavigationLink {
                    RecordingsView(store: store)
                } label: {
                    LabeledContent(
                        "Sessions",
                        value: "\(store.labelRecordingBundles.count) Label · \(store.predictRecordingBundles.count) Predict"
                    )
                }
                Button("Aktualisieren") { store.refresh() }
            }
        }
    }

    @ViewBuilder
    private func statusRow(_ label: String, ok: Bool, text: String) -> some View {
        HStack {
            Circle().fill(ok ? Color.green : Color.gray).frame(width: 10, height: 10)
            Text(label)
            Spacer()
            Text(text).foregroundStyle(.secondary)
        }
    }
}

#Preview {
    ContentView()
}

struct RecordingsView: View {
    @ObservedObject var store: RecordingStore
    @State private var showLabelRecordings = true
    @State private var showPredictRecordings = false

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .medium
        return f
    }()

    var body: some View {
        List {
            if store.recordingBundles.isEmpty {
                Text("Noch keine Aufnahmen.")
                    .foregroundStyle(.secondary)
            } else {
                DisclosureGroup(
                    "Label-Aufnahmen (\(store.labelRecordingBundles.count))",
                    isExpanded: $showLabelRecordings
                ) {
                    if store.labelRecordingBundles.isEmpty {
                        Text("Noch keine Label-Aufnahmen.")
                            .foregroundStyle(.secondary)
                    } else {
                        recordingRows(store.labelRecordingBundles)
                    }
                }

                DisclosureGroup(
                    "Predict-Sessions (\(store.predictRecordingBundles.count))",
                    isExpanded: $showPredictRecordings
                ) {
                    if store.predictRecordingBundles.isEmpty {
                        Text("Noch keine Predict-Sessions.")
                            .foregroundStyle(.secondary)
                    } else {
                        recordingRows(store.predictRecordingBundles)
                    }
                }
            }
        }
        .navigationTitle("Aufnahmen")
        .toolbar {
            Button("Aktualisieren") { store.refresh() }
            if !store.recordingBundles.isEmpty {
                EditButton()
            }
        }
        .onAppear { store.refresh() }
    }

    @ViewBuilder
    private func recordingRows(_ bundles: [RecordingBundle]) -> some View {
        ForEach(bundles) { bundle in
            NavigationLink {
                RecordingDetailView(bundle: bundle)
            } label: {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(bundle.baseName)
                            .font(.subheadline)
                        Text(detailText(for: bundle))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        HStack(spacing: 8) {
                            fileBadge("CSV", available: bundle.hasCSV)
                            fileBadge("Video", available: bundle.hasVideo)
                            if bundle.metadataURL != nil {
                                fileBadge("Sync", available: true)
                            }
                        }
                    }
                    Spacer()
                    ShareLink(items: bundle.shareURLs) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .disabled(bundle.shareURLs.isEmpty)
                }
            }
        }
        .onDelete { offsets in
            store.deleteRecordingBundles(offsets, in: bundles)
        }
    }

    @ViewBuilder
    private func fileBadge(_ text: String, available: Bool) -> some View {
        Text(text)
            .font(.caption2)
            .foregroundStyle(available ? .primary : .secondary)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(available ? Color.green.opacity(0.18) : Color.gray.opacity(0.14))
            .clipShape(Capsule())
    }

    private func detailText(for bundle: RecordingBundle) -> String {
        let size = bundle.urls.reduce(0) { $0 + RecordingStore.fileSize(for: $1) }
        var parts = ["Aufnahme: \(Self.dateFormatter.string(from: bundle.date))"]
        if let csvURL = bundle.csvURL,
           let csvDate = RecordingStore.csvStartDate(for: csvURL),
           abs(csvDate.timeIntervalSince(bundle.date)) > 60 {
            parts.append("CSV-Start: \(Self.dateFormatter.string(from: csvDate))")
        }
        parts.append(formatBytes(size))
        return parts.joined(separator: " · ")
    }

    private func formatBytes(_ bytes: Int) -> String {
        ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
    }
}

struct RecordingDetailView: View {
    let bundle: RecordingBundle

    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .medium
        return f
    }()

    var body: some View {
        List {
            if let videoURL = bundle.videoURL {
                Section("Video") {
                    VideoPlayer(player: AVPlayer(url: videoURL))
                        .frame(height: 260)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    Text(videoURL.lastPathComponent)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            } else {
                Section("Video") {
                    Text("Kein Video fuer diese Aufnahme gefunden.")
                        .foregroundStyle(.secondary)
                }
            }

            Section("Dateien") {
                if let csvURL = bundle.csvURL {
                    fileRow("CSV", url: csvURL)
                }
                if let videoURL = bundle.videoURL {
                    fileRow("Video", url: videoURL)
                }
                if let metadataURL = bundle.metadataURL {
                    fileRow("Sync", url: metadataURL)
                }
            }

            Section("Zeit") {
                LabeledContent("Aufnahme", value: Self.dateFormatter.string(from: bundle.date))
                if let csvURL = bundle.csvURL,
                   let csvDate = RecordingStore.csvStartDate(for: csvURL) {
                    LabeledContent("CSV-Start", value: Self.dateFormatter.string(from: csvDate))
                    if let metadataURL = bundle.metadataURL,
                       let videoStart = RecordingStore.videoStartDate(for: metadataURL) {
                        LabeledContent("Video-Start", value: Self.dateFormatter.string(from: videoStart))
                        LabeledContent("CSV zu Video", value: offsetText(csvDate.timeIntervalSince(videoStart)))
                    }
                    LabeledContent("CSV zu Name", value: offsetText(csvDate.timeIntervalSince(bundle.date)))
                }
            }
        }
        .navigationTitle(bundle.baseName)
        .toolbar {
            ShareLink(items: bundle.shareURLs) {
                Image(systemName: "square.and.arrow.up")
            }
            .disabled(bundle.shareURLs.isEmpty)
        }
    }

    @ViewBuilder
    private func fileRow(_ label: String, url: URL) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text(label)
                Text(url.lastPathComponent)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text(ByteCountFormatter.string(fromByteCount: Int64(RecordingStore.fileSize(for: url)), countStyle: .file))
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    private func offsetText(_ seconds: TimeInterval) -> String {
        String(format: "%+.3f s", seconds)
    }
}

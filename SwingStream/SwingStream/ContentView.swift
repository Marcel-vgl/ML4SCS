import SwiftUI

struct ContentView: View {
    @StateObject private var mac: MacHTTPClient
    @StateObject private var store: RecordingStore
    @StateObject private var bridge: PhoneWatchBridge
    @State private var sessionNameInput = ""
    @State private var portText = ""

    init() {
        let mac = MacHTTPClient()
        let store = RecordingStore()
        _mac = StateObject(wrappedValue: mac)
        _store = StateObject(wrappedValue: store)
        _bridge = StateObject(wrappedValue: PhoneWatchBridge(mac: mac, store: store))
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
                              text: bridge.watchReachable ? "verbunden" : "Bluetooth/Hintergrund")
                    LabeledContent("Empfangen", value: "\(bridge.receivedSamples) Samples")
                    LabeledContent("Rate", value: "\(Int(bridge.lastSampleRate.rounded())) Hz")
                }

                Section(bridge.mode == .label ? "Aufnahme" : "Live-Vorhersage") {
                    if bridge.mode == .label {
                        TextField("Session-Name (z. B. fritz_vorhand)", text: $sessionNameInput)
                            .autocorrectionDisabled()
                            .disabled(bridge.isRunning)
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
                         ? "Die Uhr nimmt 100 Hz verlustfrei auf und überträgt die CSV am Ende ans iPhone. Watch-App geöffnet lassen."
                         : "Die Live-Daten werden ans Mac-Dashboard gesendet, das die Schläge erkennt.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if bridge.mode == .predict {
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
                        Button("Verbindung testen") { mac.ping() }
                    }
                }

                Section("Aufnahmen") {
                    if store.recordings.isEmpty {
                        Text("Noch keine Aufnahmen.").foregroundStyle(.secondary)
                    } else {
                        ForEach(store.recordings, id: \.self) { url in
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(url.lastPathComponent).font(.subheadline)
                                }
                                Spacer()
                                ShareLink(item: url) {
                                    Image(systemName: "square.and.arrow.up")
                                }
                            }
                        }
                    }
                    Button("Aktualisieren") { store.refresh() }
                }
            }
            .navigationTitle("SwingStream")
        }
        .onAppear { portText = String(mac.port) }
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

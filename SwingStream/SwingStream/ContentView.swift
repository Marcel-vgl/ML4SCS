import SwiftUI

struct ContentView: View {
    @StateObject private var mac: MacHTTPClient
    @StateObject private var bridge: PhoneWatchBridge
    @State private var portText = ""

    init() {
        let mac = MacHTTPClient()
        _mac = StateObject(wrappedValue: mac)
        _bridge = StateObject(wrappedValue: PhoneWatchBridge(mac: mac))
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Mac-Dashboard") {
                    HStack {
                        Text("IP")
                        Spacer()
                        TextField("192.168.1.50", text: $mac.host)
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
                                if let value = Int(new) { mac.port = value }
                            }
                    }
                    Button("Verbindung testen") { mac.ping() }
                }

                Section("Status") {
                    statusRow("Watch", ok: bridge.watchReachable,
                              text: bridge.watchReachable ? "erreichbar" : "getrennt")
                    statusRow("Mac", ok: mac.reachable,
                              text: mac.reachable ? "verbunden" : "getrennt")
                    LabeledContent("Empfangen", value: "\(bridge.receivedSamples) Samples")
                    LabeledContent("Rate", value: "\(Int(bridge.lastSampleRate.rounded())) Hz")
                    LabeledContent("An Mac gesendet", value: "\(mac.sentBatches) Batches")
                    if mac.failedBatches > 0 {
                        LabeledContent("Fehlgeschlagen", value: "\(mac.failedBatches)")
                            .foregroundStyle(.orange)
                    }
                    if !mac.lastError.isEmpty {
                        Text(mac.lastError)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }

                Section {
                    Text("Stream auf der Apple Watch mit der Start-Taste beginnen. Das iPhone leitet die Daten automatisch an das Mac-Dashboard weiter.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("SwingStream Bridge")
        }
        .onAppear { portText = String(mac.port) }
    }

    @ViewBuilder
    private func statusRow(_ label: String, ok: Bool, text: String) -> some View {
        HStack {
            Circle()
                .fill(ok ? Color.green : Color.gray)
                .frame(width: 10, height: 10)
            Text(label)
            Spacer()
            Text(text).foregroundStyle(.secondary)
        }
    }
}

#Preview {
    ContentView()
}

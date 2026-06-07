import SwiftUI

struct WatchContentView: View {
    @StateObject private var sampler = WatchMotionSampler()
    @StateObject private var sender = WatchConnectivitySender.shared

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                Text("SwingStream")
                    .font(.headline)

                statusRow("iPhone", ok: sender.phoneReachable,
                          text: sender.phoneReachable ? "erreichbar" : "getrennt")
                statusRow("Stream", ok: sampler.isRunning,
                          text: sampler.isRunning ? "läuft" : "gestoppt")

                VStack(spacing: 2) {
                    Text("\(Int(sampler.rateHz.rounded())) Hz")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("\(sampler.sampleCount) Samples · \(sender.sentBatches) Batches")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    if sender.droppedBatches > 0 {
                        Text("\(sender.droppedBatches) verworfen")
                            .font(.caption2)
                            .foregroundStyle(.orange)
                    }
                }
                .padding(.vertical, 4)

                Button(action: toggle) {
                    Text(sampler.isRunning ? "Stop" : "Start")
                        .frame(maxWidth: .infinity)
                        .fontWeight(.semibold)
                }
                .tint(sampler.isRunning ? .red : .green)
            }
            .padding(.horizontal, 6)
        }
        .onAppear {
            // Batches der Watch direkt ans iPhone weiterreichen.
            sampler.onBatch = { batch in
                WatchConnectivitySender.shared.send(batch)
            }
        }
    }

    private func toggle() {
        if sampler.isRunning {
            sampler.stop()
        } else {
            sampler.start()
        }
    }

    @ViewBuilder
    private func statusRow(_ label: String, ok: Bool, text: String) -> some View {
        HStack {
            Circle()
                .fill(ok ? Color.green : Color.gray)
                .frame(width: 8, height: 8)
            Text(label).font(.caption)
            Spacer()
            Text(text).font(.caption).foregroundStyle(.secondary)
        }
    }
}

#Preview {
    WatchContentView()
}

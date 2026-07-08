import SwiftUI

struct WatchContentView: View {
    @StateObject private var controller = WatchSessionController()

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                Text("TennisTracker")
                    .font(.headline)

                statusRow("iPhone", ok: controller.link.phoneReachable,
                          text: controller.link.phoneReachable ? "verbunden" : "Bluetooth")
                statusRow("Aufnahme", ok: controller.isRunning,
                          text: controller.isRunning ? "läuft" : "gestoppt")
                statusRow("Hintergrund", ok: controller.workout.active,
                          text: controller.workout.active ? "aktiv" : "aus")
                statusRow("Workout", ok: controller.workout.authorized,
                          text: controller.workout.authorized ? "bereit" : "Berechtigung")
                statusRow("Live", ok: controller.link.sentBatches > 0,
                          text: "\(controller.link.sentBatches) direkt")
                statusRow("Queue", ok: controller.link.queuedBatches == 0,
                          text: "\(controller.link.queuedBatches) Hintergrund")

                VStack(spacing: 2) {
                    Text("\(Int(controller.sampler.rateHz.rounded())) Hz")
                        .font(.system(size: 26, weight: .bold, design: .rounded))
                    Text("\(controller.sampler.sampleCount) Samples")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    if !controller.sessionName.isEmpty {
                        Text(controller.sessionName)
                            .font(.system(size: 10))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                }
                .padding(.vertical, 4)

                Button(action: controller.toggleManual) {
                    Text(controller.isRunning ? "Stop" : "Start")
                        .frame(maxWidth: .infinity)
                        .fontWeight(.semibold)
                }
                .tint(controller.isRunning ? .red : .green)

                Text("Tipp: Auf dem iPhone Modus + Session-Name wählen und dort starten – die Uhr startet dann mit.")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                if !controller.workout.lastError.isEmpty {
                    Text(controller.workout.lastError)
                        .font(.system(size: 10))
                        .foregroundStyle(.red)
                }
                if controller.link.failedBatches > 0 {
                    Text("\(controller.link.failedBatches) Live-Fehler")
                        .font(.system(size: 10))
                        .foregroundStyle(.red)
                }
            }
            .padding(.horizontal, 6)
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

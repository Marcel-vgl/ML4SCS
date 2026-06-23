import SwiftUI
import Charts

/// On-device Live-Dashboard für den Predict-Modus – ersetzt das Mac-Dashboard.
/// Zeigt die Energiekurven (|a|, |ω|), die erkannten Schläge als Marker, den
/// letzten Schlag groß und die Schlag-Historie als Chips.
struct PredictDashboardView: View {
    @ObservedObject var predictor: StrokePredictor

    private static func color(for label: String) -> Color {
        label == "Vorhand" ? .green : .blue
    }
    private static func short(_ label: String) -> String {
        label == "Vorhand" ? "VH" : "RH"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if !predictor.modelLoaded {
                Label("Modell nicht geladen (StrokeForest.json fehlt im Bundle).",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote)
                    .foregroundStyle(.red)
            }

            lastStrokeCard
            chart
            legend
            if !predictor.predictions.isEmpty {
                historyChips
            }
        }
    }

    // MARK: - Letzter Schlag

    private var lastStrokeCard: some View {
        HStack {
            if let last = predictor.lastPrediction {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Letzter Schlag").font(.caption).foregroundStyle(.secondary)
                    Text(last.label)
                        .font(.title2).fontWeight(.bold)
                        .foregroundStyle(Self.color(for: last.label))
                }
                Spacer()
                Text("\(Int((last.confidence * 100).rounded())) %")
                    .font(.title3).fontWeight(.semibold)
                    .foregroundStyle(.secondary)
            } else {
                Text(predictor.isActive ? "Warte auf Schläge…" : "Predict-Modus bereit")
                    .font(.headline)
                    .foregroundStyle(.secondary)
                Spacer()
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill((predictor.lastPrediction.map { Self.color(for: $0.label) } ?? .gray)
                    .opacity(0.12))
        )
    }

    // MARK: - Live-Chart

    private var chart: some View {
        let points = predictor.chartPoints
        let maxAcc = max(0.2, points.map(\.acc).max() ?? 0.2)
        let maxGyro = max(0.5, points.map(\.gyro).max() ?? 0.5)
        let tMin = points.first?.t ?? 0
        let tMax = points.last?.t ?? 1

        return Chart {
            ForEach(points) { p in
                LineMark(x: .value("t", p.t), y: .value("v", p.acc / maxAcc),
                         series: .value("s", "acc"))
                    .foregroundStyle(.blue)
            }
            ForEach(points) { p in
                LineMark(x: .value("t", p.t), y: .value("v", p.gyro / maxGyro),
                         series: .value("s", "gyro"))
                    .foregroundStyle(.orange)
            }
            ForEach(predictor.predictions.filter { $0.time >= tMin && $0.time <= tMax }) { pr in
                RuleMark(x: .value("t", pr.time))
                    .foregroundStyle(Self.color(for: pr.label).opacity(0.7))
                    .lineStyle(StrokeStyle(lineWidth: 1.5))
                    .annotation(position: .top, alignment: .center) {
                        Text(Self.short(pr.label))
                            .font(.caption2).fontWeight(.bold)
                            .foregroundStyle(Self.color(for: pr.label))
                    }
            }
        }
        .chartYScale(domain: 0...1.05)
        .chartYAxis(.hidden)
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 4)) { value in
                AxisValueLabel {
                    if let t = value.as(Double.self) {
                        Text("\(Int(t)) s").font(.caption2)
                    }
                }
            }
        }
        .frame(height: 200)
        .padding(8)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(.secondarySystemBackground)))
    }

    private var legend: some View {
        HStack(spacing: 16) {
            legendItem(color: .blue, text: "|a| Beschleunigung")
            legendItem(color: .orange, text: "|ω| Rotation")
        }
        .font(.caption2)
        .foregroundStyle(.secondary)
    }

    private func legendItem(color: Color, text: String) -> some View {
        HStack(spacing: 4) {
            RoundedRectangle(cornerRadius: 1).fill(color).frame(width: 12, height: 3)
            Text(text)
        }
    }

    // MARK: - Historie

    private var historyChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(predictor.predictions) { p in
                    HStack(spacing: 4) {
                        Text(p.label)
                            .fontWeight(.semibold)
                            .foregroundStyle(Self.color(for: p.label))
                        Text("\(Int((p.confidence * 100).rounded()))%")
                            .foregroundStyle(.secondary)
                    }
                    .font(.caption)
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .background(Capsule().fill(Color(.tertiarySystemBackground)))
                }
            }
            .padding(.vertical, 2)
        }
    }
}

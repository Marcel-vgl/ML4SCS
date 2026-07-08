import Foundation

/// Roh-Sample mit genau den Feldern, die das Schlagmodell braucht. Wird sowohl
/// aus den Live-`SensorSample`s der Uhr als auch (im Test) aus CSV-Zeilen gebaut.
struct IMUSample {
    var time: Double            // Zeitachse in Sekunden (relativ egal, nur Differenzen zählen)
    var accX, accY, accZ: Double            // accelerometerAcceleration (roh)
    var userAccX, userAccY, userAccZ: Double
    var gyroX, gyroY, gyroZ: Double
    var roll, pitch, yaw: Double
}

/// Zeit-aufgelöste Sensortabelle inkl. abgeleiteter Energie-Spuren. Direkter
/// Nachbau von `SensorTable` aus `src/stroke_model.py`.
struct SensorTable {
    struct PeakRow { var t: Double; var acc: Double; var gyro: Double; var score: Double }

    let times: [Double]
    let values: [String: [Double]]
    let peakRows: [PeakRow]

    // Signalnamen exakt wie im trainierten Modell (sortiert).
    static let signalKeys = [
        "accelerometerAccelerationX(G)", "accelerometerAccelerationY(G)", "accelerometerAccelerationZ(G)",
        "motionPitch(rad)", "motionRoll(rad)",
        "motionRotationRateX(rad/s)", "motionRotationRateY(rad/s)", "motionRotationRateZ(rad/s)",
        "motionUserAccelerationX(G)", "motionUserAccelerationY(G)", "motionUserAccelerationZ(G)",
        "motionYaw(rad)", "rotation_magnitude", "score", "user_acc_magnitude",
    ]

    init(samples: [IMUSample]) {
        var times = [Double]()
        var v: [String: [Double]] = [:]
        for key in Self.signalKeys { v[key] = [] }
        var peaks = [PeakRow]()
        times.reserveCapacity(samples.count)
        peaks.reserveCapacity(samples.count)

        for s in samples {
            let uam = (s.userAccX * s.userAccX + s.userAccY * s.userAccY + s.userAccZ * s.userAccZ).squareRoot()
            let rm = (s.gyroX * s.gyroX + s.gyroY * s.gyroY + s.gyroZ * s.gyroZ).squareRoot()
            let score = uam + 0.12 * rm
            times.append(s.time)
            v["accelerometerAccelerationX(G)"]!.append(s.accX)
            v["accelerometerAccelerationY(G)"]!.append(s.accY)
            v["accelerometerAccelerationZ(G)"]!.append(s.accZ)
            v["motionPitch(rad)"]!.append(s.pitch)
            v["motionRoll(rad)"]!.append(s.roll)
            v["motionRotationRateX(rad/s)"]!.append(s.gyroX)
            v["motionRotationRateY(rad/s)"]!.append(s.gyroY)
            v["motionRotationRateZ(rad/s)"]!.append(s.gyroZ)
            v["motionUserAccelerationX(G)"]!.append(s.userAccX)
            v["motionUserAccelerationY(G)"]!.append(s.userAccY)
            v["motionUserAccelerationZ(G)"]!.append(s.userAccZ)
            v["motionYaw(rad)"]!.append(s.yaw)
            v["rotation_magnitude"]!.append(rm)
            v["score"]!.append(score)
            v["user_acc_magnitude"]!.append(uam)
            peaks.append(PeakRow(t: s.time, acc: uam, gyro: rm, score: score))
        }
        self.times = times
        self.values = v
        self.peakRows = peaks
    }
}

/// Schlag-Kandidatenerkennung und Feature-Extraktion – Portierung der
/// gleichnamigen Funktionen aus `src/stroke_model.py` (contrast-Modus).
enum StrokeDetection {

    // MARK: - Energie-Peaks

    private static func downsample(_ rows: [SensorTable.PeakRow], target: Int = 16000) -> [SensorTable.PeakRow] {
        if rows.count <= target { return rows }
        let bucket = Int((Double(rows.count) / Double(target)).rounded(.up))
        var out = [SensorTable.PeakRow]()
        var start = 0
        while start < rows.count {
            let end = min(start + bucket, rows.count)
            var best = rows[start]
            for i in (start + 1)..<end where rows[i].score > best.score { best = rows[i] }
            out.append(best)
            start += bucket
        }
        return out
    }

    private static func smooth(_ rows: [SensorTable.PeakRow], window: Int = 7) -> [SensorTable.PeakRow] {
        if window < 2 || rows.count < window { return rows }
        let half = window / 2
        var out = [SensorTable.PeakRow]()
        out.reserveCapacity(rows.count)
        for i in 0..<rows.count {
            let lo = max(0, i - half)
            let hi = min(rows.count, i + half + 1)
            let n = Double(hi - lo)
            var a = 0.0, g = 0.0, s = 0.0
            for j in lo..<hi { a += rows[j].acc; g += rows[j].gyro; s += rows[j].score }
            out.append(SensorTable.PeakRow(t: rows[i].t, acc: a / n, gyro: g / n, score: s / n))
        }
        return out
    }

    private static func averageWindow(_ rows: [SensorTable.PeakRow], _ index: Int,
                                      _ key: (SensorTable.PeakRow) -> Double, _ radius: Int) -> Double {
        let start = max(0, index - radius)
        let end = min(rows.count - 1, index + radius)
        guard end >= start else { return 0.0 }
        var sum = 0.0
        for i in start...end { sum += key(rows[i]) }
        return sum / Double(end - start + 1)
    }

    private static func robustMax(_ values: [Double], fallback: Double = 1.0) -> Double {
        let positives = values.filter { $0 > 0 }.sorted()
        if positives.isEmpty { return fallback }
        let index = min(positives.count - 1, Int(Double(positives.count) * 0.98))
        return max(positives[index], fallback)
    }

    struct Peak { var time: Double; var score: Double }

    /// `detect_energy_peaks` (contrast-Modus) aus stroke_model.py.
    static func detectEnergyPeaks(_ table: SensorTable, limit: Int = 220, minSpacingS: Double = 0.45) -> [Peak] {
        let clusterGapS = 0.18
        let rows = smooth(downsample(table.peakRows))
        guard !rows.isEmpty else { return [] }

        struct S { var t: Double; var energy: Double }
        var series = [S]()
        series.reserveCapacity(rows.count)
        for i in 0..<rows.count {
            let acc = rows[i].acc
            let gyro = rows[i].gyro
            let accBase = averageWindow(rows, i, { $0.acc }, 18)
            let gyroBase = averageWindow(rows, i, { $0.gyro }, 18)
            let accValue = max(0.0, acc - accBase)
            let gyroValue = max(0.0, gyro - gyroBase)
            series.append(S(t: rows[i].t, energy: accValue + 0.16 * gyroValue))
        }

        let maxEnergy = robustMax(series.map { $0.energy }, fallback: 1.0)
        let activeThreshold = 0.48
        var clusters = [Peak]()
        var lastActive: Double? = nil
        for p in series {
            let value = min(p.energy / maxEnergy, 1.0)
            if value < activeThreshold { continue }
            if !clusters.isEmpty, let la = lastActive, (p.t - la) <= clusterGapS {
                if value > clusters[clusters.count - 1].score {
                    clusters[clusters.count - 1].score = value
                    clusters[clusters.count - 1].time = p.t
                }
            } else {
                clusters.append(Peak(time: p.t, score: value))
            }
            lastActive = p.t
        }

        var merged = [Peak]()
        for c in clusters.sorted(by: { $0.time < $1.time }) {
            if var last = merged.last, (c.time - last.time) < minSpacingS {
                if c.score > last.score {
                    last.time = c.time
                    last.score = c.score
                    merged[merged.count - 1] = last
                }
            } else {
                merged.append(c)
            }
        }
        return Array(merged.prefix(limit))
    }

    // MARK: - Feature-Extraktion

    /// `extract_features` aus stroke_model.py: 7 Statistiken je Signal über das
    /// Zeitfenster [center-before, center+after]. Reihenfolge = signalNames × stats.
    static func extractFeatures(_ table: SensorTable, center: Double, before: Double, after: Double,
                                signalNames: [String]) -> [Double]? {
        let start = center - before
        let end = center + after
        var idx = [Int]()
        for (i, t) in table.times.enumerated() where t >= start && t <= end { idx.append(i) }
        if idx.count < 3 { return nil }

        var features = [Double]()
        features.reserveCapacity(signalNames.count * 7)
        for signal in signalNames {
            let full = table.values[signal] ?? []
            var w = [Double]()
            w.reserveCapacity(idx.count)
            for i in idx { w.append(i < full.count ? full[i] : 0.0) }
            features.append(contentsOf: stats(w))
        }
        return features
    }

    /// mean, std(pop), min, max, ptp, median, energy(mean of squares) – wie numpy.
    private static func stats(_ x: [Double]) -> [Double] {
        let n = Double(x.count)
        let mean = x.reduce(0, +) / n
        var sqDiff = 0.0, sqSum = 0.0
        var mn = x[0], mx = x[0]
        for v in x {
            let d = v - mean
            sqDiff += d * d
            sqSum += v * v
            if v < mn { mn = v }
            if v > mx { mx = v }
        }
        let std = (sqDiff / n).squareRoot()
        let energy = sqSum / n
        let sorted = x.sorted()
        let median: Double
        let c = sorted.count
        if c % 2 == 1 { median = sorted[c / 2] }
        else { median = (sorted[c / 2 - 1] + sorted[c / 2]) / 2.0 }
        return [mean, std, mn, mx, mx - mn, median, energy]
    }
}

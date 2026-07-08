import Foundation
import Combine

/// Eine erkannte Schlag-Vorhersage (für Anzeige & Marker).
struct StrokePrediction: Identifiable {
    let id = UUID()
    let time: Double          // Zeit auf der watch_uptime-Achse
    let label: String         // "Vorhand" | "Rueckhand"
    let confidence: Double    // 0…1
}

/// Ein Punkt der Live-Energiekurve.
struct StrokeChartPoint: Identifiable {
    let id = UUID()
    let t: Double
    let acc: Double           // |user acceleration|
    let gyro: Double          // |rotation rate|
}

/// On-device Schlag-Erkennung in Echtzeit. Hält einen rollierenden Puffer der
/// letzten Sekunden, erkennt Energie-Peaks und klassifiziert gesetzte Schläge mit
/// dem gebündelten RandomForest. Direkter Nachbau der `PredictionEngine` und
/// `StreamState` aus `tools/tennistracker_dashboard.py` – nur lokal statt am Mac.
final class StrokePredictor: ObservableObject {
    @Published private(set) var chartPoints: [StrokeChartPoint] = []
    @Published private(set) var predictions: [StrokePrediction] = []   // neueste zuerst
    @Published private(set) var lastPrediction: StrokePrediction? = nil
    @Published private(set) var totalStrokes = 0
    @Published private(set) var isActive = false
    @Published private(set) var modelLoaded: Bool

    let classes: [String]

    private let forest: StrokeForest?
    private let bufferCap = 800           // ~8 s bei 100 Hz (wie Dashboard)
    private let chartCap = 1200
    private let displayCap = 40

    private var buffer: [IMUSample] = []  // für die Erkennung
    private var predictedAbs: [Double] = []
    private let lock = NSLock()
    private let workQueue = DispatchQueue(label: "tennistracker.predict")
    private var timer: Timer?
    private var processing = false

    init(forest: StrokeForest? = StrokeForest.loadFromBundle()) {
        self.forest = forest
        self.modelLoaded = forest != nil
        self.classes = forest?.classes ?? ["Rueckhand", "Vorhand"]
    }

    // MARK: - Lebenszyklus

    func start() {
        lock.lock(); buffer.removeAll(keepingCapacity: true); lock.unlock()
        predictedAbs.removeAll(keepingCapacity: true)
        DispatchQueue.main.async {
            self.chartPoints.removeAll()
            self.predictions.removeAll()
            self.lastPrediction = nil
            self.totalStrokes = 0
            self.isActive = true
        }
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 0.35, repeats: true) { [weak self] _ in
            self?.tick()
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        DispatchQueue.main.async { self.isActive = false }
    }

    // MARK: - Dateneingang

    /// Wird vom `PhoneWatchBridge` im Predict-Modus mit jedem Batch gefüttert.
    func add(_ samples: [SensorSample]) {
        guard !samples.isEmpty, forest != nil else { return }
        let imu = samples.map { s in
            IMUSample(time: s.watch_uptime_s,
                      accX: s.acc_x_g, accY: s.acc_y_g, accZ: s.acc_z_g,
                      userAccX: s.user_acc_x_g, userAccY: s.user_acc_y_g, userAccZ: s.user_acc_z_g,
                      gyroX: s.gyro_x_rad_s, gyroY: s.gyro_y_rad_s, gyroZ: s.gyro_z_rad_s,
                      roll: s.roll_rad, pitch: s.pitch_rad, yaw: s.yaw_rad)
        }
        lock.lock()
        buffer.append(contentsOf: imu)
        if buffer.count > bufferCap { buffer.removeFirst(buffer.count - bufferCap) }
        lock.unlock()

        let pts = imu.map { s -> StrokeChartPoint in
            let acc = (s.userAccX * s.userAccX + s.userAccY * s.userAccY + s.userAccZ * s.userAccZ).squareRoot()
            let gyro = (s.gyroX * s.gyroX + s.gyroY * s.gyroY + s.gyroZ * s.gyroZ).squareRoot()
            return StrokeChartPoint(t: s.time, acc: acc, gyro: gyro)
        }
        DispatchQueue.main.async {
            self.chartPoints.append(contentsOf: pts)
            if self.chartPoints.count > self.chartCap {
                self.chartPoints.removeFirst(self.chartPoints.count - self.chartCap)
            }
        }
    }

    // MARK: - Erkennung

    private func tick() {
        workQueue.async { [weak self] in
            guard let self, !self.processing else { return }
            self.processing = true
            self.runOnce()
            self.processing = false
        }
    }

    private func runOnce() {
        guard let forest else { return }
        lock.lock(); let samples = buffer; lock.unlock()
        guard samples.count >= 40 else { return }

        let table = SensorTable(samples: samples)
        guard let latest = table.times.last else { return }
        let settle = forest.windowAfterS + 0.15

        let peaks = StrokeDetection.detectEnergyPeaks(table)
        var fresh: [StrokePrediction] = []
        for peak in peaks {
            let center = peak.time
            if center > latest - settle { continue }                       // noch zu frisch
            if predictedAbs.contains(where: { abs(center - $0) < 0.4 }) { continue }
            guard let vec = StrokeDetection.extractFeatures(
                table, center: center, before: forest.windowBeforeS, after: forest.windowAfterS,
                signalNames: forest.signalNames) else { continue }
            let result = forest.classify(vec)
            predictedAbs.append(center)
            fresh.append(StrokePrediction(time: center, label: result.label, confidence: result.confidence))
        }
        if predictedAbs.count > 300 { predictedAbs.removeFirst(predictedAbs.count - 300) }
        guard !fresh.isEmpty else { return }

        DispatchQueue.main.async {
            for p in fresh { self.predictions.insert(p, at: 0) }
            if self.predictions.count > self.displayCap {
                self.predictions.removeLast(self.predictions.count - self.displayCap)
            }
            self.lastPrediction = fresh.max(by: { $0.time < $1.time })
            self.totalStrokes += fresh.count
        }
    }
}

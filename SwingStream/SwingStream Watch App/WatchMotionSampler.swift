import Foundation
import CoreMotion

/// Liest Device-Motion mit 50 Hz, vergibt fortlaufende Sequenznummern und liefert
/// die Samples in kleinen Batches über `onBatch` aus.
final class WatchMotionSampler: ObservableObject {
    private let motion = CMMotionManager()
    private let queue: OperationQueue = {
        let q = OperationQueue()
        q.maxConcurrentOperationCount = 1
        q.name = "swingstream.motion"
        return q
    }()

    @Published var isRunning = false
    @Published var sampleCount = 0
    @Published var rateHz = 0.0

    /// Wird für jeden fertigen Batch aufgerufen (auf der Motion-Queue).
    var onBatch: ((SensorBatch) -> Void)?

    private let sampleRate = 50.0
    private let batchSize = 5
    private var sequence = 0
    private var sessionId = ""
    private var buffer: [SensorSample] = []

    // Ratenmessung
    private var rateWindowStart = Date()
    private var rateWindowCount = 0

    func start() {
        guard motion.isDeviceMotionAvailable, !isRunning else { return }
        sequence = 0
        sampleCount = 0
        buffer.removeAll(keepingCapacity: true)
        rateWindowStart = Date()
        rateWindowCount = 0

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd_HHmmss"
        sessionId = formatter.string(from: Date())

        motion.deviceMotionUpdateInterval = 1.0 / sampleRate
        isRunning = true

        motion.startDeviceMotionUpdates(to: queue) { [weak self] dm, _ in
            guard let self, let dm else { return }
            self.handle(dm)
        }
    }

    func stop() {
        guard isRunning else { return }
        motion.stopDeviceMotionUpdates()
        // Restpuffer noch rausschicken.
        flush()
        DispatchQueue.main.async {
            self.isRunning = false
            self.rateHz = 0
        }
    }

    private func handle(_ dm: CMDeviceMotion) {
        let ua = dm.userAcceleration
        let g = dm.gravity
        let rr = dm.rotationRate
        let att = dm.attitude
        let q = att.quaternion

        let sample = SensorSample(
            sequence: sequence,
            timestamp_unix_s: Date().timeIntervalSince1970,
            watch_uptime_s: dm.timestamp,            // Sekunden seit letztem Reboot
            user_acc_x_g: ua.x, user_acc_y_g: ua.y, user_acc_z_g: ua.z,
            gyro_x_rad_s: rr.x, gyro_y_rad_s: rr.y, gyro_z_rad_s: rr.z,
            // Rohbeschleunigung = User-Acceleration + Gravity (in G).
            acc_x_g: ua.x + g.x, acc_y_g: ua.y + g.y, acc_z_g: ua.z + g.z,
            gravity_x_g: g.x, gravity_y_g: g.y, gravity_z_g: g.z,
            roll_rad: att.roll, pitch_rad: att.pitch, yaw_rad: att.yaw,
            quat_x: q.x, quat_y: q.y, quat_z: q.z, quat_w: q.w
        )
        sequence += 1
        buffer.append(sample)
        rateWindowCount += 1

        if buffer.count >= batchSize {
            flush()
        }

        updateStats()
    }

    private func flush() {
        guard !buffer.isEmpty else { return }
        let batch = SensorBatch(source: "watch", session_id: sessionId, samples: buffer)
        buffer.removeAll(keepingCapacity: true)
        onBatch?(batch)
    }

    private func updateStats() {
        let now = Date()
        let elapsed = now.timeIntervalSince(rateWindowStart)
        let count = sequence
        if elapsed >= 0.5 {
            let hz = Double(rateWindowCount) / elapsed
            rateWindowStart = now
            rateWindowCount = 0
            DispatchQueue.main.async {
                self.rateHz = (self.rateHz * 0.5) + (hz * 0.5)
                self.sampleCount = count
            }
        } else {
            DispatchQueue.main.async { self.sampleCount = count }
        }
    }
}

import Foundation

/// Gemeinsames CSV-Format für Uhr und iPhone. Spalten exakt wie die vorhandenen
/// Apple-Watch-CSVs, damit die Dateien direkt durch die ML4SCS-Pipeline laufen
/// (src/stroke_model.load_sensor_table, src/predict.py, Modell v_r_v1.pkl).
enum CanonicalCSV {
    static let header = "loggingTime(txt),motionTimestamp_sinceReboot(s),accelerometerTimestamp_sinceReboot(s),accelerometerAccelerationX(G),accelerometerAccelerationY(G),accelerometerAccelerationZ(G),motionUserAccelerationX(G),motionUserAccelerationY(G),motionUserAccelerationZ(G),motionRotationRateX(rad/s),motionRotationRateY(rad/s),motionRotationRateZ(rad/s),motionGravityX(G),motionGravityY(G),motionGravityZ(G),motionRoll(rad),motionPitch(rad),motionYaw(rad),motionQuaternionX(R),motionQuaternionY(R),motionQuaternionZ(R),motionQuaternionW(R),sequence,label\n"

    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func row(_ s: SensorSample) -> String {
        let t = iso.string(from: Date(timeIntervalSince1970: s.timestamp_unix_s))
        let fields: [String] = [
            t, "\(s.watch_uptime_s)", "\(s.watch_uptime_s)",
            "\(s.acc_x_g)", "\(s.acc_y_g)", "\(s.acc_z_g)",
            "\(s.user_acc_x_g)", "\(s.user_acc_y_g)", "\(s.user_acc_z_g)",
            "\(s.gyro_x_rad_s)", "\(s.gyro_y_rad_s)", "\(s.gyro_z_rad_s)",
            "\(s.gravity_x_g)", "\(s.gravity_y_g)", "\(s.gravity_z_g)",
            "\(s.roll_rad)", "\(s.pitch_rad)", "\(s.yaw_rad)",
            "\(s.quat_x)", "\(s.quat_y)", "\(s.quat_z)", "\(s.quat_w)",
            "\(s.sequence)", "0"
        ]
        return fields.joined(separator: ",") + "\n"
    }

    static func rows(_ samples: [SensorSample]) -> String {
        var text = ""
        text.reserveCapacity(samples.count * 220)
        for s in samples { text += row(s) }
        return text
    }
}

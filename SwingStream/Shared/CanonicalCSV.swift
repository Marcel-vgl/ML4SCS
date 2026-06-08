import Foundation

/// Gemeinsames CSV-Format für Uhr und iPhone. Die Spalten folgen der vorhandenen
/// SensorLog-Apple-Watch-Struktur aus `Daten/fritz_*.csv`. Nicht von SwingStream
/// erfasste Sensorgruppen werden mit stabilen Platzhalterwerten geschrieben.
enum CanonicalCSV {
    static let columns = [
        "loggingTime(txt)",
        "locationTimestamp_since1970(s)",
        "locationLatitude(WGS84)",
        "locationLongitude(WGS84)",
        "locationAltitude(m)",
        "locationSpeed(m/s)",
        "locationSpeedAccuracy(m/s)",
        "locationCourse(°)",
        "locationCourseAccuracy(°)",
        "locationVerticalAccuracy(m)",
        "locationHorizontalAccuracy(m)",
        "locationFloor(Z)",
        "accelerometerTimestamp_sinceReboot(s)",
        "accelerometerAccelerationX(G)",
        "accelerometerAccelerationY(G)",
        "accelerometerAccelerationZ(G)",
        "motionTimestamp_sinceReboot(s)",
        "motionYaw(rad)",
        "motionRoll(rad)",
        "motionPitch(rad)",
        "motionRotationRateX(rad/s)",
        "motionRotationRateY(rad/s)",
        "motionRotationRateZ(rad/s)",
        "motionUserAccelerationX(G)",
        "motionUserAccelerationY(G)",
        "motionUserAccelerationZ(G)",
        "motionAttitudeReferenceFrame(txt)",
        "motionQuaternionX(R)",
        "motionQuaternionY(R)",
        "motionQuaternionZ(R)",
        "motionQuaternionW(R)",
        "motionGravityX(G)",
        "motionGravityY(G)",
        "motionGravityZ(G)",
        "motionMagneticFieldX(µT)",
        "motionMagneticFieldY(µT)",
        "motionMagneticFieldZ(µT)",
        "motionHeading(°)",
        "motionMagneticFieldCalibrationAccuracy(Z)",
        "pedometerStartDate(txt)",
        "pedometerNumberofSteps(N)",
        "pedometerAverageActivePace(s/m)",
        "pedometerCurrentPace(s/m)",
        "pedometerCurrentCadence(steps/s)",
        "pedometerDistance(m)",
        "pedometerFloorAscended(N)",
        "pedometerFloorDescended(N)",
        "pedometerEndDate(txt)",
        "altimeterTimestamp_sinceReboot(s)",
        "altimeterReset(bool)",
        "altimeterRelativeAltitude(m)",
        "altimeterPressure(kPa)",
        "label",
    ]

    static let header = columns.joined(separator: ",") + "\n"

    private static let iso: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static func row(_ s: SensorSample) -> String {
        let t = iso.string(from: Date(timeIntervalSince1970: s.timestamp_unix_s))
        let fields: [String] = [
            t,
            "\(s.timestamp_unix_s)",
            "0", "0", "0",
            "-1", "-1", "-1", "-1",
            "-1", "-1", "-9999",
            "\(s.watch_uptime_s)",
            "\(s.acc_x_g)", "\(s.acc_y_g)", "\(s.acc_z_g)",
            "\(s.watch_uptime_s)",
            "\(s.yaw_rad)", "\(s.roll_rad)", "\(s.pitch_rad)",
            "\(s.gyro_x_rad_s)", "\(s.gyro_y_rad_s)", "\(s.gyro_z_rad_s)",
            "\(s.user_acc_x_g)", "\(s.user_acc_y_g)", "\(s.user_acc_z_g)",
            "XArbitraryZVertical",
            "\(s.quat_x)", "\(s.quat_y)", "\(s.quat_z)", "\(s.quat_w)",
            "\(s.gravity_x_g)", "\(s.gravity_y_g)", "\(s.gravity_z_g)",
            "0", "0", "0",
            "-1", "-1",
            "",
            "0", "0", "0", "0", "0", "0", "0",
            "",
            "\(s.watch_uptime_s)", "0", "0", "0",
            "0",
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

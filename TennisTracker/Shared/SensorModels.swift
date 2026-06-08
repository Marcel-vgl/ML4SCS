import Foundation

/// Ein einzelnes Sensor-Sample. Die JSON-Schlüssel sind bewusst kompakt und
/// entsprechen exakt dem Protokoll, das das Mac-Dashboard (`/api/ingest`) erwartet
/// und auf die kanonischen Apple-Watch-CSV-Spalten abbildet.
///
/// Da die Property-Namen bereits dem JSON-Format entsprechen (snake_case), reicht
/// die synthetisierte `Codable`-Implementierung ohne `CodingKeys`.
struct SensorSample: Codable {
    let sequence: Int
    let timestamp_unix_s: Double
    let watch_uptime_s: Double

    let user_acc_x_g: Double
    let user_acc_y_g: Double
    let user_acc_z_g: Double

    let gyro_x_rad_s: Double
    let gyro_y_rad_s: Double
    let gyro_z_rad_s: Double

    let acc_x_g: Double
    let acc_y_g: Double
    let acc_z_g: Double

    let gravity_x_g: Double
    let gravity_y_g: Double
    let gravity_z_g: Double

    let roll_rad: Double
    let pitch_rad: Double
    let yaw_rad: Double

    let quat_x: Double
    let quat_y: Double
    let quat_z: Double
    let quat_w: Double
}

/// Ein Batch aus mehreren Samples. Optionale Felder (`source`,
/// `bridge_received_unix_s`) werden bei `nil` automatisch aus dem JSON weggelassen.
struct SensorBatch: Codable {
    var type: String = "sensor_batch"
    var source: String? = nil
    var session_id: String
    var bridge_received_unix_s: Double? = nil
    var samples: [SensorSample]
}

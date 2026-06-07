import Foundation
import Combine

/// Koordiniert eine Aufnahme-Session auf der Uhr:
/// Workout-Session (Hintergrund) + 100-Hz-Sampler + verlustfreie lokale Datei +
/// Live-Stream ans iPhone. Steuerbar lokal (Buttons) oder per iPhone-Befehl.
final class WatchSessionController: ObservableObject {
    let sampler = WatchMotionSampler()
    let workout = WatchWorkoutKeeper()
    let recorder = WatchLocalRecorder()
    let link = WatchConnectivitySender.shared

    @Published var isRunning = false
    @Published var sessionName = ""

    private let stampFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd_HHmmss"
        return f
    }()

    init() {
        sampler.onBatch = { [weak self] batch in
            // 1) verlustfrei lokal speichern, 2) live ans iPhone (Vorschau/Predict)
            self?.recorder.append(batch.samples)
            self?.link.send(batch)
        }
        link.onCommand = { [weak self] command, session in
            guard let self else { return }
            if command == "start" {
                self.start(session: session.isEmpty ? self.autoName() : session)
            } else if command == "stop" {
                self.stop()
            }
        }
        workout.requestAuthorization()
    }

    private func autoName() -> String {
        "session_\(stampFormatter.string(from: Date()))"
    }

    func start(session: String) {
        guard !isRunning else { return }
        sessionName = session
        workout.start()
        recorder.start(session: session)
        sampler.start()
        isRunning = true
    }

    func stop() {
        guard isRunning else { return }
        sampler.stop()
        // Datei schließen und ans iPhone übertragen, BEVOR die Workout-Runtime endet.
        if let url = recorder.close() {
            link.transferFile(url, session: sessionName)
        }
        workout.stop()
        isRunning = false
    }

    /// Manueller Start über den Watch-Button.
    func toggleManual() {
        if isRunning { stop() } else { start(session: autoName()) }
    }
}

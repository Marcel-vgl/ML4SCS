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
    private let outputQueue = DispatchQueue(label: "com.florianschneider.SwingStream.watchOutput")
    private var pendingStart: DispatchWorkItem?
    private var sessionMode = "label"

    @Published var isRunning = false
    @Published var sessionName = ""

    private let stampFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd_HHmmss"
        return f
    }()

    init() {
        sampler.onBatch = { [weak self] batch in
            guard let self else { return }
            self.outputQueue.async {
                // 1) verlustfrei lokal speichern, 2) live ans iPhone (Vorschau/Predict).
                // Nicht auf der CoreMotion-Queue ausführen, sonst verliert CMMotionManager Samples.
                self.recorder.append(batch.samples)
                self.link.send(batch)
            }
        }
        link.onCommand = { [weak self] command, session, startAtUnix, mode in
            guard let self else { return }
            if command == "start" {
                self.start(
                    session: session.isEmpty ? self.autoName() : session,
                    mode: mode ?? "label",
                    scheduledStartUnix: startAtUnix
                )
            } else if command == "stop" {
                self.stop()
            }
        }
        workout.requestAuthorization()
    }

    private func autoName() -> String {
        "session_\(stampFormatter.string(from: Date()))"
    }

    func start(session: String, mode: String = "label", scheduledStartUnix: Double? = nil) {
        guard !isRunning else { return }
        sessionName = session
        sessionMode = mode
        workout.start { [weak self] started in
            guard let self else { return }
            guard started else {
                self.sessionName = ""
                self.sessionMode = "label"
                self.isRunning = false
                return
            }

            self.outputQueue.sync {
                _ = self.recorder.start(session: session)
            }
            self.isRunning = true
            self.scheduleSampler(session: session, scheduledStartUnix: scheduledStartUnix)
        }
    }

    private func scheduleSampler(session: String, scheduledStartUnix: Double?) {
        let startSampler = { [weak self] in
            guard let self, self.isRunning, self.sessionName == session else { return }
            self.sampler.start(anchorUnix: scheduledStartUnix)
            self.pendingStart = nil
        }

        if let scheduledStartUnix {
            let delay = scheduledStartUnix - Date().timeIntervalSince1970
            if delay > 0.02 {
                let work = DispatchWorkItem(block: startSampler)
                pendingStart = work
                DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
            } else {
                startSampler()
            }
        } else {
            startSampler()
        }
    }

    func stop() {
        guard isRunning else { return }
        pendingStart?.cancel()
        pendingStart = nil
        sampler.stop()
        let session = sessionName
        let mode = sessionMode
        outputQueue.async { [weak self] in
            guard let self else { return }
            // Datei schließen und ans iPhone übertragen, nachdem alle ausstehenden Batches geschrieben wurden.
            if let url = self.recorder.close() {
                self.link.transferFile(url, session: session, mode: mode)
            }
            self.workout.stop()
        }
        isRunning = false
        sessionMode = "label"
    }

    /// Manueller Start über den Watch-Button.
    func toggleManual() {
        if isRunning { stop() } else { start(session: autoName()) }
    }
}

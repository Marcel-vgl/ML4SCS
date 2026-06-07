import Foundation
import HealthKit

/// Hält die Watch-App im Hintergrund am Leben. Startet eine vollständige
/// Trainingseinheit inкл. `HKLiveWorkoutBuilder` mit `beginCollection` – nur so
/// liefert CoreMotion auch bei ausgeschaltetem Display zuverlässig weiter Samples.
final class WatchWorkoutKeeper: NSObject, ObservableObject, HKWorkoutSessionDelegate, HKLiveWorkoutBuilderDelegate {
    private let healthStore = HKHealthStore()
    private var session: HKWorkoutSession?
    private var builder: HKLiveWorkoutBuilder?

    @Published var active = false
    @Published var authorized = false

    func requestAuthorization() {
        guard HKHealthStore.isHealthDataAvailable() else { return }
        let share: Set = [HKObjectType.workoutType()]
        var read: Set<HKObjectType> = [HKObjectType.workoutType()]
        if let heartRate = HKObjectType.quantityType(forIdentifier: .heartRate) {
            read.insert(heartRate)
        }
        healthStore.requestAuthorization(toShare: share, read: read) { ok, _ in
            DispatchQueue.main.async { self.authorized = ok }
        }
    }

    func start() {
        guard HKHealthStore.isHealthDataAvailable(), session == nil else { return }
        let config = HKWorkoutConfiguration()
        config.activityType = .tennis
        config.locationType = .outdoor
        do {
            let session = try HKWorkoutSession(healthStore: healthStore, configuration: config)
            let builder = session.associatedWorkoutBuilder()
            builder.dataSource = HKLiveWorkoutDataSource(healthStore: healthStore, workoutConfiguration: config)
            session.delegate = self
            builder.delegate = self
            self.session = session
            self.builder = builder
            let start = Date()
            session.startActivity(with: start)
            builder.beginCollection(withStart: start) { _, _ in }
            DispatchQueue.main.async { self.active = true }
        } catch {
            DispatchQueue.main.async { self.active = false }
        }
    }

    func stop() {
        guard let session, let builder else {
            DispatchQueue.main.async { self.active = false }
            return
        }
        let end = Date()
        session.end()
        builder.endCollection(withEnd: end) { _, _ in
            builder.finishWorkout { _, _ in }
        }
        self.session = nil
        self.builder = nil
        DispatchQueue.main.async { self.active = false }
    }

    // MARK: - HKWorkoutSessionDelegate

    func workoutSession(_ workoutSession: HKWorkoutSession,
                        didChangeTo toState: HKWorkoutSessionState,
                        from fromState: HKWorkoutSessionState,
                        date: Date) {
        DispatchQueue.main.async { self.active = (toState == .running) }
    }

    func workoutSession(_ workoutSession: HKWorkoutSession, didFailWithError error: Error) {
        DispatchQueue.main.async { self.active = false }
    }

    // MARK: - HKLiveWorkoutBuilderDelegate

    func workoutBuilder(_ workoutBuilder: HKLiveWorkoutBuilder, didCollectDataOf collectedTypes: Set<HKSampleType>) {}
    func workoutBuilderDidCollectEvent(_ workoutBuilder: HKLiveWorkoutBuilder) {}
}

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
    @Published var lastError = ""

    func requestAuthorization(completion: ((Bool) -> Void)? = nil) {
        guard HKHealthStore.isHealthDataAvailable() else {
            DispatchQueue.main.async {
                self.authorized = false
                self.lastError = "HealthKit ist auf dieser Watch nicht verfügbar."
                completion?(false)
            }
            return
        }
        let workoutType = HKObjectType.workoutType()
        let share: Set = [workoutType]
        var read: Set<HKObjectType> = [HKObjectType.workoutType()]
        if let heartRate = HKObjectType.quantityType(forIdentifier: .heartRate) {
            read.insert(heartRate)
        }
        healthStore.requestAuthorization(toShare: share, read: read) { ok, _ in
            let canShareWorkout = self.healthStore.authorizationStatus(for: workoutType) == .sharingAuthorized
            DispatchQueue.main.async {
                self.authorized = ok && canShareWorkout
                self.lastError = self.authorized ? "" : "HealthKit-Workout-Berechtigung fehlt."
                completion?(self.authorized)
            }
        }
    }

    func start(completion: ((Bool) -> Void)? = nil) {
        guard HKHealthStore.isHealthDataAvailable() else {
            DispatchQueue.main.async {
                self.active = false
                self.lastError = "HealthKit ist auf dieser Watch nicht verfügbar."
                completion?(false)
            }
            return
        }
        guard session == nil else {
            DispatchQueue.main.async {
                self.active = true
                completion?(true)
            }
            return
        }
        let workoutType = HKObjectType.workoutType()
        guard healthStore.authorizationStatus(for: workoutType) == .sharingAuthorized else {
            requestAuthorization { [weak self] ok in
                guard ok else {
                    completion?(false)
                    return
                }
                self?.start(completion: completion)
            }
            return
        }

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
            DispatchQueue.main.async {
                self.active = true
                self.lastError = ""
                completion?(true)
            }
        } catch {
            DispatchQueue.main.async {
                self.active = false
                self.lastError = error.localizedDescription
                completion?(false)
            }
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
        DispatchQueue.main.async {
            self.active = false
            self.lastError = error.localizedDescription
        }
    }

    // MARK: - HKLiveWorkoutBuilderDelegate

    func workoutBuilder(_ workoutBuilder: HKLiveWorkoutBuilder, didCollectDataOf collectedTypes: Set<HKSampleType>) {}
    func workoutBuilderDidCollectEvent(_ workoutBuilder: HKLiveWorkoutBuilder) {}
}

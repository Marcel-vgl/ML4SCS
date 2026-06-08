import Foundation
import AVFoundation
import SwiftUI
import UIKit

struct LabelVideoMetadata: Codable {
    let type: String
    let session_id: String
    let video_filename: String
    let camera: String
    let quality: String
    let video_orientation: String
    let video_rotation_angle_degrees: Double
    let video_start_unix_s: Double
    let session_anchor_unix_s: Double?
    let video_anchor_time_s: Double?
    let video_stop_unix_s: Double
    let video_duration_s: Double
    let created_unix_s: Double
    let sync_formula: String
}

enum LabelCameraOption: String, CaseIterable, Identifiable {
    case backWide
    case front
    case ultraWide
    case telephoto

    var id: String { rawValue }

    var title: String {
        switch self {
        case .backWide:
            return "Rueckkamera"
        case .front:
            return "Frontkamera"
        case .ultraWide:
            return "Ultraweitwinkel"
        case .telephoto:
            return "Tele"
        }
    }
}

enum LabelVideoQuality: String, CaseIterable, Identifiable {
    case hd720
    case hd1080
    case high
    case medium

    var id: String { rawValue }

    var title: String {
        switch self {
        case .hd720:
            return "720p"
        case .hd1080:
            return "1080p"
        case .high:
            return "Hoch"
        case .medium:
            return "Mittel"
        }
    }

    var preset: AVCaptureSession.Preset {
        switch self {
        case .hd720:
            return .hd1280x720
        case .hd1080:
            return .hd1920x1080
        case .high:
            return .high
        case .medium:
            return .medium
        }
    }
}

/// Nimmt im Label-Modus ein iPhone-Video parallel zur Watch-CSV auf.
final class LabelVideoRecorder: NSObject, ObservableObject, AVCaptureFileOutputRecordingDelegate {
    @Published var authorizationStatus: AVAuthorizationStatus = AVCaptureDevice.authorizationStatus(for: .video)
    @Published var isReady = false
    @Published var isRecording = false
    @Published var statusText = "Video nicht vorbereitet"
    @Published var lastError: String?
    @Published var selectedCamera: LabelCameraOption = .backWide {
        didSet { reconfigureForSettingsChange() }
    }
    @Published var selectedQuality: LabelVideoQuality = .hd1080 {
        didSet { reconfigureForSettingsChange() }
    }
    @Published var videoRotationAngle: CGFloat = 90

    let captureSession = AVCaptureSession()
    var onRecordingFinished: (() -> Void)?

    private let sessionQueue = DispatchQueue(label: "com.florianschneider.SwingStream.labelVideo")
    private let movieOutput = AVCaptureMovieFileOutput()
    private var isConfigured = false
    private var videoInput: AVCaptureDeviceInput?
    private var audioInput: AVCaptureDeviceInput?
    private var activeSessionID: String?
    private var activeURL: URL?
    private var activeStartUnix: Double?
    private var activeSessionAnchorUnix: Double?
    private var activeCameraTitle: String?
    private var activeQualityTitle: String?
    private var activeOrientationTitle: String?
    private var activeRotationAngle: Double?
    private var startCompletion: ((Bool) -> Void)?

    override init() {
        super.init()
        UIDevice.current.beginGeneratingDeviceOrientationNotifications()
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleOrientationChange),
            name: UIDevice.orientationDidChangeNotification,
            object: nil
        )
        refreshVideoOrientation()
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
        UIDevice.current.endGeneratingDeviceOrientationNotifications()
    }

    func prepare() {
        requestPermissions { [weak self] granted in
            guard let self else { return }
            guard granted else {
                self.publishError("Kamera nicht erlaubt")
                return
            }
            let angle = Self.currentVideoRotationAngle()
            self.sessionQueue.async {
                self.configureSession(rotationAngle: angle)
                if !self.captureSession.isRunning {
                    self.captureSession.startRunning()
                }
                DispatchQueue.main.async {
                    self.isReady = self.isConfigured
                    self.statusText = self.isConfigured ? "Video bereit" : "Video nicht verfügbar"
                }
            }
        }
    }

    func startRecording(sessionID: String, completion: @escaping (Bool) -> Void = { _ in }) {
        requestPermissions { [weak self] granted in
            guard let self else { return }
            guard granted else {
                self.publishError("Kamera nicht erlaubt")
                completion(false)
                return
            }

            let angle = Self.currentVideoRotationAngle()
            let title = Self.currentVideoOrientationTitle(for: angle)
            let cameraTitle = self.selectedCamera.title
            let qualityTitle = self.selectedQuality.title

            self.sessionQueue.async {
                self.configureSession(rotationAngle: angle)
                guard self.isConfigured else {
                    self.publishError("Kamera konnte nicht eingerichtet werden")
                    DispatchQueue.main.async { completion(false) }
                    return
                }
                guard !self.movieOutput.isRecording else {
                    DispatchQueue.main.async { completion(true) }
                    return
                }

                if !self.captureSession.isRunning {
                    self.captureSession.startRunning()
                }

                let safeSession = sessionID.replacingOccurrences(of: "/", with: "-")
                let url = RecordingStore.dir().appendingPathComponent("\(safeSession).mov")
                try? FileManager.default.removeItem(at: url)

                if let connection = self.movieOutput.connection(with: .video),
                   connection.isVideoRotationAngleSupported(angle) {
                    connection.videoRotationAngle = angle
                }

                self.activeSessionID = safeSession
                self.activeURL = url
                self.activeStartUnix = nil
                self.activeSessionAnchorUnix = nil
                self.activeCameraTitle = cameraTitle
                self.activeQualityTitle = qualityTitle
                self.activeOrientationTitle = title
                self.activeRotationAngle = Double(angle)
                self.startCompletion = completion
                self.movieOutput.startRecording(to: url, recordingDelegate: self)

                DispatchQueue.main.async {
                    self.lastError = nil
                    self.statusText = "Video startet"
                }
            }
        }
    }

    func refreshVideoOrientation() {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            let angle = Self.currentVideoRotationAngle()
            self.videoRotationAngle = angle
            self.sessionQueue.async {
                self.applyVideoRotation(angle)
            }
        }
    }

    func setSessionAnchor(_ anchorUnix: Double) {
        sessionQueue.async {
            self.activeSessionAnchorUnix = anchorUnix
        }
    }

    func stopRecording() {
        sessionQueue.async {
            if self.movieOutput.isRecording {
                self.movieOutput.stopRecording()
            }
        }
    }

    var availableCameras: [LabelCameraOption] {
        LabelCameraOption.allCases.filter { device(for: $0) != nil }
    }

    private func requestPermissions(_ completion: @escaping (Bool) -> Void) {
        let videoStatus = AVCaptureDevice.authorizationStatus(for: .video)
        let audioStatus = AVCaptureDevice.authorizationStatus(for: .audio)

        DispatchQueue.main.async {
            self.authorizationStatus = videoStatus
        }

        let group = DispatchGroup()
        var videoGranted = videoStatus == .authorized

        if videoStatus == .notDetermined {
            group.enter()
            AVCaptureDevice.requestAccess(for: .video) { granted in
                videoGranted = granted
                group.leave()
            }
        }

        if audioStatus == .notDetermined {
            group.enter()
            AVCaptureDevice.requestAccess(for: .audio) { _ in
                group.leave()
            }
        }

        group.notify(queue: .main) {
            self.authorizationStatus = AVCaptureDevice.authorizationStatus(for: .video)
            completion(videoGranted)
        }
    }

    private func reconfigureForSettingsChange() {
        let angle = Self.currentVideoRotationAngle()
        sessionQueue.async {
            guard self.isConfigured, !self.movieOutput.isRecording else { return }
            self.configureSession(rotationAngle: angle)
            if !self.captureSession.isRunning {
                self.captureSession.startRunning()
            }
        }
    }

    private func configureSession(rotationAngle: CGFloat) {
        captureSession.beginConfiguration()

        let preset = selectedQuality.preset
        captureSession.sessionPreset = captureSession.canSetSessionPreset(preset) ? preset : .high

        if let videoInput {
            captureSession.removeInput(videoInput)
            self.videoInput = nil
        }
        if let audioInput {
            captureSession.removeInput(audioInput)
            self.audioInput = nil
        }

        guard
            let camera = device(for: selectedCamera) ?? AVCaptureDevice.default(for: .video),
            let videoInput = try? AVCaptureDeviceInput(device: camera),
            captureSession.canAddInput(videoInput)
        else {
            isConfigured = false
            captureSession.commitConfiguration()
            return
        }
        captureSession.addInput(videoInput)
        self.videoInput = videoInput

        if AVCaptureDevice.authorizationStatus(for: .audio) == .authorized,
           let microphone = AVCaptureDevice.default(for: .audio),
           let audioInput = try? AVCaptureDeviceInput(device: microphone),
           captureSession.canAddInput(audioInput) {
            captureSession.addInput(audioInput)
            self.audioInput = audioInput
        }

        if !captureSession.outputs.contains(movieOutput), captureSession.canAddOutput(movieOutput) {
            captureSession.addOutput(movieOutput)
        }

        guard captureSession.outputs.contains(movieOutput) else {
            isConfigured = false
            captureSession.commitConfiguration()
            return
        }

        captureSession.commitConfiguration()
        applyVideoRotation(rotationAngle)
        isConfigured = true
    }

    private func applyVideoRotation(_ angle: CGFloat) {
        guard let connection = movieOutput.connection(with: .video),
              connection.isVideoRotationAngleSupported(angle)
        else { return }
        connection.videoRotationAngle = angle
    }

    private func device(for option: LabelCameraOption) -> AVCaptureDevice? {
        switch option {
        case .backWide:
            return AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back)
        case .front:
            return AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .front)
        case .ultraWide:
            return AVCaptureDevice.default(.builtInUltraWideCamera, for: .video, position: .back)
        case .telephoto:
            return AVCaptureDevice.default(.builtInTelephotoCamera, for: .video, position: .back)
        }
    }

    private func publishError(_ message: String) {
        DispatchQueue.main.async {
            self.lastError = message
            self.statusText = message
            self.isReady = false
            self.isRecording = false
        }
    }

    private func writeMetadata(stopUnix: Double) {
        guard
            let sessionID = activeSessionID,
            let videoURL = activeURL,
            let startUnix = activeStartUnix
        else { return }

        let anchorUnix = activeSessionAnchorUnix
        let rotationAngle = activeRotationAngle ?? 90
        let metadata = LabelVideoMetadata(
            type: "swingstream_label_video_metadata",
            session_id: sessionID,
            video_filename: videoURL.lastPathComponent,
            camera: activeCameraTitle ?? selectedCamera.title,
            quality: activeQualityTitle ?? selectedQuality.title,
            video_orientation: activeOrientationTitle ?? Self.currentVideoOrientationTitle(for: CGFloat(rotationAngle)),
            video_rotation_angle_degrees: rotationAngle,
            video_start_unix_s: startUnix,
            session_anchor_unix_s: anchorUnix,
            video_anchor_time_s: anchorUnix.map { max(0, $0 - startUnix) },
            video_stop_unix_s: stopUnix,
            video_duration_s: max(0, stopUnix - startUnix),
            created_unix_s: Date().timeIntervalSince1970,
            sync_formula: "video_time_s = sample.timestamp_unix_s - video_start_unix_s; session_time_s = sample.timestamp_unix_s - session_anchor_unix_s"
        )

        let metadataURL = RecordingStore.dir().appendingPathComponent("\(sessionID)_video_metadata.json")
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            let data = try encoder.encode(metadata)
            try data.write(to: metadataURL, options: .atomic)
        } catch {
            publishError("Video-Metadaten konnten nicht gespeichert werden")
        }
    }

    @objc private func handleOrientationChange() {
        refreshVideoOrientation()
    }

    private static func currentVideoRotationAngle() -> CGFloat {
        switch currentInterfaceOrientation() {
        case .portrait:
            return 90
        case .portraitUpsideDown:
            return 270
        case .landscapeLeft:
            return 180
        case .landscapeRight:
            return 0
        default:
            switch UIDevice.current.orientation {
            case .portrait:
                return 90
            case .portraitUpsideDown:
                return 270
            case .landscapeLeft:
                return 180
            case .landscapeRight:
                return 0
            default:
                return 90
            }
        }
    }

    private static func currentVideoOrientationTitle(for angle: CGFloat) -> String {
        switch angle {
        case 0:
            return "landscapeRight"
        case 180:
            return "landscapeLeft"
        case 270:
            return "portraitUpsideDown"
        default:
            return "portrait"
        }
    }

    private static func currentInterfaceOrientation() -> UIInterfaceOrientation? {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }?
            .interfaceOrientation
    }

    func fileOutput(_ output: AVCaptureFileOutput,
                    didStartRecordingTo fileURL: URL,
                    from connections: [AVCaptureConnection]) {
        let startUnix = Date().timeIntervalSince1970
        let completion = startCompletion
        startCompletion = nil
        activeStartUnix = startUnix

        DispatchQueue.main.async {
            self.lastError = nil
            self.isRecording = true
            self.statusText = "Video läuft"
            completion?(true)
        }
    }

    func fileOutput(_ output: AVCaptureFileOutput,
                    didFinishRecordingTo outputFileURL: URL,
                    from connections: [AVCaptureConnection],
                    error: Error?) {
        let stopUnix = Date().timeIntervalSince1970
        if let completion = startCompletion {
            startCompletion = nil
            DispatchQueue.main.async { completion(false) }
        }
        writeMetadata(stopUnix: stopUnix)

        DispatchQueue.main.async {
            self.isRecording = false
            if let error {
                self.lastError = error.localizedDescription
                self.statusText = "Videofehler"
            } else {
                self.lastError = nil
                self.statusText = "Video gespeichert"
            }
            self.onRecordingFinished?()
        }
    }
}

struct LabelCameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    let rotationAngle: CGFloat

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.videoPreviewLayer.session = session
        view.videoPreviewLayer.videoGravity = .resizeAspectFill
        view.rotationAngle = rotationAngle
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        uiView.rotationAngle = rotationAngle
    }

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }

        var videoPreviewLayer: AVCaptureVideoPreviewLayer {
            layer as! AVCaptureVideoPreviewLayer
        }

        var rotationAngle: CGFloat = 90 {
            didSet {
                applyRotation()
            }
        }

        override func layoutSubviews() {
            super.layoutSubviews()
            applyRotation()
        }

        private func applyRotation() {
            guard let connection = videoPreviewLayer.connection else { return }
            if connection.isVideoRotationAngleSupported(rotationAngle) {
                connection.videoRotationAngle = rotationAngle
            }
        }
    }
}

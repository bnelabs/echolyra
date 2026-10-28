import AVFoundation
import Foundation

/// Emits the quiet probe sweep through the phone speaker while recording it, so the backend
/// can deconvolve the true room impulse response (co-located source + receiver).
@MainActor
final class ProbeRecorder: ObservableObject {
    @Published var isMeasuring = false
    @Published var status = ""

    func measure() async throws -> Data {
        let granted = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            AVAudioApplication.requestRecordPermission { c.resume(returning: $0) }
        }
        guard granted else {
            throw NSError(domain: "RoomSense", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Microphone access is off. Enable it in Settings → RoomSense → Microphone."])
        }
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
        try session.setPreferredSampleRate(48_000)
        try session.setActive(true)

        let sweepURL = FileManager.default.temporaryDirectory.appendingPathComponent("roomsense-probe.wav")
        try WAVWriter.mono16(ProbeSweep.samples(), sampleRate: ProbeSweep.sampleRate).write(to: sweepURL)
        let player = try AVAudioPlayer(contentsOf: sweepURL)
        player.volume = 0.6
        player.prepareToPlay()

        let recURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("roomsense-probe-rec-\(UUID().uuidString).wav")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: 48_000.0,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        let recorder = try AVAudioRecorder(url: recURL, settings: settings)
        isMeasuring = true
        status = "Measuring the room…"
        recorder.record()
        player.play()
        try await Task.sleep(nanoseconds: UInt64((ProbeSweep.duration + 1.8) * 1_000_000_000))
        recorder.stop()
        player.stop()
        isMeasuring = false
        status = ""
        try? session.setActive(false, options: .notifyOthersOnDeactivation)
        let data = try Data(contentsOf: recURL)
        try? FileManager.default.removeItem(at: recURL)
        try? FileManager.default.removeItem(at: sweepURL)
        return data
    }
}

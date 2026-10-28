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
            throw NSError(domain: "Echolyra", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Microphone access is off. Enable it in Settings → Echolyra → Microphone."])
        }
        try Task.checkCancellation()
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
        try session.setPreferredSampleRate(48_000)
        try session.setActive(true)

        let sweepURL = FileManager.default.temporaryDirectory.appendingPathComponent("echolyra-probe-\(UUID().uuidString).wav")
        let recURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("echolyra-probe-rec-\(UUID().uuidString).wav")
        defer {
            isMeasuring = false
            status = ""
            try? session.setActive(false, options: .notifyOthersOnDeactivation)
            try? FileManager.default.removeItem(at: recURL)
            try? FileManager.default.removeItem(at: sweepURL)
        }
        try WAVWriter.mono16(ProbeSweep.samples(), sampleRate: ProbeSweep.sampleRate).write(to: sweepURL)
        let player = try AVAudioPlayer(contentsOf: sweepURL)
        defer { player.stop() }
        player.volume = 0.6
        player.prepareToPlay()
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: 48_000.0,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        let recorder = try AVAudioRecorder(url: recURL, settings: settings)
        defer { recorder.stop() }
        guard recorder.record(), player.play() else {
            throw NSError(domain: "Echolyra", code: 3, userInfo: [
                NSLocalizedDescriptionKey: "Could not start the probe speaker and microphone. Try again with no other audio capture running."])
        }
        isMeasuring = true
        status = "Measuring the room…"
        try await Task.sleep(nanoseconds: UInt64((ProbeSweep.duration + 1.8) * 1_000_000_000))
        recorder.stop()
        player.stop()
        return try Data(contentsOf: recURL)
    }
}

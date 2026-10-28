import AVFoundation
import Foundation

/// Records a short linear-PCM clip (16 kHz mono CAF) — no playback, no sweep.
@MainActor
final class Recorder: ObservableObject {
    @Published var isRecording = false
    @Published var remaining: Double = 0

    func record(seconds: Double = 2.8) async throws -> Data {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: [])
        try session.setActive(true)

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("roomsense-\(UUID().uuidString).caf")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: 16_000.0,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
        ]
        let audioRecorder = try AVAudioRecorder(url: url, settings: settings)
        guard audioRecorder.record() else {
            throw NSError(domain: "RoomSense", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Could not start recording"])
        }
        isRecording = true
        let started = Date()
        while Date().timeIntervalSince(started) < seconds {
            remaining = max(0, seconds - Date().timeIntervalSince(started))
            try await Task.sleep(nanoseconds: 100_000_000)
        }
        audioRecorder.stop()
        isRecording = false
        remaining = 0
        try? session.setActive(false, options: .notifyOthersOnDeactivation)

        let data = try Data(contentsOf: url)
        try? FileManager.default.removeItem(at: url)
        return data
    }
}

import Foundation
import Darwin

@MainActor
final class AppModel: ObservableObject {
    @Published var backendURL: String {
        didSet { UserDefaults.standard.set(backendURL, forKey: "backendURL") }
    }
    @Published var session: SessionSummary?
    @Published var lastResult: DetectResponse?
    @Published var lastClip: Data?
    @Published var busy = false
    @Published var errorText: String?

    init() {
        let env = ProcessInfo.processInfo.environment["ROOMSENSE_BACKEND"]
        backendURL = env ?? UserDefaults.standard.string(forKey: "backendURL") ?? "http://192.168.68.50:8080"
    }

#if DEBUG
    /// Headless end-to-end check (launch with `-autotest`): record → enroll → detect → log.
    private func log(_ message: String) { print(message); fflush(stdout) }

    func runSelfTest() async {
        log("AUTOTEST start backend=\(backendURL)")
        let recorder = Recorder()
        do {
            let rec = try await recorder.record(seconds: 2.8)
            let clip = rec.data
            log("AUTOTEST recorded \(clip.count) bytes")
            session = try await client.enroll(roomID: "sim-test", roomName: "Simulator test room", clip: clip) ?? session
            log("AUTOTEST enrolled rooms=\(session?.rooms?.count ?? 0)")
            let heard = await SoundUnderstanding.classify(fileURL: rec.url)
            try? FileManager.default.removeItem(at: rec.url)
            log("AUTOTEST heard: \(heard.prefix(3).map { "\($0.label) \(Int($0.confidence * 100))%" }.joined(separator: ", "))")
            let result = try await client.detect(clip: clip, heard: heard)
            lastResult = result
            log("AUTOTEST detect label=\(result.event.label) conf=\(result.event.confidence) room=\(result.room.room_name ?? "nil") roomConf=\(result.room.confidence) situation=\(result.situation.headline ?? "nil") model=\(result.situation._model ?? "nil")")
        } catch {
            log("AUTOTEST error \(error.localizedDescription)")
        }
    }
#endif

    var client: APIClient {
        APIClient(baseURL: URL(string: backendURL) ?? URL(string: "http://127.0.0.1:8080")!)
    }

    func refresh() async {
        busy = true
        defer { busy = false }
        do { session = try await client.session() }
        catch { errorText = error.localizedDescription }
    }

    func enroll(roomName: String, clip: Data) async {
        busy = true
        defer { busy = false }
        let id = roomName.lowercased()
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "-")
        do { session = try await client.enroll(roomID: id, roomName: roomName, clip: clip) ?? session }
        catch { errorText = error.localizedDescription }
    }

    func detect(clip: Data, heard: [SoundLabel] = []) async {
        busy = true
        defer { busy = false }
        lastClip = clip
        do { lastResult = try await client.detect(clip: clip, heard: heard) }
        catch { errorText = error.localizedDescription }
    }

    func teach(label: String) async {
        guard let clip = lastClip else { return }
        busy = true
        defer { busy = false }
        do { session = try await client.teach(label: label, clip: clip) ?? session }
        catch { errorText = error.localizedDescription }
    }

    func reset() async {
        busy = true
        defer { busy = false }
        do {
            try await client.reset()
            session = try await client.session()
            lastResult = nil
        } catch { errorText = error.localizedDescription }
    }
}

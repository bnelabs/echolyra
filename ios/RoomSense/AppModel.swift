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
    /// Preload a sample detection card for screenshots (launch with `-sampleResult`).
    func loadSampleResult() {
        lastResult = DetectResponse(
            event: EventInfo(label: "glass_impact", confidence: 0.96, snr_db: 34.2,
                             reason: "on_device_classifier", ranking: nil),
            room: RoomMatch(room_id: "kitchen", room_name: "Kitchen", confidence: 0.97,
                            uncertain: false, reason: "match", snr_db: 34.2, ranking: nil),
            situation: Situation(
                urgency: "high",
                headline: "Glass break in the Kitchen",
                explanation: "A short, high-frequency impact was detected from the kitchen direction.",
                suggested_action: "Check for broken glass in the kitchen before walking through.",
                false_alarm_check: "A dropped mug or dish also sounds like this. Confirm before alarming anyone.",
                _model: "muse-spark-1.3-contributor"),
            certainty: 0.94,
            heard: [SoundLabel(label: "glass_breaking", confidence: 0.91),
                    SoundLabel(label: "glass_clink", confidence: 0.62)],
            decision: Decision(decision: "alert", calibrated_confidence: 0.96,
                               reason: "conformal_pass", alert_threshold: 0.23, snr_db: 34.2))
    }

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

    @Published var probeMessage: String?
    @Published var probeStatusByRoom: [String: String] = [:]
    @Published var probeRT60ByRoom: [String: Double] = [:]

    func probe(roomName: String) async {
        busy = true
        defer { busy = false }
        let id = roomName.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "-")
        do {
            let recorder = ProbeRecorder()
            let clip = try await recorder.measure()
            let resp = try await client.probeEnroll(roomID: id, roomName: roomName, clip: clip)
            let rt = resp.probe?.room?.rt60_mid_s ?? resp.probe?.analyses?.first?.rt60_mid_s
            if let rt { probeRT60ByRoom[roomName] = rt }
            probeMessage = rt.map { String(format: "Room measured: RT60 %.2f s — acoustic fingerprint stored", $0) }
                ?? "Probe uploaded"
            session = try await client.session()
        } catch { errorText = error.localizedDescription }
    }

    func probeCheck(roomName: String) async {
        busy = true
        defer { busy = false }
        let id = roomName.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "-")
        do {
            let recorder = ProbeRecorder()
            let clip = try await recorder.measure()
            let resp = try await client.probeCheck(roomID: id, clip: clip)
            let status = resp.status ?? (resp.change_detected == true ? "changed" : "stable")
            let delta = resp.max_t30_change_pct ?? 0
            let conf = Int((resp.confidence ?? 0) * 100)
            var text: String
            switch status {
            case "changed": text = String(format: "Room changed — ΔT30 max %.0f%% (conf %d%%)", delta, conf)
            case "drift": text = String(format: "Room drifting — ΔT30 max %.0f%% (conf %d%%)", delta, conf)
            default: text = String(format: "Room stable — ΔT30 max %.0f%% (conf %d%%)", delta, conf)
            }
            if resp.unusual_activity == true {
                text += String(format: " · unusual activity (%.0f%%)", (resp.activity_score ?? 0) * 100)
            }
            probeMessage = text
            probeStatusByRoom[roomName] = text
        } catch { errorText = error.localizedDescription }
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

import Foundation

struct SessionSummary: Codable {
    var rooms: [RoomSummary]?
    var templates: [String: Int]?
    var events: [RecentEvent]?
}

struct RoomSummary: Codable, Identifiable {
    var id: String
    var name: String
    var examples: Int?
}

struct RecentEvent: Codable, Identifiable {
    var id: String { "\(label ?? "")|\(room ?? "")|\(confidence ?? 0)" }
    var label: String?
    var room: String?
    var confidence: Double?
}

struct EventInfo: Codable {
    var label: String
    var confidence: Double
    var snr_db: Double?
    var reason: String?
    var ranking: [EventRank]?
}

struct EventRank: Codable {
    var label: String
    var score: Double
}

struct RoomMatch: Codable {
    var room_id: String?
    var room_name: String?
    var confidence: Double
    var uncertain: Bool?
    var reason: String?
    var snr_db: Double?
    var ranking: [RoomRank]?
}

struct RoomRank: Codable {
    var room: String
    var distance: Double
}

struct Situation: Codable {
    var urgency: String?
    var headline: String?
    var explanation: String?
    var suggested_action: String?
    var false_alarm_check: String?
    var _model: String?
}

struct DetectResponse: Codable {
    var event: EventInfo
    var room: RoomMatch
    var situation: Situation
    var certainty: Double?
    var heard: [SoundLabel]?
}

struct EnrollResponse: Codable {
    var room: RoomSummary?
    var session: SessionSummary?
}

struct TeachResponse: Codable {
    var label: String?
    var examples: Int?
    var session: SessionSummary?
}

enum EventLabels {
    static let all = ["knock", "glass_impact", "impact_thud", "baby_cry",
                      "speech", "alarm_beep", "water"]
    static func pretty(_ raw: String) -> String {
        raw.replacingOccurrences(of: "_", with: " ").capitalized
    }
}

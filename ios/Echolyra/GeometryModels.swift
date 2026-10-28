import Foundation

struct GeometryObject: Codable, Identifiable {
    var id: String
    var distance_m: Double
    var delay_ms: Double
    var strength: Double
    var confidence: String
    var note: String
    var support: Int
}

struct StagingObject: Codable, Identifiable {
    var kind: String
    var x: Double
    var z: Double
    var w: Double
    var d: Double
    var h: Double
    var color: String
    var id: String { "\(kind)-\(x)-\(z)-\(w)" }
}

struct GeometryStaging: Codable {
    var available: Bool
    var source: String
    var model: String?
    var training_use: Bool
    var style: String
    var palette: [String]
    var objects: [StagingObject]
    var note: String

    var isIllustrative: Bool { available && !objects.isEmpty }
}

struct GeometryResult: Codable {
    var status: String
    var message: String
    var source: String
    var assumptions: [String]
    var candidates: [GeometryCandidate]
    var echoes: [GeometryEcho]
    var diagnostics: GeometryDiagnostics
    var objects: [GeometryObject]?
    var confidence: String?

    var isSynthetic: Bool { source == "synthetic_demo" }
}


struct ScanPose: Codable {
    var x: Double
    var y: Double
    var yaw: Double
}

struct ReflectionPoint: Codable, Identifiable {
    var id: String
    var x: Double
    var y: Double
    var distance_from_start_m: Double
    var support: Int
    var poses: Int
    var score: Double
    var type: String
    var note: String
}

struct ReflectionDiagnostics: Codable {
    var recordings: Int?
    var usable_poses: Int?
    var support_needed: Int?
    var grid_step_m: Double?
    var assumed_spacing_m: Double?
}

struct ReflectionScan: Codable {
    var status: String
    var message: String
    var assumptions: [String]
    var poses: [ScanPose]
    var reflectors: [ReflectionPoint]
    var diagnostics: ReflectionDiagnostics
}

struct GeometryCandidate: Codable, Identifiable {
    var id: String
    var dimensions_m: [Double]
    var sensor_position_m: [Double]
    var fit_error_ms: Double
    var matched_echoes: Int
    var total_predicted_echoes: Int
    var support_fraction: Double
    var vertices: [[Double]]
    var faces: [[Int]]
    var confidence: String?
    var tier: String?

    var hasValidScene: Bool {
        dimensions_m.count == 3 && sensor_position_m.count == 3 &&
        dimensions_m.allSatisfy { $0.isFinite && $0 > 0 && $0 < 100 } &&
        zip(sensor_position_m, dimensions_m).allSatisfy { $0.0.isFinite && $0.0 >= 0 && $0.0 <= $0.1 }
    }
}

struct GeometryEcho: Codable {
    var delay_ms: Double
    var strength: Double
}

struct GeometryDiagnostics: Codable {
    var recordings: Int
    var repeatable_echoes: Int
}

struct GeometryReview: Codable {
    var available: Bool
    var model: String?
    var text: String
    var training_use: Bool
}

extension APIClient {
    func reconstructGeometry(clips: [Data]) async throws -> GeometryResult {
        var upload = URLRequest(url: baseURL.appendingPathComponent("api/geometry/reconstruct"))
        upload.httpMethod = "POST"
        upload.timeoutInterval = 120
        upload.setValue("multipart/form-data; boundary=\(Self.boundary)", forHTTPHeaderField: "Content-Type")
        upload.httpBody = Self.multipart(fields: [:], files: clips.enumerated().map {
            (name: "audio", filename: "geometry\($0.offset).wav", mime: "audio/wav", data: $0.element)
        })
        let (data, response) = try await URLSession.shared.data(for: upload)
        try Self.check(response, data)
        return try JSONDecoder().decode(GeometryResult.self, from: data)
    }

    func scanGeometry(clips: [Data], poses: [ScanPose]) async throws -> ReflectionScan {
        let encoded = try JSONEncoder().encode(poses)
        let posesJSON = String(data: encoded, encoding: .utf8) ?? "[]"
        let body = Self.multipart(
            fields: ["poses": posesJSON],
            files: clips.enumerated().map { (name: "audio", filename: "walk\($0.offset).wav",
                                              mime: "audio/wav", data: $0.element) }
        )
        var upload = URLRequest(url: baseURL.appendingPathComponent("api/geometry/scan"))
        upload.httpMethod = "POST"
        upload.timeoutInterval = 120
        upload.setValue("multipart/form-data; boundary=\(Self.boundary)", forHTTPHeaderField: "Content-Type")
        upload.httpBody = body
        let (data, response) = try await URLSession.shared.data(for: upload)
        try Self.check(response, data)
        return try JSONDecoder().decode(ReflectionScan.self, from: data)
    }

    func geometryDemo() async throws -> GeometryResult {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/geometry/demo"))
        request.timeoutInterval = 120
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.check(response, data)
        return try JSONDecoder().decode(GeometryResult.self, from: data)
    }

    func stageGeometry(_ result: GeometryResult) async throws -> GeometryStaging {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/geometry/stage"))
        request.httpMethod = "POST"
        request.timeoutInterval = 45
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(result)
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.check(response, data)
        return try JSONDecoder().decode(GeometryStaging.self, from: data)
    }

    func reviewGeometry(_ result: GeometryResult) async throws -> GeometryReview {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/geometry/review"))
        request.httpMethod = "POST"
        request.timeoutInterval = 45
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(result)
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.check(response, data)
        return try JSONDecoder().decode(GeometryReview.self, from: data)
    }
}

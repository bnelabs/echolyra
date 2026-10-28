import Foundation

struct GeometryResult: Codable {
    var status: String
    var message: String
    var source: String
    var assumptions: [String]
    var candidates: [GeometryCandidate]
    var echoes: [GeometryEcho]
    var diagnostics: GeometryDiagnostics

    var isSynthetic: Bool { source == "synthetic_demo" }
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

    func geometryDemo() async throws -> GeometryResult {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/geometry/demo"))
        request.timeoutInterval = 120
        let (data, response) = try await URLSession.shared.data(for: request)
        try Self.check(response, data)
        return try JSONDecoder().decode(GeometryResult.self, from: data)
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

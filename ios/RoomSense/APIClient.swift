import Foundation

enum APIError: LocalizedError {
    case badURL
    case http(Int, String)
    case decode(String)

    var errorDescription: String? {
        switch self {
        case .badURL: return "Bad backend URL."
        case let .http(code, body): return "HTTP \(code): \(body.prefix(200))"
        case let .decode(message): return "Could not read the response: \(message)"
        }
    }
}

struct APIClient {
    var baseURL: URL

    private func request(_ path: String, method: String = "GET") -> URLRequest {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.timeoutInterval = 120
        return request
    }

    func session() async throws -> SessionSummary {
        let (data, response) = try await URLSession.shared.data(for: request("api/session"))
        try Self.check(response, data)
        return try JSONDecoder().decode(SessionSummary.self, from: data)
    }

    func reset() async throws {
        let (data, response) = try await URLSession.shared.data(for: request("api/reset", method: "POST"))
        try Self.check(response, data)
    }

    func enroll(roomID: String, roomName: String, clip: Data) async throws -> SessionSummary? {
        let body = Self.multipart(
            fields: ["room_id": roomID, "room_name": roomName],
            files: [(name: "audio", filename: "knock.caf", mime: "audio/x-caf", data: clip)]
        )
        var upload = request("api/enroll", method: "POST")
        upload.setValue("multipart/form-data; boundary=\(Self.boundary)", forHTTPHeaderField: "Content-Type")
        upload.httpBody = body
        let (data, response) = try await URLSession.shared.data(for: upload)
        try Self.check(response, data)
        return try JSONDecoder().decode(EnrollResponse.self, from: data).session
    }

    func detect(clip: Data) async throws -> DetectResponse {
        let body = Self.multipart(
            fields: [:],
            files: [(name: "audio", filename: "event.caf", mime: "audio/x-caf", data: clip)]
        )
        var upload = request("api/detect", method: "POST")
        upload.setValue("multipart/form-data; boundary=\(Self.boundary)", forHTTPHeaderField: "Content-Type")
        upload.httpBody = body
        let (data, response) = try await URLSession.shared.data(for: upload)
        try Self.check(response, data)
        do {
            return try JSONDecoder().decode(DetectResponse.self, from: data)
        } catch {
            throw APIError.decode(error.localizedDescription)
        }
    }

    func teach(label: String, clip: Data) async throws -> SessionSummary? {
        let body = Self.multipart(
            fields: ["label": label],
            files: [(name: "audio", filename: "teach.caf", mime: "audio/x-caf", data: clip)]
        )
        var upload = request("api/teach", method: "POST")
        upload.setValue("multipart/form-data; boundary=\(Self.boundary)", forHTTPHeaderField: "Content-Type")
        upload.httpBody = body
        let (data, response) = try await URLSession.shared.data(for: upload)
        try Self.check(response, data)
        return try JSONDecoder().decode(TeachResponse.self, from: data).session
    }

    // MARK: - Helpers

    static let boundary = "RoomSense-\(UUID().uuidString)"

    static func check(_ response: URLResponse, _ data: Data) throws {
        guard let http = response as? HTTPURLResponse else { throw APIError.badURL }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.http(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
    }

    static func multipart(fields: [String: String],
                          files: [(name: String, filename: String, mime: String, data: Data)]) -> Data {
        var body = Data()
        func append(_ string: String) {
            if let data = string.data(using: .utf8) { body.append(data) }
        }
        for (name, value) in fields {
            append("--\(boundary)\r\n")
            append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
            append("\(value)\r\n")
        }
        for file in files {
            append("--\(boundary)\r\n")
            append("Content-Disposition: form-data; name=\"\(file.name)\"; filename=\"\(file.filename)\"\r\n")
            append("Content-Type: \(file.mime)\r\n\r\n")
            body.append(file.data)
            append("\r\n")
        }
        append("--\(boundary)--\r\n")
        return body
    }
}

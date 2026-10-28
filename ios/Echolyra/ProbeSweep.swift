import Foundation

/// Must match backend probe.probe_sweep(): 250 Hz–16 kHz log sweep, 3 s, 48 kHz.
enum ProbeSweep {
    static let sampleRate: Double = 48_000
    static let duration: Double = 3.0
    static let f1: Double = 250
    static let f2: Double = 16_000

    static func samples() -> [Float] {
        let n = Int(duration * sampleRate)
        let k = log(f2 / f1) / duration
        var out = [Float](repeating: 0, count: n)
        for i in 0..<n {
            let t = Double(i) / sampleRate
            out[i] = Float(sin(2 * .pi * f1 * (exp(k * t) - 1) / k)) * 0.7
        }
        return out
    }
}

enum WAVWriter {
    static func mono16(_ samples: [Float], sampleRate: Double) -> Data {
        var data = Data()
        let n = samples.count
        func u32(_ v: UInt32) { var x = v.littleEndian; withUnsafeBytes(of: &x) { data.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { var x = v.littleEndian; withUnsafeBytes(of: &x) { data.append(contentsOf: $0) } }
        data.append(contentsOf: Array("RIFF".utf8)); u32(UInt32(36 + n * 2))
        data.append(contentsOf: Array("WAVEfmt ".utf8)); u32(16); u16(1); u16(1)
        u32(UInt32(sampleRate)); u32(UInt32(sampleRate) * 2); u16(2); u16(16)
        data.append(contentsOf: Array("data".utf8)); u32(UInt32(n * 2))
        for s in samples {
            u16(UInt16(bitPattern: Int16(max(-1, min(1, s)) * 32767)))
        }
        return data
    }
}

import Foundation
import SoundAnalysis

struct SoundLabel: Codable, Identifiable {
    var id: String { label }
    var label: String
    var confidence: Double
}

/// On-device sound understanding using Apple's SoundAnalysis classifier (303 classes:
/// knock, glass_breaking, baby_crying, speech, door_slam, alarm_clock, water, ...).
/// Runs fully on the phone — no audio leaves the device for this step.
final class SoundUnderstanding {
    static func classify(fileURL: URL, maxResults: Int = 6) async -> [SoundLabel] {
        final class Collector: NSObject, SNResultsObserving, @unchecked Sendable {
            var best: [String: Double] = [:]
            func request(_ request: SNRequest, didProduce result: SNResult) {
                guard let r = result as? SNClassificationResult else { return }
                for c in r.classifications where c.confidence > (best[c.identifier] ?? 0) {
                    best[c.identifier] = c.confidence
                }
            }
            func request(_ request: SNRequest, didFailWithError error: Error) {}
            func requestDidComplete(_ request: SNRequest) {}
        }
        return await withCheckedContinuation { (continuation: CheckedContinuation<[SoundLabel], Never>) in
            do {
                let analyzer = try SNAudioFileAnalyzer(url: fileURL)
                let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
                let collector = Collector()
                try analyzer.add(request, withObserver: collector)
                analyzer.analyze { _ in
                    let top = collector.best.sorted { $0.value > $1.value }.prefix(maxResults)
                    continuation.resume(returning: top.map { SoundLabel(label: $0.key, confidence: $0.value) })
                }
            } catch {
                continuation.resume(returning: [])
            }
        }
    }
}

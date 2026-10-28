import SwiftUI
import SceneKit
import simd
import Darwin
import CoreMotion

struct GeometryView: View {
    @EnvironmentObject private var model: AppModel
    @State private var result: GeometryResult?
    @State private var selectedCandidate = ""
    @State private var sceneAngle = 0.0
    @State private var sceneZoom = 1.0
    @State private var progress = ""
    @State private var review: GeometryReview?
    @State private var staging: GeometryStaging?
    @State private var scan: ReflectionScan?
    @State private var walkProgress = ""
    @State private var reviewConsent = false
    @State private var stagingConsent = false
    @State private var work: Task<Void, Never>?

    private var candidate: GeometryCandidate? {
        guard let result, result.status != "insufficient_evidence" else { return nil }
        return result.candidates.first(where: { $0.id == selectedCandidate }) ?? result.candidates.first
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
#if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("-geometryWalkSample"), let scan {
                        reflectionCard(scan)
                    }
#endif
                    if result == nil {
                        intro
                        captureActions
                    }
                    if !progress.isEmpty {
                        HStack { ProgressView(); Text(progress).font(.subheadline) }
                            .accessibilityElement(children: .combine)
                    }
                    if let result {
                        resultHeader(result)
                        if let candidate, candidate.hasValidScene {
                            sceneCard(candidate, result: result)
                        }
                        if result.status != "insufficient_evidence" {
                            acousticObjectsCard(result)
                            stagingCard
                            Button { stagingConsent = true } label: {
                                Label("Generate illustrative scene", systemImage: "wand.and.stars")
                            }
                            .buttonStyle(.bordered)
                            .disabled(model.busy || result.candidates.isEmpty)
                        }
                        captureActions
                        Button { reviewConsent = true } label: {
                            Label("Ask Meta to review", systemImage: "sparkles")
                        }
                        .buttonStyle(.bordered).disabled(model.busy)
                        if let review { reviewCard(review) }
                        assumptions(result)
                    } else {
                        ContentUnavailableView("Start with the echoes", systemImage: "waveform.path",
                            description: Text("Measure a stationary phone’s probe echoes, or explore the synthetic example. The room appears here when the recordings support an estimate."))
                    }
                    walkScanSection
                    if let scan { reflectionCard(scan) }
                }
                .padding()
            }
            .navigationTitle("3D Room")
            .task {
#if DEBUG
                let env = ProcessInfo.processInfo.environment
                if (ProcessInfo.processInfo.arguments.contains("-geometryDemo")
                    || env["ECHOLYRA_GEOMETRY_DEMO"] == "1"), result == nil {
                    await loadDemo()
                }
                if (ProcessInfo.processInfo.arguments.contains("-geometryStage")
                    || env["ECHOLYRA_GEOMETRY_STAGE"] == "1"), staging == nil {
                    await askStage()
                }
                if ProcessInfo.processInfo.arguments.contains("-geometryWalkSample"), scan == nil {
                    scan = sampleScan()
                }
#endif
            }
            .onDisappear { work?.cancel() }
            .confirmationDialog("Send numeric measurements to Meta?", isPresented: $reviewConsent,
                                titleVisibility: .visible) {
                Button("Send geometry and echo timings") {
                    work = Task { await askMeta() }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This sends the estimated layout, echo timings and measurement details to Meta. No recording is sent to Meta. If your backend uses Contributor mode, Meta may use this content for training. The review cannot verify the room’s true shape.")
            }
            .confirmationDialog("Generate an illustrative scene from numeric estimates?", isPresented: $stagingConsent,
                                titleVisibility: .visible) {
                Button("Send room estimates to Meta") {
                    work = Task { await askStage() }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Sends the estimated dimensions and distance-only echo candidates to Meta to compose a styled visualisation. No audio and no room name are sent. If the backend uses Contributor mode, Meta may use this content for training. These objects are an illustration and are not measured furniture.")
            }
        }
    }

    private var intro: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Experimental · sound only", systemImage: "waveform")
                .font(.subheadline.weight(.semibold)).foregroundStyle(.orange)
            Text("Hear the room’s shape").font(.title2.weight(.bold))
            Text("Echo timings can suggest a rectangular shell. Strong echoes the shell can’t explain appear as distance-only object candidates. Styled furniture is an illustrative composition, not measured, and the room’s orientation is unknown.")
                .font(.subheadline).foregroundStyle(.secondary)
        }
    }

    private var captureActions: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Keep the phone still in a quiet room, away from walls and soft surfaces. Keep the speaker and microphone clear. Three audible sweeps take about 15 seconds.")
                .font(.subheadline)
            Button {
                work = Task { await measure() }
            } label: {
                Label("Measure with 3 sweeps", systemImage: "mic.fill")
                    .frame(maxWidth: .infinity).padding(.vertical, 6)
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.busy)
            Button {
                work = Task { await loadDemo() }
            } label: {
                Label("Explore synthetic example", systemImage: "cube.transparent")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(model.busy)
            Text("Recordings go to your configured backend for noise filtering and reconstruction — the heavy computation runs there, not on the phone. No cloud call happens unless you choose Ask Meta or Generate illustrative scene.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding().background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func resultHeader(_ result: GeometryResult) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if result.isSynthetic {
                Label("Synthetic demonstration", systemImage: "testtube.2")
                    .font(.headline).foregroundStyle(.orange)
                Text("Reconstructed from simulated audio. This is not your room.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Label(statusTitle(result.status), systemImage: result.status == "insufficient_evidence" ? "questionmark.diamond" : "cube")
                .font(.headline)
            if result.confidence == "low" || candidate?.confidence == "low" {
                Label("Low-confidence estimate — verify the dimensions before trusting them",
                      systemImage: "exclamationmark.triangle.fill")
                    .font(.subheadline.weight(.semibold)).foregroundStyle(.orange)
            }
            Text(result.message).font(.subheadline)
            if result.status == "insufficient_evidence" {
                Text("Try another recording in a quieter room, with the phone away from soft surfaces. Keep it still for all three sweeps. Some rooms may not produce clear enough echoes to map.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
            Text("\(result.diagnostics.recordings) recordings · \(result.diagnostics.repeatable_echoes) consistent echoes")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private func sceneCard(_ candidate: GeometryCandidate, result: GeometryResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if result.candidates.count > 1 {
                Picker("Estimated layout", selection: $selectedCandidate) {
                    ForEach(Array(result.candidates.enumerated()), id: \.element.id) { index, option in
                        Text("Layout \(index + 1)").tag(option.id)
                    }
                }
                .pickerStyle(.segmented)
                .onChange(of: selectedCandidate) { _, _ in resetCamera() }
                Text("More than one layout fits. Try another recording to narrow it down.")
                    .font(.caption).foregroundStyle(.orange)
            }
            HStack(spacing: 8) {
                if candidate.confidence == "low" {
                    Label("Low-confidence shell", systemImage: "exclamationmark.triangle")
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Color.orange.opacity(0.18), in: Capsule())
                } else {
                    Label("Measured shell", systemImage: "ruler")
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Color.cyan.opacity(0.14), in: Capsule())
                }
                if staging?.isIllustrative == true {
                    Label("Illustrative staging · not measured", systemImage: "paintpalette")
                        .font(.caption2.weight(.semibold))
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(Color.orange.opacity(0.16), in: Capsule())
                }
                Spacer(minLength: 0)
            }
            AcousticRoomScene(candidate: candidate, objects: sceneObjects(for: result),
                              staging: staging, angle: sceneAngle, zoom: sceneZoom)
                .frame(height: 420)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .accessibilityLabel("Estimated rectangular room, axes \(dimensionDescription(candidate)) metres")
                .accessibilityHint("Use the controls below to rotate and zoom the room.")
            cameraControls
            Text("Marker = estimated phone position · cyan rings = distance-only echo candidates · styled objects = illustrative only")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                ForEach(0..<3) { axis in
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Axis \(["A", "B", "C"][axis])").font(.caption).foregroundStyle(.secondary)
                        Text(String(format: "≈ %.2f m", candidate.dimensions_m[axis])).font(.headline)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            Text("Cutaway orientation and finishes are illustrative. Styled objects are a generated illustration, not measured furniture. The acoustic shell itself is the only measured geometry.")
                .font(.caption).foregroundStyle(.secondary)
            if candidate.confidence == "low" {
                Text("Low-confidence experimental fit · support \(Int(candidate.support_fraction * 100))% · \(candidate.matched_echoes)/\(candidate.total_predicted_echoes) echoes matched. Verify with a tape measure.")
                    .font(.caption).foregroundStyle(.orange)
            } else {
                Text(String(format: "Echo fit error %.3f ms · %d/%d predicted echoes matched", candidate.fit_error_ms,
                            candidate.matched_echoes, candidate.total_predicted_echoes))
                    .font(.caption.monospacedDigit())
            }
            Text("Echo match quality measures how well this layout explains the recording. It does not confirm the room’s actual dimensions.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding().background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func sceneObjects(for result: GeometryResult) -> [GeometryObject] {
#if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-geometryStageSample") {
            return [GeometryObject(id: "object-1", distance_m: 1.3, delay_ms: 7.6, strength: 0.52,
                                   confidence: "medium",
                                   note: "Reflective-surface echo at this distance.", support: 2),
                    GeometryObject(id: "object-2", distance_m: 2.6, delay_ms: 15.2, strength: 0.31,
                                   confidence: "low",
                                   note: "Reflective-surface echo at this distance.", support: 1)]
        }
#endif
        return result.objects ?? []
    }

    private func acousticObjectsCard(_ result: GeometryResult) -> some View {
        let objects = result.objects ?? []
        return Group {
            if !objects.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Label("Acoustic object candidates · distance only", systemImage: "dot.radiowaves.left.and.right")
                        .font(.headline)
                    ForEach(objects.prefix(5)) { object in
                        HStack {
                            Text(object.id.uppercased()).font(.caption.monospaced())
                            Spacer()
                            Text(String(format: "≈ %.1f m", object.distance_m)).font(.subheadline.weight(.semibold))
                            Text("\(object.confidence) · strength \(Int(object.strength * 100))%")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    Text("Unexplained reflective echoes at these distances. A single-position recording cannot tell direction, identity, size or shape — these are not mapped objects.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .padding().background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
            }
        }
    }

    private var stagingCard: some View {
        Group {
            if let staging {
                VStack(alignment: .leading, spacing: 8) {
                    Label(staging.isIllustrative ? "Illustrative scene" : "Illustrative scene unavailable",
                          systemImage: "paintpalette")
                        .font(.headline)
                    if staging.isIllustrative {
                        Text("Style: \(staging.style) · \(staging.objects.count) staged objects").font(.subheadline)
                    }
                    Text(staging.note).font(.caption).foregroundStyle(.secondary)
                    if let name = staging.model {
                        Text("Generated with \(name)" + (staging.training_use ? " · Contributor mode (may be used for training)" : ""))
                            .font(.caption2).foregroundStyle(staging.training_use ? .orange : .secondary)
                    }
                }
                .padding().background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
            }
        }
    }

    private var cameraControls: some View {
        HStack(spacing: 12) {
            Spacer(minLength: 0)
            Button { sceneAngle -= .pi / 8 } label: {
                Image(systemName: "rotate.left").frame(width: 34, height: 32)
            }
            .accessibilityLabel("Rotate room left")
            .accessibilityIdentifier("geometryRotateLeft")
            Button { sceneAngle += .pi / 8 } label: {
                Image(systemName: "rotate.right").frame(width: 34, height: 32)
            }
            .accessibilityLabel("Rotate room right")
            .accessibilityIdentifier("geometryRotateRight")
            Button { sceneZoom = max(0.45, sceneZoom * 0.8) } label: {
                Image(systemName: "plus.magnifyingglass").frame(width: 34, height: 32)
            }
            .disabled(sceneZoom <= 0.45)
            .accessibilityLabel("Zoom room in")
            .accessibilityIdentifier("geometryZoomIn")
            Button { sceneZoom = min(1.8, sceneZoom / 0.8) } label: {
                Image(systemName: "minus.magnifyingglass").frame(width: 34, height: 32)
            }
            .disabled(sceneZoom >= 1.8)
            .accessibilityLabel("Zoom room out")
            .accessibilityIdentifier("geometryZoomOut")
            Spacer(minLength: 0)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
    }

    private func resetCamera() {
        sceneAngle = 0
        sceneZoom = 1
    }

    private func reviewCard(_ review: GeometryReview) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(review.available ? "Meta’s interpretation" : "Meta review unavailable", systemImage: "text.bubble")
                .font(.headline)
            Text(review.text).font(.subheadline)
            if let name = review.model { Text(name).font(.caption).foregroundStyle(.secondary) }
            Text("Meta’s interpretation does not change the estimated layout or confirm the room’s dimensions.")
                .font(.caption).foregroundStyle(.secondary)
            if review.training_use {
                Text("Contributor mode: submitted numeric context may be used for training.")
                    .font(.caption).foregroundStyle(.orange)
            }
        }.padding().background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func assumptions(_ result: GeometryResult) -> some View {
        DisclosureGroup("How this estimate works") {
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(result.assumptions.enumerated()), id: \.offset) { _, text in
                    Text(text).font(.caption).frame(maxWidth: .infinity, alignment: .leading)
                }
            }.padding(.top, 8)
        }
    }

    private func statusTitle(_ status: String) -> String {
        switch status {
        case "candidate": return "Estimated room layout"
        case "ambiguous": return "More than one layout fits"
        default: return "Couldn’t map this room yet"
        }
    }

    private func dimensionDescription(_ candidate: GeometryCandidate) -> String {
        candidate.dimensions_m.map { String(format: "%.2f", $0) }.joined(separator: ", ")
    }

    private var walkScanSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Walk scan · reflections from objects", systemImage: "figure.walk")
                .font(.headline)
            Text("Five sweeps, four walking segments: start → step right → step forward → step right → walk back to the start. Point the top of the phone in the direction you walk; the phone measures step distance and heading, then closes the loop to correct drift. Turning in place is rejected.")
                .font(.subheadline)
            Button { work = Task { await walkScan() } } label: {
                Label("Start walk scan (4 sweeps)", systemImage: "waveform.path.ecg")
                    .frame(maxWidth: .infinity).padding(.vertical, 6)
            }
            .buttonStyle(.bordered)
            .disabled(model.busy)
            if !walkProgress.isEmpty {
                HStack { ProgressView(); Text(walkProgress).font(.subheadline) }
            }
            Text("Reflections from furniture, walls and people are localized as candidates — not identified objects. The last stop must be back at the start for loop closure. Walk slowly; keep the phone at the same height.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding().background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    private func reflectionCard(_ scan: ReflectionScan) -> some View {
        let persistent = scan.reflectors.filter { $0.type == "persistent" }.count
        let unstable = scan.reflectors.count - persistent
        return VStack(alignment: .leading, spacing: 10) {
            Label("Acoustic reflection map · experimental", systemImage: "dot.radiowaves.left.and.right")
                .font(.headline)
            Text(scan.message).font(.subheadline)
            ReflectionScene(scan: scan).frame(height: 340)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .accessibilityLabel("Reflection candidates in a top-down 3D view")
            Text("\(persistent) persistent reflection candidates · \(unstable) unstable (possible movement/occlusion)")
                .font(.caption).foregroundStyle(.secondary)
            if let loop = scan.trajectory?.diagnostics,
               let raw = loop.raw_loop_error_m, let adjusted = loop.adjusted_loop_error_m {
                Text(String(format: "Walk trajectory loop error: %.2f m → %.2f m after pose-graph adjustment", raw, adjusted))
                    .font(.caption).foregroundStyle(.secondary)
            }
            ForEach(scan.reflectors.prefix(5)) { point in
                HStack {
                    Text(point.type == "persistent" ? "Persistent" : "Unstable")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(point.type == "persistent" ? .cyan : .orange)
                    Spacer()
                    Text(String(format: "≈ %.1f m from start · %d/%d poses", point.distance_from_start_m,
                                point.support, point.poses))
                        .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
            }
            Text("These are reflective surfaces, not identified furniture or people. A person walking through during the scan usually appears as an unstable or missing candidate; repeat the walk to distinguish persistent objects from movement.")
                .font(.caption).foregroundStyle(.secondary)
            DisclosureGroup("Scan assumptions") {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(scan.assumptions.enumerated()), id: \.offset) { _, text in
                        Text(text).font(.caption).frame(maxWidth: .infinity, alignment: .leading)
                    }
                }.padding(.top, 6)
            }
        }
        .padding().background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }

    @MainActor private func walkScan() async {
        guard !model.busy else { return }
        guard CMPedometer.isStepCountingAvailable() else {
            model.errorText = "This device does not expose step counting; walk scan needs step distance."
            return
        }
        let motion = CMMotionManager()
        guard motion.isDeviceMotionAvailable else {
            model.errorText = "Device motion is unavailable; walk scan needs heading tracking."
            return
        }
        model.busy = true
        scan = nil
        defer { model.busy = false; walkProgress = "" }
        motion.startDeviceMotionUpdates()
        defer { motion.stopDeviceMotionUpdates() }
        let pedometer = CMPedometer()
        let walkStart = Date()
        var previousDistance = 0.0
        var yaw0: Double?
        var segments: [TrajectorySegment] = []
        var poses = [ScanPose(x: 0, y: 0, yaw: 0)]
        let labels = ["start", "step right", "step forward", "step right", "return to start"]
        do {
            let recorder = ProbeRecorder()
            var clips: [Data] = []
            for index in 0..<5 {
                try Task.checkCancellation()
                if index == 0 {
                    try? await Task.sleep(nanoseconds: 350_000_000)
                    yaw0 = motion.deviceMotion?.attitude.yaw
                } else {
                    let total = await stepDistance(pedometer: pedometer, from: walkStart)
                    let segment = total.map { max(0, $0 - previousDistance) }
                    if let segment, segment < 0.15 {
                        throw NSError(domain: "Echolyra", code: 7, userInfo: [
                            NSLocalizedDescriptionKey: "No walking detected between sweeps. Turning the phone in your hand gives no position baseline — take 2–3 steps between each sweep and return to the start on the last one."])
                    }
                    let moved = min(max(segment ?? 0.6, 0.3), 2.5)
                    previousDistance += moved
                    var heading = 0.0
                    if let current = motion.deviceMotion?.attitude.yaw, let base = yaw0 {
                        heading = normalizeAngle(current - base)
                    }
                    segments.append(TrajectorySegment(distance_m: moved, heading_rad: heading))
                    let previous = poses[poses.count - 1]
                    poses.append(ScanPose(x: previous.x + moved * cos(heading),
                                          y: previous.y + moved * sin(heading), yaw: 0))
                }
                walkProgress = "Spot \(index + 1) of 5 · \(labels[index]) — hold still…"
                clips.append(try await recorder.measure())
            }
            try Task.checkCancellation()
            let trajectory = segments.count == 4 ? WalkTrajectory(segments: segments, loop: true) : nil
            walkProgress = "Adjusting the walk trajectory (loop closure) and localizing reflections…"
            scan = try await model.client.scanGeometry(clips: clips, poses: poses, trajectory: trajectory)
#if DEBUG
            print("ECHOLYRA_WALK status=\(scan?.status ?? "nil") reflectors=\(scan?.reflectors.count ?? -1) loop=\(scan?.trajectory?.diagnostics?.raw_loop_error_m ?? 0)->\(scan?.trajectory?.diagnostics?.adjusted_loop_error_m ?? 0)")
            fflush(stdout)
#endif
        } catch is CancellationError {
        } catch { if !Task.isCancelled { model.errorText = error.localizedDescription } }
    }

    private func normalizeAngle(_ value: Double) -> Double {
        var angle = value
        while angle > .pi { angle -= 2 * .pi }
        while angle < -.pi { angle += 2 * .pi }
        return angle
    }

    private func stepDistance(pedometer: CMPedometer, from start: Date) async -> Double? {
        guard CMPedometer.isStepCountingAvailable() else { return nil }
        return await withCheckedContinuation { continuation in
            pedometer.queryPedometerData(from: start, to: Date()) { data, _ in
                continuation.resume(returning: data?.distance?.doubleValue)
            }
        }
    }

    @MainActor private func measure() async {
        guard !model.busy else { return }
        model.busy = true
        result = nil; review = nil; staging = nil
        defer { model.busy = false; progress = "" }
        do {
            let recorder = ProbeRecorder()
            var clips: [Data] = []
            for step in 1...3 {
                try Task.checkCancellation()
                progress = "Sweep \(step) of 3 — keep the phone still…"
                clips.append(try await recorder.measure())
            }
            try Task.checkCancellation()
            progress = "Comparing echoes and estimating the layout…"
            let received = try await model.client.reconstructGeometry(clips: clips)
            try Task.checkCancellation()
            result = received
            selectedCandidate = received.candidates.first?.id ?? ""
            resetCamera()
            if ProcessInfo.processInfo.arguments.contains("-geometryStage") {
                await askStage()
            }
        } catch is CancellationError {
            // Navigating away cancels capture; ProbeRecorder releases audio resources.
        } catch { if !Task.isCancelled { model.errorText = error.localizedDescription } }
    }

    @MainActor private func loadDemo() async {
        guard !model.busy else { return }
        model.busy = true
        result = nil; review = nil; staging = nil
        progress = "Reconstructing simulated probe recordings…"
        defer { model.busy = false; progress = "" }
        do {
            let received = try await model.client.geometryDemo()
            try Task.checkCancellation()
            result = received
            selectedCandidate = received.candidates.first?.id ?? ""
            resetCamera()
#if DEBUG
            print("ECHOLYRA_GEOM demo status=\(received.status) candidates=\(received.candidates.count) objects=\(received.objects?.count ?? 0)")
            fflush(stdout)
#endif
            if ProcessInfo.processInfo.arguments.contains("-geometryStageSample") {
                staging = sampleStaging()
            }
        } catch is CancellationError {} catch { if !Task.isCancelled { model.errorText = error.localizedDescription } }
    }

#if DEBUG
    private func sampleScan() -> ReflectionScan {
        let poses = [ScanPose(x: 0, y: 0, yaw: 0), ScanPose(x: 0.6, y: 0, yaw: 0),
                     ScanPose(x: 0.6, y: 0.6, yaw: 0), ScanPose(x: 1.2, y: 0.6, yaw: 0)]
        let reflectors = [
            ReflectionPoint(id: "reflector-1", x: 2.12, y: 1.08, distance_from_start_m: 2.38,
                            support: 4, poses: 4, score: 2.4, type: "persistent",
                            note: "Acoustic reflection candidate; not an identified object."),
            ReflectionPoint(id: "reflector-2", x: 3.52, y: 2.48, distance_from_start_m: 4.31,
                            support: 4, poses: 4, score: 2.2, type: "persistent",
                            note: "Acoustic reflection candidate; not an identified object."),
            ReflectionPoint(id: "reflector-3", x: 1.48, y: 2.72, distance_from_start_m: 3.10,
                            support: 4, poses: 4, score: 2.0, type: "persistent",
                            note: "Acoustic reflection candidate; not an identified object."),
            ReflectionPoint(id: "reflector-4", x: 0.9, y: 2.1, distance_from_start_m: 2.28,
                            support: 3, poses: 4, score: 1.6, type: "unstable",
                            note: "Possible movement/occlusion; unstable candidate."),
        ]
        return ReflectionScan(status: "reflectors",
                              message: "Reflection candidates localized. These are surfaces that reflected the probe, not identified furniture; moving things can appear as unstable candidates.",
                              assumptions: ["Phone moved along an approximate L-path with 0.6 m hand spacing (user instruction; not measured).",
                                            "Reflectors are localized on a 2D horizontal plane; true height and identity are unknown."],
                              poses: poses, reflectors: reflectors,
                              diagnostics: ReflectionDiagnostics(recordings: 4, usable_poses: 4,
                                                                 support_needed: 3, grid_step_m: 0.08,
                                                                 assumed_spacing_m: 0.6))
    }

    private func sampleStaging() -> GeometryStaging {
        GeometryStaging(available: true, source: "procedural", model: nil, training_use: false,
                        style: "Warm minimal (sample)", palette: ["#d8c3a5", "#8d7b68"],
                        objects: [
                            StagingObject(kind: "rug", x: 2.85, z: 2.15, w: 2.4, d: 1.3, h: 0.05, color: "#d8c3a5"),
                            StagingObject(kind: "sofa", x: 1.82, z: 0.86, w: 1.9, d: 0.8, h: 0.72, color: "#6b705c"),
                            StagingObject(kind: "table", x: 2.9, z: 2.2, w: 1.1, d: 0.7, h: 0.42, color: "#8d7b68"),
                            StagingObject(kind: "lamp", x: 4.9, z: 3.6, w: 0.4, d: 0.4, h: 1.5, color: "#a4907c"),
                            StagingObject(kind: "plant", x: 0.7, z: 3.5, w: 0.5, d: 0.5, h: 1.0, color: "#c8b6a6"),
                            StagingObject(kind: "shelf", x: 4.6, z: 0.7, w: 1.2, d: 0.35, h: 1.4, color: "#b7b7a4"),
                        ],
                        note: "Sample illustrative staging for screenshot; not measured.")
    }
#endif

    @MainActor private func askStage() async {
        guard let result, !model.busy else { return }
        model.busy = true
        progress = "Composing an illustrative scene from the estimates…"
        defer { model.busy = false; progress = "" }
        do {
            staging = try await model.client.stageGeometry(result)
#if DEBUG
            print("ECHOLYRA_GEOM stage source=\(staging?.source ?? "nil") objects=\(staging?.objects.count ?? -1) style=\(staging?.style ?? "nil")")
            fflush(stdout)
#endif
        }
        catch is CancellationError {} catch { if !Task.isCancelled { model.errorText = error.localizedDescription } }
    }

    @MainActor private func askMeta() async {
        guard let result, !model.busy else { return }
        model.busy = true
        progress = "Requesting a review of the measurements…"
        defer { model.busy = false; progress = "" }
        do { review = try await model.client.reviewGeometry(result) }
        catch is CancellationError {} catch { if !Task.isCancelled { model.errorText = error.localizedDescription } }
    }
}

private struct AcousticRoomScene: UIViewRepresentable {
    let candidate: GeometryCandidate
    let objects: [GeometryObject]
    let staging: GeometryStaging?
    let angle: Double
    let zoom: Double

    final class Coordinator {
        var key = ""
        var camera: SCNNode?
        var scale: Float = 1
        var focus = SCNVector3Zero
        var angle: Double?
        var zoom: Double?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.backgroundColor = UIColor(red: 0.10, green: 0.12, blue: 0.15, alpha: 1)
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = false
        view.antialiasingMode = .multisampling4X
        view.defaultCameraController.interactionMode = .orbitTurntable
        return view
    }

    func updateUIView(_ view: SCNView, context: Context) {
        let key = candidate.id + candidate.dimensions_m.description
            + candidate.sensor_position_m.description
            + (objects.map { $0.id + $0.distance_m.description }).joined()
            + (staging.map { "stage-" + $0.source + "-" + $0.objects.map(\.kind).joined() } ?? "")
        guard candidate.hasValidScene else { return }
        let coordinator = context.coordinator
        if coordinator.key != key {
            coordinator.key = key
            buildScene(view, coordinator: coordinator)
        }
        // Keep the same scene and camera across unrelated SwiftUI updates.
        guard coordinator.angle != angle || coordinator.zoom != zoom,
              let camera = coordinator.camera else { return }
        coordinator.angle = angle
        coordinator.zoom = zoom
        let azimuth = Float(angle + .pi / 4)
        let distance = coordinator.scale * Float(zoom)
        let horizontal = distance * 1.3 * sqrt(Float(2))
        SCNTransaction.begin()
        SCNTransaction.animationDuration = 0.18
        camera.position = SCNVector3(horizontal * sin(azimuth), coordinator.focus.y + distance * 0.95,
                                    horizontal * cos(azimuth))
        view.pointOfView = camera
        view.defaultCameraController.pointOfView = camera
        SCNTransaction.commit()
    }

    private func buildScene(_ view: SCNView, coordinator: Coordinator) {
        let scene = SCNScene()
        let d = candidate.dimensions_m
        let length = d[0], depth = d[1], height = d[2]
        let extent = max(d.max() ?? 5, 1)
        let thickness = extent * 0.015 // Illustrative wall/slab thickness, not measured.
        let wallMaterial = matte(UIColor(red: 0.81, green: 0.82, blue: 0.81, alpha: 1), roughness: 0.94)
        let floorMaterial = matte(UIColor(red: 0.58, green: 0.55, blue: 0.49, alpha: 1), roughness: 0.86)
        let underside = matte(UIColor(red: 0.32, green: 0.35, blue: 0.37, alpha: 1), roughness: 0.9)
        let room = SCNNode()
        scene.rootNode.addChildNode(room)

        // A cutaway opens the front, right side and roof so the measured shell is legible.
        let slab = SCNBox(width: length + thickness * 2, height: thickness,
                          length: depth + thickness * 2, chamferRadius: thickness * 0.08)
        slab.materials = [floorMaterial, underside, underside, underside, floorMaterial, underside]
        let floor = SCNNode(geometry: slab)
        floor.position.y = -Float(thickness / 2)
        room.addChildNode(floor)
        addBox(to: room, width: length + thickness * 2, height: height, depth: thickness,
               position: SCNVector3(0, Float(height / 2), -Float((depth + thickness) / 2)), material: wallMaterial)
        addBox(to: room, width: thickness, height: height, depth: depth + thickness,
               position: SCNVector3(-Float((length + thickness) / 2), Float(height / 2), -Float(thickness / 2)),
               material: wallMaterial)

        // Fine floor joints are presentation styling, never an inferred surface grid.
        let jointMaterial = matte(UIColor(red: 0.40, green: 0.39, blue: 0.36, alpha: 1), roughness: 1)
        for fraction in [0.33, 0.66] {
            addBox(to: room, width: length, height: thickness * 0.012, depth: extent * 0.0008,
                   position: SCNVector3(0, Float(thickness * 0.006), Float(depth * (fraction - 0.5))),
                   material: jointMaterial)
        }

        // Small schematic device marker at the estimated acoustic source position.
        let p = candidate.sensor_position_m
        let phone = SCNBox(width: extent * 0.014, height: extent * 0.0024,
                           length: extent * 0.028, chamferRadius: extent * 0.0018)
        phone.materials = [matte(UIColor(red: 0.15, green: 0.20, blue: 0.25, alpha: 1), roughness: 0.4)]
        let sensor = SCNNode(geometry: phone)
        sensor.position = SCNVector3(Float(p[0] - length / 2), Float(p[2]), Float(p[1] - depth / 2))
        room.addChildNode(sensor)
        let marker = SCNNode(geometry: SCNCylinder(radius: extent * 0.014, height: extent * 0.0004))
        marker.geometry?.firstMaterial?.diffuse.contents = UIColor(red: 0.84, green: 0.66, blue: 0.37, alpha: 1)
        marker.geometry?.firstMaterial?.lightingModel = .constant
        marker.position = SCNVector3(sensor.position.x, Float(extent * 0.0004), sensor.position.z)
        room.addChildNode(marker)

        let focus = SCNNode()
        focus.position = SCNVector3(0, Float(height * 0.42), 0)
        scene.rootNode.addChildNode(focus)
        coordinator.focus = focus.position
        coordinator.scale = Float(extent)

        let ambient = SCNNode()
        ambient.light = SCNLight()
        ambient.light?.type = .ambient
        ambient.light?.color = UIColor(red: 0.77, green: 0.83, blue: 0.91, alpha: 1)
        ambient.light?.intensity = 430
        scene.rootNode.addChildNode(ambient)
        let keyLight = SCNNode()
        keyLight.light = SCNLight()
        keyLight.light?.type = .directional
        keyLight.light?.intensity = 1200
        keyLight.light?.temperature = 5600
        keyLight.light?.castsShadow = true
        keyLight.light?.shadowMode = .deferred
        keyLight.light?.shadowColor = UIColor.black.withAlphaComponent(0.28)
        keyLight.light?.shadowRadius = 8
        keyLight.light?.shadowSampleCount = 16
        keyLight.light?.shadowMapSize = CGSize(width: 2048, height: 2048)
        keyLight.light?.orthographicScale = extent * 2
        keyLight.light?.zNear = 0.01
        keyLight.light?.zFar = extent * 8
        keyLight.position = SCNVector3(Float(extent * 0.6), Float(extent * 1.8), Float(extent * 0.8))
        keyLight.constraints = [SCNLookAtConstraint(target: focus)]
        scene.rootNode.addChildNode(keyLight)
        let fill = SCNNode()
        fill.light = SCNLight()
        fill.light?.type = .omni
        fill.light?.intensity = 230
        fill.light?.color = UIColor(red: 0.76, green: 0.85, blue: 1, alpha: 1)
        fill.position = SCNVector3(-Float(extent), Float(height), Float(extent))
        scene.rootNode.addChildNode(fill)
        scene.lightingEnvironment.contents = studioEnvironment()
        scene.lightingEnvironment.intensity = 0.6

        addAcousticObjectRings(to: room, sensor: sensor.position, objects: objects,
                               length: length, depth: depth, extent: extent)
        if let staging, !staging.objects.isEmpty {
            addStaging(to: room, staging: staging, length: length, depth: depth, extent: extent)
#if DEBUG
            print("ECHOLYRA_GEOM scene staged=\(staging.objects.count) rings=\(objects.count)")
            fflush(stdout)
#endif
        }
        addDimensions(to: scene.rootNode, length: length, depth: depth, height: height, extent: extent)
        let camera = SCNNode()
        camera.camera = SCNCamera()
        camera.camera?.fieldOfView = 42
        camera.camera?.zNear = 0.01
        camera.camera?.zFar = extent * 12
        camera.camera?.wantsHDR = true
        camera.camera?.wantsExposureAdaptation = false
        camera.camera?.screenSpaceAmbientOcclusionIntensity = 1.0
        camera.camera?.screenSpaceAmbientOcclusionRadius = extent * 0.12
        camera.camera?.screenSpaceAmbientOcclusionBias = 0.01
        let look = SCNLookAtConstraint(target: focus)
        look.isGimbalLockEnabled = true
        camera.constraints = [look]
        scene.rootNode.addChildNode(camera)
        view.scene = scene
        view.pointOfView = camera
        view.defaultCameraController.pointOfView = camera
        view.defaultCameraController.target = focus.position
        coordinator.camera = camera
        coordinator.angle = nil
        coordinator.zoom = nil
    }


    private func hexColor(_ hex: String, fallback: UIColor) -> UIColor {
        var value = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.hasPrefix("#") { value.removeFirst() }
        guard value.count == 6, let number = UInt64(value, radix: 16) else { return fallback }
        return UIColor(red: CGFloat((number >> 16) & 0xff) / 255,
                       green: CGFloat((number >> 8) & 0xff) / 255,
                       blue: CGFloat(number & 0xff) / 255, alpha: 1)
    }

    private func addAcousticObjectRings(to parent: SCNNode, sensor: SCNVector3,
                                        objects: [GeometryObject], length: Double,
                                        depth: Double, extent: Double) {
        guard !objects.isEmpty else { return }
        let cyan = UIColor(red: 0.36, green: 0.83, blue: 0.92, alpha: 1)
        let maxRadius = max(length, depth) * 1.25
        for object in objects.prefix(5) {
            let radius = min(max(object.distance_m, 0.2), maxRadius)
            let ring = SCNTorus(ringRadius: CGFloat(radius), pipeRadius: CGFloat(extent * 0.0022))
            let material = matte(cyan.withAlphaComponent(0.72), roughness: 0.35)
            material.emission.contents = cyan.withAlphaComponent(0.55)
            material.emission.intensity = 0.8
            ring.materials = [material]
            let node = SCNNode(geometry: ring)
            node.position = SCNVector3(sensor.x, 0.012, sensor.z)
            node.eulerAngles.x = -.pi / 2
            parent.addChildNode(node)
            if let label = textNode(String(format: "≈ %.1f m", object.distance_m),
                                    size: CGFloat(extent * 0.030), color: cyan) {
                label.position = SCNVector3(sensor.x + Float(radius), 0.22, sensor.z)
                parent.addChildNode(label)
            }
        }
    }

    private func addStaging(to parent: SCNNode, staging: GeometryStaging,
                            length: Double, depth: Double, extent: Double) {
        for object in staging.objects.prefix(8) {
            let node = stagingNode(for: object, length: length, depth: depth, extent: extent)
            node.position = SCNVector3(Float(object.x - length / 2), Float(object.h / 2),
                                       Float(object.z - depth / 2))
            parent.addChildNode(node)
        }
        // A billboard keeps the illustration label legible from any orbit angle.
        let orange = UIColor(red: 0.95, green: 0.64, blue: 0.28, alpha: 1)
        if let banner = textNode("ILLUSTRATIVE · NOT MEASURED",
                                 size: CGFloat(extent * 0.026), color: orange) {
            banner.position = SCNVector3(0, Float(extent * 0.46), 0)
            parent.addChildNode(banner)
        }
    }

    private func stagingNode(for object: StagingObject, length: Double, depth: Double,
                             extent: Double) -> SCNNode {
        let node = SCNNode()
        let color = hexColor(object.color, fallback: UIColor(red: 0.72, green: 0.66, blue: 0.58, alpha: 1))
        let material = matte(color, roughness: 0.72)
        func box(_ w: Double, _ h: Double, _ d: Double, x: Double = 0, y: Double = 0, z: Double = 0,
                 material override: SCNMaterial? = nil) -> SCNNode {
            let geometry = SCNBox(width: CGFloat(w), height: CGFloat(h), length: CGFloat(d),
                                  chamferRadius: CGFloat(min(w, min(h, d)) * 0.06))
            geometry.materials = [override ?? material]
            let child = SCNNode(geometry: geometry)
            child.position = SCNVector3(Float(x), Float(y), Float(z))
            return child
        }
        switch object.kind {
        case "rug":
            node.addChildNode(box(object.w, max(0.012, object.h), object.d, y: -object.h / 2 + 0.006,
                                  material: matte(color.withAlphaComponent(0.92), roughness: 1)))
        case "table", "desk":
            let top = box(object.w, object.h * 0.10, object.d, y: object.h / 2 - object.h * 0.05)
            node.addChildNode(top)
            for dx in [-1.0, 1.0] {
                for dz in [-1.0, 1.0] {
                    let leg = SCNCylinder(radius: CGFloat(min(object.w, object.d) * 0.035),
                                          height: CGFloat(object.h * 0.9))
                    leg.materials = [material]
                    let legNode = SCNNode(geometry: leg)
                    legNode.position = SCNVector3(Float(dx * (object.w / 2 - object.w * 0.08)),
                                                  Float(-object.h * 0.05),
                                                  Float(dz * (object.d / 2 - object.d * 0.08)))
                    node.addChildNode(legNode)
                }
            }
        case "sofa", "armchair", "chair":
            node.addChildNode(box(object.w, object.h * 0.5, object.d, y: -object.h * 0.2))
            node.addChildNode(box(object.w, object.h * 0.55, object.d * 0.22,
                                  y: object.h * 0.16, z: -object.d / 2 + object.d * 0.11))
            if object.kind != "chair" {
                for dx in [-1.0, 1.0] {
                    node.addChildNode(box(object.w * 0.09, object.h * 0.4, object.d,
                                          x: dx * (object.w / 2 - object.w * 0.045), y: -object.h * 0.1))
                }
            } else {
                for dx in [-1.0, 1.0] {
                    for dz in [-1.0, 1.0] {
                        node.addChildNode(box(object.w * 0.07, object.h * 0.45, object.d * 0.07,
                                              x: dx * (object.w / 2 - object.w * 0.06),
                                              y: -object.h * 0.28,
                                              z: dz * (object.d / 2 - object.d * 0.08)))
                    }
                }
            }
        case "bed":
            node.addChildNode(box(object.w, object.h * 0.35, object.d, y: -object.h * 0.32))
            node.addChildNode(box(object.w, object.h * 0.22, object.d,
                                  y: object.h * 0.02, material: matte(UIColor.white.withAlphaComponent(0.85), roughness: 0.95)))
            node.addChildNode(box(object.w * 0.9, object.h * 0.3, object.d * 0.05,
                                  y: object.h * 0.25, z: -object.d / 2 + object.d * 0.05))
        case "shelf":
            node.addChildNode(box(object.w, object.h, object.d, y: 0,
                                  material: matte(color.withAlphaComponent(0.55), roughness: 0.8)))
            for fraction in [0.25, 0.5, 0.75] {
                node.addChildNode(box(object.w * 0.94, object.h * 0.03, object.d * 0.9,
                                      y: -object.h / 2 + object.h * fraction))
            }
        case "plant":
            let pot = SCNCylinder(radius: CGFloat(object.w * 0.32), height: CGFloat(object.h * 0.28))
            pot.materials = [matte(color, roughness: 0.9)]
            let potNode = SCNNode(geometry: pot)
            potNode.position = SCNVector3(0, -object.h / 2 + object.h * 0.14, 0)
            node.addChildNode(potNode)
            for i in 0..<3 {
                let leaf = SCNSphere(radius: CGFloat(object.w * (0.34 - Double(i) * 0.07)))
                leaf.materials = [matte(UIColor(red: 0.32, green: 0.46, blue: 0.31, alpha: 1), roughness: 0.9)]
                let leafNode = SCNNode(geometry: leaf)
                leafNode.position = SCNVector3(Float((Double(i) - 1) * object.w * 0.16),
                                               Float(-object.h / 2 + object.h * (0.45 + Double(i) * 0.12)),
                                               Float((Double(i) - 1) * object.d * 0.1))
                node.addChildNode(leafNode)
            }
        case "lamp":
            node.addChildNode(box(object.w * 0.45, max(0.03, object.h * 0.04), object.d * 0.45,
                                  y: -object.h / 2 + object.h * 0.02,
                                  material: matte(UIColor(white: 0.2, alpha: 1), roughness: 0.5)))
            let stem = SCNCylinder(radius: CGFloat(object.w * 0.035), height: CGFloat(object.h * 0.85))
            stem.materials = [matte(UIColor(white: 0.25, alpha: 1), roughness: 0.4)]
            let stemNode = SCNNode(geometry: stem)
            stemNode.position = SCNVector3(0, 0, 0)
            node.addChildNode(stemNode)
            let shade = SCNSphere(radius: CGFloat(object.w * 0.3))
            let shadeMaterial = matte(color.withAlphaComponent(0.9), roughness: 0.5)
            shadeMaterial.emission.contents = color.withAlphaComponent(0.35)
            shade.materials = [shadeMaterial]
            let shadeNode = SCNNode(geometry: shade)
            shadeNode.position = SCNVector3(0, Float(object.h * 0.42), 0)
            node.addChildNode(shadeNode)
        default:
            node.addChildNode(box(object.w, object.h, object.d))
        }
        return node
    }

    private func textNode(_ text: String, size: CGFloat, color: UIColor) -> SCNNode? {
        let geometry = SCNText(string: text, extrusionDepth: 0)
        geometry.font = UIFont.systemFont(ofSize: 1, weight: .semibold)
        geometry.flatness = 0.02
        let material = SCNMaterial()
        material.lightingModel = .constant
        material.diffuse.contents = color
        geometry.materials = [material]
        let node = SCNNode(geometry: geometry)
        node.scale = SCNVector3(Float(size), Float(size), Float(size))   // size in metres
        node.constraints = [SCNBillboardConstraint()]
        return node
    }

    private func matte(_ color: UIColor, roughness: CGFloat) -> SCNMaterial {
        let material = SCNMaterial()
        material.lightingModel = .physicallyBased
        material.diffuse.contents = color
        material.roughness.contents = roughness
        material.metalness.contents = 0
        return material
    }

    private func addBox(to parent: SCNNode, width: Double, height: Double, depth: Double,
                        position: SCNVector3, material: SCNMaterial) {
        let geometry = SCNBox(width: width, height: height, length: depth, chamferRadius: 0)
        geometry.materials = [material]
        let node = SCNNode(geometry: geometry)
        node.position = position
        parent.addChildNode(node)
    }

    private func studioEnvironment() -> UIImage {
        let size = CGSize(width: 512, height: 256)
        return UIGraphicsImageRenderer(size: size).image { renderer in
            let colors = [UIColor(white: 0.24, alpha: 1).cgColor, UIColor(white: 0.92, alpha: 1).cgColor,
                          UIColor(white: 0.38, alpha: 1).cgColor] as CFArray
            if let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors,
                                         locations: [0, 0.45, 1]) {
                renderer.cgContext.drawLinearGradient(gradient, start: .zero,
                    end: CGPoint(x: 0, y: size.height), options: [])
            }
        }
    }

    private func addDimensions(to parent: SCNNode, length: Double, depth: Double, height: Double, extent: Double) {
        let material = SCNMaterial()
        material.lightingModel = .constant
        material.diffuse.contents = UIColor(white: 0.70, alpha: 1)
        let offset = Float(extent * 0.065)
        let l = Float(length / 2), d = Float(depth / 2), h = Float(height)
        dimensionLine(to: parent, from: SIMD3(-l, 0, d + offset), to: SIMD3(l, 0, d + offset),
                      radius: extent * 0.00065, material: material)
        dimensionLine(to: parent, from: SIMD3(l + offset, 0, -d), to: SIMD3(l + offset, 0, d),
                      radius: extent * 0.00065, material: material)
        dimensionLine(to: parent, from: SIMD3(-l - offset, 0, d), to: SIMD3(-l - offset, h, d),
                      radius: extent * 0.00065, material: material)
        dimensionText(to: parent, value: length, position: SCNVector3(0, -Float(extent * 0.025), d + offset * 1.5), extent: extent)
        dimensionText(to: parent, value: depth, position: SCNVector3(l + offset * 1.5, -Float(extent * 0.025), 0), extent: extent)
        dimensionText(to: parent, value: height, position: SCNVector3(-l - offset * 1.5, h / 2, d), extent: extent)
    }

    private func dimensionLine(to parent: SCNNode, from start: SIMD3<Float>, to end: SIMD3<Float>,
                               radius: Double, material: SCNMaterial) {
        let delta = end - start
        let geometry = SCNCylinder(radius: radius, height: Double(simd_length(delta)))
        geometry.radialSegmentCount = 6
        geometry.materials = [material]
        let node = SCNNode(geometry: geometry)
        node.simdPosition = (start + end) / 2
        node.simdOrientation = simd_quatf(from: SIMD3(0, 1, 0), to: simd_normalize(delta))
        parent.addChildNode(node)
    }

    private func dimensionText(to parent: SCNNode, value: Double, position: SCNVector3, extent: Double) {
        let geometry = SCNText(string: String(format: "≈ %.2f m", value), extrusionDepth: 0)
        geometry.font = UIFont.systemFont(ofSize: 1, weight: .medium)
        geometry.flatness = 0.1
        geometry.firstMaterial?.lightingModel = .constant
        geometry.firstMaterial?.diffuse.contents = UIColor(white: 0.90, alpha: 1)
        let node = SCNNode(geometry: geometry)
        let bounds = node.boundingBox
        node.pivot = SCNMatrix4MakeTranslation((bounds.min.x + bounds.max.x) / 2, (bounds.min.y + bounds.max.y) / 2, 0)
        let scale = Float(extent * 0.021)
        node.scale = SCNVector3(scale, scale, scale)
        node.position = position
        node.constraints = [SCNBillboardConstraint()]
        parent.addChildNode(node)
    }
}

private struct ReflectionScene: UIViewRepresentable {
    let scan: ReflectionScan

    final class Coordinator {
        var key = ""
        var camera: SCNNode?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.backgroundColor = UIColor(red: 0.08, green: 0.10, blue: 0.13, alpha: 1)
        view.allowsCameraControl = true
        view.antialiasingMode = .multisampling4X
        view.autoenablesDefaultLighting = false
        return view
    }

    func updateUIView(_ view: SCNView, context: Context) {
        let key = scan.status + scan.reflectors.map { "\($0.id)\($0.x)\($0.y)\($0.type)" }.joined()
        guard context.coordinator.key != key else { return }
        context.coordinator.key = key
        buildScene(view, coordinator: context.coordinator)
    }

    private func buildScene(_ view: SCNView, coordinator: Coordinator) {
        let scene = SCNScene()
        let xs = scan.poses.map(\.x) + scan.reflectors.map(\.x)
        let ys = scan.poses.map(\.y) + scan.reflectors.map(\.y)
        let minX = xs.min() ?? -1, maxX = xs.max() ?? 3
        let minY = ys.min() ?? -1, maxY = ys.max() ?? 3
        let span = max(max(maxX - minX, maxY - minY), 2.0)
        let cx = (minX + maxX) / 2, cy = (minY + maxY) / 2
        let extent = max(span, 2.5)

        let gridMaterial = SCNMaterial()
        gridMaterial.lightingModel = .constant
        gridMaterial.diffuse.contents = UIColor(white: 0.55, alpha: 0.28)
        let half = extent * 0.8
        var line = floor((cx - half) / 0.5) * 0.5
        while line <= cx + half {
            let vertical = SCNBox(width: 0.008, height: 0.004, length: CGFloat(half * 2),
                                  chamferRadius: 0)
            vertical.materials = [gridMaterial]
            let node = SCNNode(geometry: vertical)
            node.position = SCNVector3(Float(line - cx), 0, 0)
            scene.rootNode.addChildNode(node)
            let horizontal = SCNBox(width: CGFloat(half * 2), height: 0.004, length: 0.008,
                                    chamferRadius: 0)
            horizontal.materials = [gridMaterial]
            let hnode = SCNNode(geometry: horizontal)
            hnode.position = SCNVector3(0, 0, Float(line - cy))
            scene.rootNode.addChildNode(hnode)
            line += 0.5
        }

        let pathMaterial = SCNMaterial()
        pathMaterial.lightingModel = .constant
        pathMaterial.diffuse.contents = UIColor(red: 0.44, green: 0.62, blue: 0.95, alpha: 1)
        for index in 0..<max(0, scan.poses.count - 1) {
            let a = scan.poses[index], b = scan.poses[index + 1]
            let dx = b.x - a.x, dz = b.y - a.y
            let length = max(hypot(dx, dz), 0.01)
            let segment = SCNBox(width: CGFloat(length), height: 0.01, length: 0.02, chamferRadius: 0)
            segment.materials = [pathMaterial]
            let node = SCNNode(geometry: segment)
            node.position = SCNVector3(Float((a.x + b.x) / 2 - cx), 0.012, Float((a.y + b.y) / 2 - cy))
            node.eulerAngles.y = Float(-atan2(dz, dx))
            scene.rootNode.addChildNode(node)
        }
        for (index, pose) in scan.poses.enumerated() {
            let marker = SCNSphere(radius: 0.07)
            let material = SCNMaterial()
            material.lightingModel = .constant
            material.diffuse.contents = UIColor(red: 0.44, green: 0.62, blue: 0.95, alpha: 1)
            marker.materials = [material]
            let node = SCNNode(geometry: marker)
            node.position = SCNVector3(Float(pose.x - cx), 0.07, Float(pose.y - cy))
            scene.rootNode.addChildNode(node)
            if let label = labelNode("\(index + 1)", size: 0.12,
                                     color: UIColor(red: 0.55, green: 0.72, blue: 1, alpha: 1)) {
                label.position = SCNVector3(Float(pose.x - cx), 0.20, Float(pose.y - cy))
                scene.rootNode.addChildNode(label)
            }
        }

        for reflector in scan.reflectors {
            let persistent = reflector.type == "persistent"
            let color = persistent
                ? UIColor(red: 0.30, green: 0.86, blue: 0.94, alpha: 1)
                : UIColor(red: 0.96, green: 0.66, blue: 0.30, alpha: 1)
            let sphere = SCNSphere(radius: 0.11)
            let material = SCNMaterial()
            material.lightingModel = .constant
            material.diffuse.contents = color.withAlphaComponent(0.9)
            sphere.materials = [material]
            let node = SCNNode(geometry: sphere)
            node.position = SCNVector3(Float(reflector.x - cx), 0.42, Float(reflector.y - cy))
            scene.rootNode.addChildNode(node)
            let ring = SCNTorus(ringRadius: 0.16, pipeRadius: 0.008)
            let ringMaterial = SCNMaterial()
            ringMaterial.lightingModel = .constant
            ringMaterial.diffuse.contents = color.withAlphaComponent(0.7)
            ring.materials = [ringMaterial]
            let ringNode = SCNNode(geometry: ring)
            ringNode.eulerAngles.x = -.pi / 2
            ringNode.position = SCNVector3(Float(reflector.x - cx), 0.01, Float(reflector.y - cy))
            scene.rootNode.addChildNode(ringNode)
            if let label = labelNode(String(format: "≈ %.1f m", reflector.distance_from_start_m),
                                     size: 0.11, color: color) {
                label.position = SCNVector3(Float(reflector.x - cx), 0.62, Float(reflector.y - cy))
                scene.rootNode.addChildNode(label)
            }
        }

        if let banner = labelNode("REFLECTION CANDIDATES · NOT IDENTIFIED OBJECTS",
                                  size: extent * 0.030,
                                  color: UIColor(red: 0.95, green: 0.64, blue: 0.28, alpha: 1)) {
            banner.position = SCNVector3(0, Float(extent * 0.55), 0)
            scene.rootNode.addChildNode(banner)
        }

        let ambient = SCNNode()
        ambient.light = SCNLight()
        ambient.light?.type = .ambient
        ambient.light?.intensity = 560
        ambient.light?.color = UIColor(red: 0.82, green: 0.88, blue: 0.96, alpha: 1)
        scene.rootNode.addChildNode(ambient)
        let keyLight = SCNNode()
        keyLight.light = SCNLight()
        keyLight.light?.type = .directional
        keyLight.light?.intensity = 900
        keyLight.light?.temperature = 5800
        keyLight.position = SCNVector3(Float(extent), Float(extent * 2), Float(extent))
        scene.rootNode.addChildNode(keyLight)

        let focus = SCNNode()
        focus.position = SCNVector3(0, 0.3, 0)
        scene.rootNode.addChildNode(focus)
        let camera = SCNNode()
        camera.camera = SCNCamera()
        camera.camera?.fieldOfView = 45
        camera.camera?.zNear = 0.01
        camera.camera?.zFar = extent * 12
        camera.camera?.wantsHDR = true
        camera.position = SCNVector3(Float(extent * 0.9), Float(extent * 1.35), Float(extent * 1.05))
        let look = SCNLookAtConstraint(target: focus)
        look.isGimbalLockEnabled = true
        camera.constraints = [look]
        scene.rootNode.addChildNode(camera)

        view.scene = scene
        view.pointOfView = camera
        view.defaultCameraController.target = focus.position
        coordinator.camera = camera
    }

    private func labelNode(_ text: String, size: CGFloat, color: UIColor) -> SCNNode? {
        let geometry = SCNText(string: text, extrusionDepth: 0)
        geometry.font = UIFont.systemFont(ofSize: 1, weight: .semibold)
        geometry.flatness = 0.02
        let material = SCNMaterial()
        material.lightingModel = .constant
        material.diffuse.contents = color
        geometry.materials = [material]
        let node = SCNNode(geometry: geometry)
        node.scale = SCNVector3(Float(size), Float(size), Float(size))
        node.constraints = [SCNBillboardConstraint()]
        return node
    }
}

import SwiftUI
import SceneKit
import simd

struct GeometryView: View {
    @EnvironmentObject private var model: AppModel
    @State private var result: GeometryResult?
    @State private var selectedCandidate = ""
    @State private var sceneAngle = 0.0
    @State private var sceneZoom = 1.0
    @State private var progress = ""
    @State private var review: GeometryReview?
    @State private var reviewConsent = false
    @State private var work: Task<Void, Never>?

    private var candidate: GeometryCandidate? {
        guard let result, result.status != "insufficient_evidence" else { return nil }
        return result.candidates.first(where: { $0.id == selectedCandidate }) ?? result.candidates.first
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
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
                }
                .padding()
            }
            .navigationTitle("3D Room")
            .task {
#if DEBUG
                if ProcessInfo.processInfo.arguments.contains("-geometryDemo"), result == nil {
                    await loadDemo()
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
        }
    }

    private var intro: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("Experimental · sound only", systemImage: "waveform")
                .font(.subheadline.weight(.semibold)).foregroundStyle(.orange)
            Text("Hear the room’s shape").font(.title2.weight(.bold))
            Text("Echo timings can suggest a rectangular room shell. This is an estimate. Furniture and doors aren’t mapped, and the room’s orientation is unknown.")
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
            Text("Recordings are sent to your configured backend for reconstruction. This feature makes no cloud call unless you choose Ask Meta.")
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
            AcousticRoomScene(candidate: candidate, angle: sceneAngle, zoom: sceneZoom)
                .frame(height: 360)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .accessibilityLabel("Estimated rectangular room, axes \(dimensionDescription(candidate)) metres")
                .accessibilityHint("Use the controls below to rotate and zoom the room.")
            cameraControls
            Text("Rotate and zoom with the controls · marker = estimated phone position")
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
            Text("Cutaway orientation and finishes are illustrative. The measurements do not identify materials, furniture, floor or ceiling.")
                .font(.caption).foregroundStyle(.secondary)
            Text(String(format: "Echo fit error %.3f ms · %d/%d predicted echoes matched", candidate.fit_error_ms,
                        candidate.matched_echoes, candidate.total_predicted_echoes))
                .font(.caption.monospacedDigit())
            Text("Echo match quality measures how well this layout explains the recording. It does not confirm the room’s actual dimensions.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding().background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
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

    @MainActor private func measure() async {
        guard !model.busy else { return }
        model.busy = true
        result = nil; review = nil
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
        } catch is CancellationError {
            // Navigating away cancels capture; ProbeRecorder releases audio resources.
        } catch { if !Task.isCancelled { model.errorText = error.localizedDescription } }
    }

    @MainActor private func loadDemo() async {
        guard !model.busy else { return }
        model.busy = true
        result = nil; review = nil
        progress = "Reconstructing simulated probe recordings…"
        defer { model.busy = false; progress = "" }
        do {
            let received = try await model.client.geometryDemo()
            try Task.checkCancellation()
            result = received
            selectedCandidate = received.candidates.first?.id ?? ""
            resetCamera()
        } catch is CancellationError {} catch { if !Task.isCancelled { model.errorText = error.localizedDescription } }
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
        let key = candidate.id + candidate.dimensions_m.description + candidate.sensor_position_m.description
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

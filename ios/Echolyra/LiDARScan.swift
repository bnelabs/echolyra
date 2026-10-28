import SwiftUI
import SceneKit
import ARKit
import Combine
@preconcurrency import RoomPlan
import simd

struct LiDARResult {
    let room: CapturedRoom
    let modelURL: URL?

    var wallCount: Int { room.walls.count }
    var doorCount: Int { room.doors.count }
    var windowCount: Int { room.windows.count }
    var objectCount: Int { room.objects.count }

    var objectSummary: String {
        let names = room.objects.map { String(describing: $0.category) }
        let counts = Dictionary(grouping: names, by: { $0 }).mapValues { $0.count }
        return counts.sorted { $0.value > $1.value }
            .map { "\($0.key) ×\($0.value)" }
            .joined(separator: ", ")
    }
}

@MainActor
final class LiDARCaptureController: NSObject, ObservableObject, RoomCaptureViewDelegate, RoomCaptureSessionDelegate {
    @Published var finishedRoom: CapturedRoom?
    @Published var isRunning = false
    @Published var message = "Slowly walk around the room. The LiDAR map builds as you move."
    private weak var captureView: RoomCaptureView?

    override init() { super.init() }

    nonisolated required init?(coder: NSCoder) { super.init() }

    nonisolated func encode(with coder: NSCoder) {}

    func makeView() -> RoomCaptureView {
        let view = RoomCaptureView(frame: .zero)
        view.delegate = self
        view.captureSession.delegate = self
        captureView = view
        return view
    }

    func start() {
        guard let captureView else { return }
        captureView.captureSession.run(configuration: RoomCaptureSession.Configuration())
        isRunning = true
        message = "Scanning… walk around the whole room, then tap Finish."
    }

    func stop() {
        guard let captureView else { return }
        captureView.captureSession.stop()
        isRunning = false
        message = "Processing the LiDAR model…"
    }

    nonisolated func captureView(_ view: RoomCaptureView, didFinishWith capturedRoom: CapturedRoom) {
        Task { @MainActor in
            self.finishedRoom = capturedRoom
            self.isRunning = false
        }
    }

    nonisolated func captureView(_ view: RoomCaptureView, didPresent result: CapturedRoom) {
        Task { @MainActor in self.message = "LiDAR map ready." }
    }

    nonisolated func captureView(_ view: RoomCaptureView, postProcessDeviceTransform deviceTransform: simd_float4x4) {}

    nonisolated func captureSession(_ session: RoomCaptureSession, didEndWith data: CapturedRoomData, error: Error?) {
        if let error {
            Task { @MainActor in self.message = "LiDAR scan failed: \(error.localizedDescription)" }
        }
    }
}

struct LiDARCaptureScreen: View {
    @Environment(\.dismiss) private var dismiss
    let onFinish: (CapturedRoom) -> Void
    @StateObject private var controller = LiDARCaptureController()

    var body: some View {
        ZStack(alignment: .bottom) {
            LiDARCaptureRepresentable(controller: controller)
                .ignoresSafeArea()
            VStack(spacing: 12) {
                Text(controller.message)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(.black.opacity(0.55), in: Capsule())
                HStack(spacing: 12) {
                    Button(controller.isRunning ? "Finish" : "Start") {
                        controller.isRunning ? controller.stop() : controller.start()
                    }
                    .buttonStyle(.borderedProminent)
                    Button("Cancel") { dismiss() }
                        .buttonStyle(.bordered)
                }
            }
            .padding(.bottom, 24)
        }
        .onReceive(controller.$finishedRoom) { room in
            if let room { onFinish(room); dismiss() }
        }
        .interactiveDismissDisabled(controller.isRunning)
    }
}

private struct LiDARCaptureRepresentable: UIViewRepresentable {
    let controller: LiDARCaptureController

    func makeUIView(context: Context) -> RoomCaptureView {
        controller.makeView()
    }

    func updateUIView(_ uiView: RoomCaptureView, context: Context) {}
}

struct LiDARSceneView: UIViewRepresentable {
    let modelURL: URL

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.backgroundColor = UIColor(red: 0.08, green: 0.10, blue: 0.13, alpha: 1)
        view.allowsCameraControl = true
        view.antialiasingMode = .multisampling4X
        view.autoenablesDefaultLighting = false
        if let scene = try? SCNScene(url: modelURL, options: [.checkConsistency: true]) {
            scene.background.contents = UIColor(red: 0.08, green: 0.10, blue: 0.13, alpha: 1)
            view.scene = scene
            let camera = SCNNode()
            camera.camera = SCNCamera()
            camera.camera?.fieldOfView = 50
            camera.camera?.zNear = 0.01
            camera.camera?.zFar = 200
            let box = scene.rootNode.boundingBox
            let extent = max(Float(box.max.x - box.min.x), max(Float(box.max.y - box.min.y), Float(box.max.z - box.min.z)))
            camera.position = SCNVector3(0, extent * 0.65, extent * 1.25)
            let look = SCNLookAtConstraint(target: SCNNode())
            look.isGimbalLockEnabled = true
            camera.constraints = [look]
            scene.rootNode.addChildNode(camera)
            view.pointOfView = camera
            let light = SCNNode()
            light.light = SCNLight()
            light.light?.type = .directional
            light.light?.intensity = 900
            light.position = SCNVector3(extent, extent * 2, extent)
            scene.rootNode.addChildNode(light)
            let ambient = SCNNode()
            ambient.light = SCNLight()
            ambient.light?.type = .ambient
            ambient.light?.intensity = 500
            scene.rootNode.addChildNode(ambient)
        }
        return view
    }

    func updateUIView(_ uiView: SCNView, context: Context) {}
}

func exportLiDARModel(_ room: CapturedRoom) -> URL? {
    let url = FileManager.default.temporaryDirectory
        .appendingPathComponent("echolyra-lidar-\(UUID().uuidString).usdz")
    do {
        try room.export(to: url)
        return url
    } catch {
        return nil
    }
}

var liDARScanningSupported: Bool {
#if targetEnvironment(simulator)
    return false
#else
    if #available(iOS 16.0, *), ARWorldTrackingConfiguration.supportsSceneReconstruction(.mesh) {
        return true
    }
    return false
#endif
}

import SwiftUI

struct ContentView: View {
    @StateObject private var model = AppModel()
    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            RoomsView()
                .tabItem { Label("Rooms", systemImage: "house.fill") }
                .tag(0)
            DetectView()
                .tabItem { Label("Listen", systemImage: "ear.badge.waveform") }
                .tag(1)
            GeometryView()
                .tabItem { Label("3D Room", systemImage: "cube.transparent.fill") }
                .tag(3)
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape.fill") }
                .tag(2)
        }
        .environmentObject(model)
        .task {
            await model.refresh()
#if DEBUG
            let debugEnv = ProcessInfo.processInfo.environment
            if ProcessInfo.processInfo.arguments.contains("-geometryDemo")
                || debugEnv["ECHOLYRA_GEOMETRY_DEMO"] == "1"
                || debugEnv["ECHOLYRA_GEOMETRY_STAGE"] == "1" {
                selectedTab = 3
            } else if ProcessInfo.processInfo.arguments.contains("-sampleResult") {
                model.loadSampleResult()
                selectedTab = 1
            } else if ProcessInfo.processInfo.arguments.contains("-tabListen") {
                selectedTab = 1
            }
            let autotestEnv = ProcessInfo.processInfo.environment["ECHOLYRA_AUTOTEST"] == "1"
            if autotestEnv || ProcessInfo.processInfo.arguments.contains("-autotest") {
                await model.runSelfTest()
                selectedTab = 1
            }
            if let probeMode = ProcessInfo.processInfo.environment["ECHOLYRA_AUTOPROBE"], !probeMode.isEmpty {
                await model.runAutoProbe(mode: probeMode)
            }
#endif
        }
        .alert("Something went wrong", isPresented: Binding(
            get: { model.errorText != nil },
            set: { if !$0 { model.errorText = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.errorText ?? "")
        }
    }
}

#Preview {
    ContentView()
}

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
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gearshape.fill") }
                .tag(2)
        }
        .environmentObject(model)
        .task {
            await model.refresh()
#if DEBUG
            if ProcessInfo.processInfo.arguments.contains("-sampleResult") {
                model.loadSampleResult()
                selectedTab = 1
            } else if ProcessInfo.processInfo.arguments.contains("-tabListen") {
                selectedTab = 1
            }
            if ProcessInfo.processInfo.arguments.contains("-autotest") {
                await model.runSelfTest()
                selectedTab = 1
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

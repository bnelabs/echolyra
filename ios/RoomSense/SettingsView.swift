import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.x.x:8080", text: $model.backendURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Button("Test connection") {
                        Task { await model.refresh() }
                    }
                } header: {
                    Text("Backend")
                } footer: {
                    Text("The phone and the Mac must be on the same Wi-Fi. This URL is your Mac's LAN address.")
                }

                Section("Session") {
                    Button("Reset learned rooms", role: .destructive) {
                        Task { await model.reset() }
                    }
                    if let rooms = model.session?.rooms, !rooms.isEmpty {
                        Text("\(rooms.count) room(s) learned")
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Privacy") {
                    Text("RoomSense never plays sounds and never stores recordings on the server. Only numeric acoustic features are uploaded, so the app can tell what happened without keeping what it heard.")
                        .font(.footnote)
                }

                Section("About") {
                    Text("RoomSense — camera-free home awareness. Meta Global AI Developer Hackathon, Indie Developer track.")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
        }
    }
}

#Preview {
    SettingsView().environmentObject(AppModel())
}

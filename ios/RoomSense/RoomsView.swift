import SwiftUI

struct RoomsView: View {
    @EnvironmentObject private var model: AppModel
    @StateObject private var recorder = Recorder()
    @State private var roomName = ""

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Room name (e.g. Kitchen)", text: $roomName)
                        .textInputAutocapitalization(.words)
                    Button {
                        recordAndEnroll()
                    } label: {
                        HStack {
                            Image(systemName: recorder.isRecording ? "waveform" : "hand.tap.fill")
                            Text(recorder.isRecording
                                 ? "Listening… \(Int(recorder.remaining))s"
                                 : "Knock once and record")
                        }
                    }
                    .disabled(recorder.isRecording || roomName.trimmingCharacters(in: .whitespaces).isEmpty)
                    Text("Put the phone where it will normally sit, then have someone knock once in this room. Repeat for each room.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } header: {
                    Text("Learn a room")
                }

                Section("Learned rooms") {
                    if let rooms = model.session?.rooms, !rooms.isEmpty {
                        ForEach(rooms) { room in
                            HStack {
                                Text(room.name)
                                Spacer()
                                Text("\(room.examples ?? 0) sample\(room.examples == 1 ? "" : "s")")
                                    .foregroundStyle(.secondary)
                            }
                        }
                    } else {
                        Text("No rooms yet. Knock once per room.")
                            .foregroundStyle(.secondary)
                    }
                }

                Section {
                    Text("RoomSense keeps no audio. Only numeric acoustic features are sent to your own backend.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Rooms")
            .refreshable { await model.refresh() }
            .overlay { if model.busy { ProgressView() } }
        }
    }

    private func recordAndEnroll() {
        let name = roomName.trimmingCharacters(in: .whitespaces)
        Task {
            do {
                let rec = try await recorder.record(seconds: 2.8)
                await model.enroll(roomName: name, clip: rec.data)
                try? FileManager.default.removeItem(at: rec.url)
                roomName = ""
            } catch {
                model.errorText = error.localizedDescription
            }
        }
    }
}

#Preview {
    RoomsView().environmentObject(AppModel())
}

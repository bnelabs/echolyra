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
                    Button {
                        Task { await model.probe(roomName: roomName.trimmingCharacters(in: .whitespaces)) }
                    } label: {
                        Label("Measure acoustics (active probe)", systemImage: "waveform.path.ecg")
                    }
                    .disabled(model.busy || roomName.trimmingCharacters(in: .whitespaces).isEmpty)
                    Text("Knock = fast signature. Active probe = the phone emits a quiet 3 s sweep and measures the room's true impulse response (RT60, per-band decay) — this is what detects a room changing later.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let message = model.probeMessage {
                        Text(message).font(.caption).foregroundStyle(.green)
                    }
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
                                if let rt60 = model.probeRT60ByRoom[room.name] {
                                    Text(String(format: "RT60 %.2f s", rt60))
                                        .font(.caption2.monospacedDigit())
                                        .foregroundStyle(.secondary)
                                }
                                if let status = model.probeStatusByRoom[room.name] {
                                    Text(status)
                                        .font(.caption2)
                                        .foregroundStyle(status.contains("changed") || status.contains("unusual") ? .orange : .secondary)
                                }
                                Button("Re-probe") {
                                    Task { await model.probeCheck(roomName: room.name) }
                                }
                                .buttonStyle(.borderless)
                                .font(.caption)
                                .disabled(model.busy)
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

import SwiftUI

struct DetectView: View {
    @EnvironmentObject private var model: AppModel
    @StateObject private var recorder = Recorder()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Button {
                        listen()
                    } label: {
                        VStack(spacing: 10) {
                            Image(systemName: recorder.isRecording ? "waveform.circle.fill" : "ear.badge.waveform")
                                .font(.system(size: 46))
                            Text(recorder.isRecording
                                 ? "Listening… \(Int(recorder.remaining))s"
                                 : "Listen for 3 seconds")
                                .font(.headline)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 34)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(recorder.isRecording)

                    Text("Make the sound while it listens — a knock, a dropped spoon, a clap.")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    if let result = model.lastResult {
                        ResultCard(result: result)
                        teachMenu
                    }

                    if let events = model.session?.events, !events.isEmpty {
                        Text("Recent").font(.headline).padding(.top, 8)
                        ForEach(events) { event in
                            HStack {
                                Text(EventLabels.pretty(event.label ?? "unknown"))
                                Spacer()
                                Text(event.room ?? "—")
                                Text(((event.confidence ?? 0) * 100).formatted(.number.precision(.fractionLength(0))) + "%")
                                    .foregroundStyle(.secondary)
                            }
                            .font(.subheadline)
                        }
                    }
                }
                .padding()
            }
            .navigationTitle("Listen")
            .overlay { if model.busy { ProgressView("Thinking…") } }
        }
    }

    private var teachMenu: some View {
        Menu {
            ForEach(EventLabels.all, id: \.self) { label in
                Button(EventLabels.pretty(label)) {
                    Task { await model.teach(label: label) }
                }
            }
        } label: {
            Label("Teach this sound", systemImage: "graduationcap.fill")
        }
        .buttonStyle(.bordered)
    }

    private func listen() {
        Task {
            do {
                let clip = try await recorder.record(seconds: 3.2)
                await model.detect(clip: clip)
            } catch {
                model.errorText = error.localizedDescription
            }
        }
    }
}

struct ResultCard: View {
    let result: DetectResponse

    private var urgencyColor: Color {
        switch (result.situation.urgency ?? "").lowercased() {
        case "high": return .red
        case "medium": return .orange
        default: return .green
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(EventLabels.pretty(result.event.label))
                    .font(.title2.weight(.bold))
                Spacer()
                Text("\((result.event.confidence * 100).formatted(.number.precision(.fractionLength(0))))%")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
            HStack(spacing: 8) {
                Image(systemName: "mappin.and.ellipse")
                Text(result.room.room_name ?? "Unknown room")
                Text("\((result.room.confidence * 100).formatted(.number.precision(.fractionLength(0))))%")
                    .foregroundStyle(.secondary)
            }
            .font(.subheadline)

            if result.room.confidence < 0.35 {
                Text("Room uncertain — teach this sound, or record another sample in that room.")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            if let urgency = result.situation.urgency {
                Text("Urgency: \(urgency.capitalized)")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(urgencyColor)
            }

            Divider()

            if let headline = result.situation.headline {
                Text(headline).font(.headline)
            }
            if let explanation = result.situation.explanation {
                Text(explanation).font(.subheadline)
            }
            if let action = result.situation.suggested_action {
                Label(action, systemImage: "checkmark.circle")
                    .font(.subheadline)
            }
            if let check = result.situation.false_alarm_check {
                Text(check).font(.caption).foregroundStyle(.secondary)
            }
            if let modelName = result.situation._model {
                Text("Reasoning: \(modelName)").font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .padding()
        .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
    }
}

#Preview {
    DetectView().environmentObject(AppModel())
}

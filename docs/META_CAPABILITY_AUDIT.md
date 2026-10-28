# Meta capability audit: can cloud audio help Echolyra?

**Short answer: no — Meta Model API currently cannot analyze non-speech audio.** We tested this
live rather than assuming it from marketing copy. Cloud help that *does* work: numeric reasoning
(muse-wonder-1.0 / muse-spark-1.3-contributor), image/video understanding, SAM segmentation,
Muse Image generation. This note records the exact evidence and where each capability applies.

## 1. What models exist (live `GET /v1/models`, 2026-10-29)

```
muse-wonder-1.0 · sam-3.1 · muse-spark-1.3-contributor · muse-voice-transcribe-1.0
muse-spark-1.3 · muse-image-1.0 · muse-spark-1.2-contributor · muse-spark-1.2 · muse-spark-1.1
```

## 2. Audio: transcription, not acoustic understanding

Official docs (fetched from `dev.meta.ai/docs`):

- [Video and audio understanding](https://dev.meta.ai/docs/video-understanding): "Muse Spark
  **transcribes spoken audio** to text… audio understanding in Muse Spark 1.3 is currently not
  fully supported, and response quality for requests including audio content may be degraded.
  These examples use Muse Spark 1.2."
- [Speech to text](https://dev.meta.ai/docs/speech-to-text): "**Sound event detection** … not
  available." Muse Voice Transcribe is speech-only (turns, speakers, vocabulary bias).
- [Responses protocol](https://dev.meta.ai/docs/protocols/responses): audio modalities are listed
  among OpenAI parameters **not implemented**.
- [File handling](https://dev.meta.ai/docs/file-handling): files support images, video, PDFs —
  not acoustic probe audio.

## 3. Live test (Echolyra probe/event audio → Muse Wonder)

Sent three different WAVs (real knocks, a synthetic glass clink, digital silence) to
`muse-wonder-1.0` via both Chat Completions and Responses `input_audio` (base64 WAV), with a
prompt that asked for the dominant sound or `NO_AUDIO_ACCESS`.

Result for **every** clip:

```
http 200 · prompt_tokens 66–91 (audio not tokenized) · content: "NO_AUDIO_ACCESS"
```

Conclusion: the endpoint accepts the field but does not process the recording. There is no
Meta audio-geometry/object-understanding path to send recordings to. Adding an audio-upload
button would be misleading, cost tokens, and increase privacy exposure for no benefit, so we did
**not** add one.

## 4. What cloud assistance is actually useful

| Capability | Model | Use in Echolyra |
|---|---|---|
| Numeric reasoning over echo timings, candidate layouts, diagnostics | `muse-wonder-1.0` (new default for geometry review); `muse-spark-1.3-contributor` fallback | **Implemented**: `POST /api/geometry/review` sends only allowlisted numeric diagnostics; live test returned a correct "layouts are ambiguous — move a measured distance and repeat" recommendation |
| Situation reports for events | `muse-spark-1.3-contributor` | Existing live path |
| Object boxes/masks from camera images or video | `sam-3.1` | Possible **only if the user opts into camera/video**; not used by sound-only path |
| Visual/video understanding (objects/scene) | `muse-wonder-1.0` (video + embedded audio transcription) | Same camera/video caveat |
| Artistic concept rendering | `muse-image-1.0` | Possible illustration from numeric diagnostics, never measurement |
| Voice commands/rules | `muse-voice-transcribe-1.0` | Existing |

## 5. Privacy consequences

- No probe or event recording is sent to Meta by any shipped path.
- Geometry review sends at most three candidate layouts (dimensions/fit), 64 echo delay/
  strength pairs and counts; no audio, room name, file path, mesh, or coordinates.
- Staging (optional) sends only dimensions + distance-only candidates; no audio.
- Contributor mode (`muse-spark-1.3-contributor`) may train on submitted context; Muse Wonder is
  Standard mode (not contributor training), but is still a cloud request the user explicitly
  triggers.
- If the user opts into a future camera/video assist, images/video go to Meta; that is a distinct
  consent and not part of the sound-only path.

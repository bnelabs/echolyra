**Sound-only 3D room estimates**

Echolyra's **3D Room** tab explores whether early acoustic echoes support a
rectangular room shell. It uses the phone's speaker and microphone, without a
camera, LiDAR, supplied room dimensions, or an image-generated room. It is a
research feature: it estimates a simple rectangular layout from recorded echoes.
It does not replace a room survey or reconstruct the contents of a furnished room.

The ordinary room fingerprint/RT60 feature is separate. Reverberation time alone
does not determine room dimensions and is not used as a substitute for geometry.

**Capture and interpretation**

Use the existing app's configured backend, then open **3D Room**. Keep the phone
stationary and maintain its orientation while it records repeated known probe
sweeps. A quiet room with the phone away from nearby obstructions is preferable.
The app submits the recordings to the numerical reconstruction endpoint. If too
few usable echoes repeat, or the recordings do not narrow down a room layout, the
app explains how to try another recording. It does not display made-up dimensions.

When a layout is available, inspect its estimated six-face box. The app may show
more than one layout if the same measurements fit several shapes. Axis names are arbitrary: a mono recording does not tell
the viewer which direction is north, which face is a particular wall, or which
face is the real floor. Permutations and mirror images can describe equivalent
acoustic configurations. There are no inferred furniture meshes, object labels,
textures, windows, doors, or material-specific absorption measurements.

**What the numerical method assumes**

- Six rectangular-room boundaries with three orthogonal pairs of parallel faces.
- Approximately co-located sound source and receiver. A real phone's speaker and
  microphone separation, speaker directivity, frequency response, audio processing,
  and placement introduce error. No device-specific correction has been established.
- Early, distinguishable, approximately specular reflections of the known sweep.
  Furnishings, scattering, overlapping reflections, background noise, and missing
  wall echoes can break these assumptions.

For the ideal co-located model, first-order round-trip delay to a face is
`2 × distance / speed_of_sound`. Opposing-face delays sum to the round-trip delay
across that room axis. A reflection involving perpendicular faces has delay
`sqrt(delay_a² + delay_b²)`. The solver tests echo assignments against these
relationships and reports timing-fit/support diagnostics. A fit residual or a
support fraction is **not a calibrated confidence probability**. A small residual
can still reflect a wrong echo assignment or an incorrect room model.

The displayed 3D box comes from the numerical fit. The UI does not fill gaps in
the measurements using typical room dimensions or a language model's guess.

**Demonstration and real-room measurements**

The synthetic demonstration is explicitly labeled. Its known room generates
image-source echoes and a synthetic recording of the existing probe; reconstruction
then runs through the numerical pipeline. The demo establishes a controlled
implementation check. It does not establish accuracy on phone recordings.

The project's saved living-room measurements establish neither a surveyed room
shape nor a reconstruction accuracy number. A preliminary analysis of those probe
recordings did not produce a stable, sufficient set of labeled wall echoes. Do not
use the existing 90–92% event-recognition figures as geometry-reconstruction accuracy.
Real validation requires a room with independently measured reference dimensions,
repeat captures from separate sessions/positions, held-out echoes/captures, and
comparisons against incorrect alternative boxes. Report dimensional error, how often
another recording is needed, and how often several layouts remain possible.
Repetition alone cannot resolve every symmetry.

**Data path and optional Meta review**

The acoustic solver runs on the user's configured backend. Recorded audio is sent
from the phone to that backend for processing. The new geometry-review module does
not persist audio, invoke models automatically, or send recordings to Meta. This
does not change the existing app's other recording/debug paths or make them
feature-only uploads; see the existing backend's `DEBUG_CAPTURE` behavior.

Only the explicit **Ask Meta to review** action requests cloud advice. Before that
action, the app discloses that numerical acoustic diagnostics are sent to Meta and
that Contributor-mode content may be used for training. The advisor constructs a
fresh allowlisted payload containing at most three estimated dimension/fit summaries,
64 echo-delay/strength pairs, and recording/repeatability counts. It omits raw audio,
room names and IDs, mesh data, source text, file paths, sensor positions, and location
coordinates. Acoustic timings/dimensions can still describe characteristics of a
private room; choose this action only if that disclosure is acceptable.

The server uses its existing `META_API_KEY`, `META_BASE_URL`, and `META_MODEL_SPARK`
configuration; no key is embedded in the iOS app or documentation. The default model
is `muse-spark-1.3-contributor`. Contributor mode allows training on submitted content;
Standard mode (`muse-spark-1.3`) does not use content for training. See
[Meta's pricing/data-mode documentation](https://dev.meta.ai/docs/pricing-rate-limits).
Standard mode is not a promise of zero retention. No fallback silently changes the
model or data-use mode. To keep the recipient consistent with the app’s disclosure,
this optional review accepts only the official `https://api.meta.ai/v1` address
(with an optional trailing slash). A different backend API address disables this
review; the app’s other model clients are unaffected.

The model reviews limitations and proposes one additional acoustic measurement. It
cannot edit the scene, supply geometry, execute tools, approve a fit, or turn a
room estimate into a confirmed measurement. The input is processed as data; arbitrary
result strings are not forwarded. Missing configuration and provider failures
return a bounded, generic message. Review uses one request, finite network timeouts,
bounded output, and no disk cache. Provider exception details are not exposed.

**Development checks**

From `sprint/backend`, using the project's installed Python environment:

```sh
../../prototype/.venv/bin/python -B -m unittest discover -s tests -p 'test_geometry*.py' -v
```

Or from the `sprint` repository root:

```sh
PYTHONPATH=backend ../prototype/.venv/bin/python -B -m unittest discover -s backend/tests -p 'test_geometry*.py' -v
```

The advisor tests mock all HTTP and check sanitization, no-key and empty-measurement
behavior, malformed output, error redaction, one-request/no-retry behavior, and
preservation of the original numerical result. They perform no live API calls.

Related research demonstrates sound-only room inference under stated geometric and
measurement conditions; it does not certify this implementation:
[Yu and Kleijn, single-RIR geometry estimation](https://arxiv.org/abs/2301.09198),
[Dokmanić et al., acoustic echoes and room shape](https://pmc.ncbi.nlm.nih.gov/articles/PMC3725100/).

# What math is actually running in the 3D scan?

A plain-language audit of the current pipeline, what each step uses, and how it compares with
state-of-the-art room-inference research. **Bottom line: this is a rigorous classical
physics/signal-processing pipeline with robust nonlinear fitting — not modern learned/SLAM SOTA.**

## 1. Capture → impulse response (FFT is central here)

1. The phone plays a known **logarithmic sine sweep** (250 Hz–16 kHz, 3 s, 48 kHz).
2. The recording is deconvolved with the **Farina inverse sweep**:
   `h = fftconvolve(recording, sweep⁻¹)` — a matched-filter/FFT convolution, O(N log N).
3. The direct path is located by the maximum of |h|; the impulse response (RIR) is cropped and
   mean-removed.
4. Echo detection: band-pass 2–8 kHz (Butterworth SOS), analytic envelope via the **Hilbert
   transform**, peak picking with a prominence/noise threshold, then a **repeatability
   clustering** step across the three sweeps (one peak per capture per cluster; median delay).

So FFT is used for deconvolution and filtering, not for "understanding" geometry.

## 2. Echo geometry (image-source model)

For a shoebox room with a co-located source/receiver, first-order reflection delays `t_i` satisfy:

- Opposing walls from the same axis: `t_i + t_j = 2·L_axis / c`
- Perpendicular walls: `t_ij = hypot(t_i, t_j)`

The solver searches over opposing-wall pairs whose sum has a matching observed echo, then
combination of three such pairs (triplet) and checks all 12 perpendicular second-order
identities. Dimension = `(t_i + t_j)·c/2`. This is the classical **image-source method** used in
Dokmanić et al. (PNAS 2013) and related room-geometry work — but our implementation is a bounded
combinatorial search with hard gates, not the SOTA learned/robust formulations.

**Added now:** a robust nonlinear **least-squares refinement** of each accepted layout. The
combinatorial search finds the basin; then `scipy.optimize.least_squares` with a soft-L1 loss
jointly refines dimensions and sensor position by matching predicted first/second-order delays to
observed echoes. This is the standard local inverse-problem solve around a good initialization.

## 3. Multi-position walk scan (Hough / multilateration)

Each pose gives distance measurements: a reflector at distance `r` lies on a circle of radius
`r` around that pose. Echo circles are rasterized on a 2D grid; intersections supported by most
poses become reflector candidates (Hough-style voting). This avoids having to match individual
echoes across captures. Persistent = all poses; unstable = partial support (movement/occlusion).
Poses now use **pedometer-measured step distance** (fallback 0.6 m), and rotation-only scans are
rejected.

## 4. Uncertainty logic

- strict shoebox fit → "measured shell"
- clutter-guarded partial fit (coverage ≥48%/65%, spacing/decay plausibility) → "low-confidence
  shell — verify"
- otherwise → honest refusal; dense random clutter is rejected (unit-tested)
- no calibrated dimension-accuracy claim; fit residual/support are timing diagnostics only

## 5. How this compares to SOTA

| Component | Echolyra now | SOTA examples | Gap |
|---|---|---|---|
| Echo detection | hand-tuned matched filter + peaks | learned echo detection / graph-based labeling (dEchorate training) | large |
| Echo labeling | exhaustive pair/triplet search with gates | graph assignment / learned association (RGI-Net, data-driven reflectors) | large |
| Geometry inversion | shoebox + robust least squares | learned 3D RGI incl. hidden first-order reflections; non-convex room inference | moderate |
| Pose | pedometer distance; instructed L-path | IMU trajectory + factor-graph SLAM + loop closure (ZA-SLAM, TMC 2024) | large |
| Directivity | uncompensated | device-specific calibration | moderate |
| Ground truth | synthetic + real captures, no tape truth | calibrated datasets (dEchorate), surveyed rooms | moderate |

References: [dEchorate](https://github.com/Chutlhu/dEchorate) ·
[RGI-Net](https://paperswithcode.com/paper/rgi-net-3d-room-geometry-inference-from-room/review/) ·
[handheld acoustic SLAM](https://dl.acm.org/doi/abs/10.1109/TMC.2023.3323393) ·
[ZA-SLAM](https://dl.acm.org/doi/abs/10.1145/3812835.3814975) ·
[data-driven reflector detection](https://ieeexplore.ieee.org/document/10626611) ·
[device directivity](https://theses.hal.science/tel-05340575v1/file/main_hdr_deleforge.pdf) ·
full review in [RESEARCH_GEOMETRY.md](RESEARCH_GEOMETRY.md).

## 6. What "more SOTA" would concretely mean

1. Replace hand peaks with a **learned echo detector** trained on dEchorate annotations.
2. Replace exhaustive pairing with **graph-based echo labeling** or a learned association model.
3. Add **IMU factor-graph trajectory + loop closure** so walk scans are registered by measured
   motion, enabling dense multi-pass reflector maps and separating furniture from people.
4. Optional **LiDAR/RoomPlan** on iPhone 12 Pro as local ground truth for evaluation and a
   precision setup mode.
5. Directivity calibration from measured captures.

None of these are claimed as done. The current system is honest about its uncertainty and
refuses rather than inventing a room.

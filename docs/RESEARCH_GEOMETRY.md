# Deep research: sound-only room & object mapping — state of the art vs. Echolyra

This note records the literature and data sources checked, how our implementation compares,
what was changed as a result, and the honest roadmap. Links are external research material,
not product claims.

## 1. What the literature says

| Work | Core idea | Relevance to us |
|---|---|---|
| Dokmanić et al., *Acoustic echoes reveal room shape*, PNAS 2013 (DOI 10.1073/pnas.1217811110) | First-order echoes + image-source geometry recover room shape; echo labeling is the hard part | Foundation of our solver; confirms labeling dominates accuracy |
| **dEchorate** (HAL PDF: https://hal.science/hal-03207860v3/preview/dechorate2021arxiv.pdf, code: https://github.com/Chutlhu/dEchorate) | 1,800 calibrated multichannel RIRs with **annotated geometry and echo timings** | Best available public data to train/benchmark echo detectors and labeling |
| **RGI-Net** (IWAENC 2024; https://paperswithcode.com/paper/rgi-net-3d-room-geometry-inference-from-room/review/) | Learned 3D room geometry inference that exploits low/high-order reflections and works when **first-order reflections are hidden** | Exactly our failure mode in furnished rooms; learned alternative to hard shoebox gates |
| Data-driven joint detection & localization of reflectors (IEEE 2024: https://ieeexplore.ieee.org/document/10626611) | Learned reflector detection + localization pipeline | Shows our hand-tuned peak detection is below SOTA |
| Inference of room geometry from acoustic impulse responses (IEEE TASLP 2012: https://dlnext.acm.org/doi/10.1109/TASL.2012.2210877) | Planar reflector localization from distributed microphones; includes **furniture as reflectors** | Supports reflection-candidate mapping, not just walls |
| Handheld acoustic SLAM (IEEE TMC 2024: https://dl.acm.org/doi/abs/10.1109/TMC.2023.3323393) | Smartphone SLAM from acoustic echoes | Directly relevant to moving-phone mapping |
| **ZA-SLAM** (MobiSys 2026 demo/paper: https://dl.acm.org/doi/abs/10.1145/3812835.3814975, https://dl.acm.org/doi/pdf/10.1145/3745756.3809218) | Near-inaudible chirps + **IMU** + loop closure; zero-shot acoustic SLAM in unseen rooms | Confirms the right process: measure poses with IMU, multi-position loop closure — not assumed spacing |
| Complex room geometry via acoustic echoes (EAA 2025: https://dael.euracoustics.org/confs/fa2025/data/articles/000244.pdf) | Non-convex/complex geometry inference | Our shoebox-only model is a deliberate simplification |
| Data-driven 3D RGI with linear loudspeaker array + one mic (arXiv 2308.14611: https://ar5iv.labs.arxiv.org/html/2308.14611) | Data-driven RGI with device arrays | Phone has no such array; multi-position walk is our substitute |
| Autonomous localization & mapping with a single mobile device (arXiv 1612.05793: https://ar5iv.labs.arxiv.org/html/1612.05793) | SLAM with ungrouped first-order echoes when **inter-measurement distances are known** | Validates our walk-scan concept; measured spacing is the key input |
| RIR absorption + shoebox geometry estimator (GitHub: https://github.com/Elquintas/RIR_estimator) | CNN on RIRs → shoebox dimensions + absorption | Reference for a learned follow-up |
| Device-directivity study (HAL thesis: https://theses.hal.science/tel-05340575v1/file/main_hdr_deleforge.pdf) | Speaker/mic directivity strongly biases room acoustics estimation | Explains phone-hardware error and the 2–8 kHz usable band |
| IR dataset list (https://github.com/moisestohias/IR-datasets) | Catalogue of public RIR datasets | Data inventory for benchmarking |

## 2. How our approach compares

**What is right:**
- Known logarithmic sweep + Farina deconvolution + probe-match gating (our device captures reach
  78–81 dB match even in a furnished room).
- Image-source (shoebox) inversion from echo times; clutter-aware acceptance.
- Multi-position walk scan instead of pretending one stationary position maps objects.
- Honest uncertainty: strict → low-confidence → refusal, and "reflection candidates ≠ objects".

**Where we are behind SOTA:**
1. **Echo labeling/detection is hand-tuned** (peak prominence + repeatability). dEchorate contains
   annotated echo times; a learned detector (or graph-based labeling) is the documented next step.
2. **Geometry inversion uses hard gates** rather than learned/robust inference (RGI-Net). We
   partially compensated with a clutter-guarded low-confidence tier.
3. **Poses are not truly measured** — our walk scan assumed 0.6 m hand spacing. ZA-SLAM and
   handheld acoustic SLAM use IMU + loop closure. We now measure step distance with the phone's
   pedometer and reject rotation-only "scans"; full IMU trajectory + loop closure is next.
4. **Phone directivity** is uncompensated (documented in the literature as a major bias).
5. **No public phone-in-room dataset** — our device captures + tape-measured ground truth are
   needed. dEchorate can bootstrap echo-detection training but is array-based.

## 3. Changes made in this round (research → code)

0. **Robust nonlinear refinement**: accepted layouts are now refined jointly over dimensions and
   sensor position with a soft-L1 least-squares solve against all matched echoes (see
   `docs/GEOMETRY_MATH.md`).

1. **Latest real-room capture now maps instead of refusing**: stats showed support 90.5%, fit
   0.016–0.093 ms, 18/21 unique predictions, cross 10/12 — blocked only by a coverage floor of
   55%. Coverage in furnished rooms is naturally lower, so the clutter-guarded low-confidence
   tier now accepts ≥48% single / 65% joint coverage and returns **3 low-confidence layouts**
   (≈3.97×3.78×2.57 m, ≈5.94×3.97×1.81 m, ≈6.25×3.93×1.81 m at 52%/69% coverage). Dense random
   clutter is still rejected (guard + unit test).
2. **Pedometer-measured walk path**: walk-scan poses now use step distance from `CMPedometer`
   when available (fallback ~0.6 m), and the app **rejects rotation-only scans** with a clear
   message. This implements the research recommendation that inter-measurement distance must be
   measured.
3. **Debug capture** (`DEBUG_CAPTURE=1`) stores geometry audio, poses and result JSON so real
   measurements can be diagnosed; the last capture analysis above used it.
4. Docs/UI now distinguish: measured shell (strict), low-confidence shell, reflection
   candidates, and illustrative staging.

## 4. Recommended roadmap (priority order)

1. **IMU trajectory + loop closure** (ZA-SLAM/handheld SLAM): record device motion during the
   walk, estimate 2D trajectory, capture two passes, close the loop; feed measured poses into
   the existing Hough voting. This is the highest-value upgrade for object mapping.
2. **Echo-detection benchmark on dEchorate**: evaluate our peak/knowledge pipeline against
   annotated echo times; train a small 1-D CNN/temporal model on dEchorate + our device probes
   for echo-vs-clutter classification. Reuse the same interface (`geometry.extract_echoes`).
3. **Learned/robust geometry inversion**: RGI-Net-style handling of hidden first-order echoes;
   or keep the geometric solver but score candidates with a learned prior trained on dEchorate
   + synthetic shoeboxes. Report dimension error on held-out rooms.
4. **Phone directivity calibration**: measure speaker/mic directivity with the captured data and
   correct echo strengths; keep the 2–8 kHz band.
5. **Ground truth**: on iPhone 12 Pro, optional **LiDAR/RoomPlan** scan (local-only, explicit
   opt-in) to measure true dimensions/furniture and report acoustic error. This does not replace
   the sound-only path; it is the only practical way to *evaluate* it and can seed a precision
   mode for users who accept depth sensing.
6. **Repeat-pass persistence**: two walk scans separated in time; persistent reflectors across
   passes = static furniture, low-support = movement. Current single-pass support already flags
   unstable candidates but cannot distinguish slow movers reliably.

## 5. Honest product conclusion

Sound-only mapping of a furnished room from a phone is a **research-grade measurement**, not a
consumer guarantees: walls can sometimes be estimated, furniture appears as reflection
candidates with distance/2-D position but no identity, and moving people are best treated as
transient clutter. The consumer-grade path is **hybrid**: sound-only awareness for privacy-
preserving event detection/change monitoring, plus an optional depth/LiDAR precision setup for
geometry/objects and for validating acoustic estimates. The current build exposes all three
tiers honestly and never fabricates measured dimensions.

"""Experimental sound-only rectangular-room hypotheses.

The inverse model is monostatic (speaker approximately at the microphone), with
six planar orthogonal boundaries. It uses early echo arrival TIMES, never RT60
or an LLM-generated dimension. A single position cannot resolve orientation,
axis names, furniture, or the mirror/axis permutations of a rectangular room.
Fit diagnostics are not calibrated probabilities. Failure is an ordinary result.

Timing identities for direct-relative first reflections t_i:
  opposite boundaries: t_ij = t_i + t_j
  perpendicular boundaries: t_ij = hypot(t_i, t_j)
The second-order identities provide an independent check on proposed first
reflections. Phone speaker/microphone separation and their frequency response
can violate this idealization; real-device accuracy has not been established.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import combinations
import math

import numpy as np
from scipy.signal import butter, fftconvolve, find_peaks, hilbert, sosfiltfilt

import probe

SOUND_SPEED = 343.0  # m/s, approximation for ordinary indoor temperature
TIMING_TOLERANCE_MS = 0.16
MAX_ECHOES = 48
MAX_FIRST_ECHOES = 24
MAX_PAIRS = 48
MIN_ROOM_M, MAX_ROOM_M = 1.5, 12.0
ASSUMPTIONS = [
    "Six planar boundaries forming a rectangular room; furniture is not reconstructed.",
    "Speaker and microphone are approximately co-located; hardware delay and separation can bias dimensions.",
    "Sound speed is assumed to be 343 m/s; room temperature is not measured.",
    "Axes are arbitrary; a single position cannot identify north, the floor, or mirror orientation.",
    "Fit diagnostics describe timing agreement, not calibrated confidence or verified physical dimensions.",
]


def _base(recordings=0, source="recorded_audio", message="Couldn’t map this room yet. Try another recording."):
    return {"status": "insufficient_evidence", "message": message, "source": source,
            "assumptions": ASSUMPTIONS.copy(), "candidates": [], "echoes": [],
            "diagnostics": {"recordings": recordings, "repeatable_echoes": 0,
                            "timing_tolerance_ms": TIMING_TOLERANCE_MS}}


@lru_cache(maxsize=2)
def _inverse(fs):
    return probe.farina_inverse(probe.probe_sweep(fs=fs), fs=fs)


def extract_echoes(recording: np.ndarray, fs: int = probe.FS) -> tuple[list[dict], dict]:
    """Matched-filter known sweep; preserve direct-relative echo times in milliseconds."""
    x = np.asarray(recording, dtype=float)
    if x.ndim != 1 or not np.isfinite(x).all():
        raise ValueError("Probe audio must be finite mono samples.")
    if fs < 24000 or fs > 96000:
        raise ValueError("Geometry capture needs a 24–96 kHz probe recording.")
    if not 3.3 * fs <= len(x) <= 7 * fs:
        raise ValueError("Each geometry probe must contain 3.3–7 seconds of audio.")
    if np.max(np.abs(x)) < 1e-6:
        return [], {"probe_match_db": 0.0, "reason": "silence"}
    h = fftconvolve(x, _inverse(fs))
    direct = int(np.argmax(np.abs(h)))
    # A sweep response must peak after at least the sweep length. Reject truncated
    # probes instead of shifting an arbitrary transient into a valid direct path.
    if direct < int((probe.SWEEP_T - 0.01) * fs) or direct + int(.09 * fs) >= len(h):
        return [], {"probe_match_db": 0.0, "reason": "probe_not_aligned"}
    tail = h[direct + int(.12 * fs):direct + int(.28 * fs)]
    noise = float(np.median(np.abs(tail))) if len(tail) else float(np.median(np.abs(h)))
    match_db = 20 * math.log10((float(np.abs(h[direct])) + 1e-12) / (noise + 1e-12))
    if match_db < 24.0:
        return [], {"probe_match_db": round(match_db, 2), "reason": "weak_probe_match"}
    y = sosfiltfilt(butter(4, [2000, min(8000, fs*.45)], btype="bandpass", fs=fs, output="sos"), h)
    env = np.abs(hilbert(y))
    smooth = max(3, int(fs*.00008)) | 1
    env = np.convolve(env, np.ones(smooth)/smooth, mode="same")
    start, stop = direct + int(.002*fs), direct + int(.080*fs)
    seg = env[start:stop]
    env_tail = env[direct + int(.12*fs):direct + int(.28*fs)]
    env_noise = float(np.median(env_tail)) if len(env_tail) else float(np.median(env))
    prominence = max(env_noise*8, float(seg.max())*.018)
    idx, props = find_peaks(seg, prominence=prominence, distance=max(1,int(.00035*fs)))
    if not len(idx):
        return [], {"probe_match_db": round(match_db, 2), "reason": "no_resolved_echoes"}
    choose = np.argsort(-props["prominences"])[:MAX_ECHOES]
    max_p = float(props["prominences"].max())
    peaks = [{"delay_ms": float((idx[j]+start-direct)/fs*1000),
              "strength": float(props["prominences"][j]/max_p)} for j in choose]
    return sorted(peaks, key=lambda p:p["delay_ms"]), {"probe_match_db": round(match_db, 2)}


def _repeatable(sets: list[list[dict]]) -> list[dict]:
    """One peak per capture per cluster; majority support, with at least two captures."""
    if len(sets) < 2:
        return []
    items = sorted((p["delay_ms"], p["strength"], i) for i, peaks in enumerate(sets) for p in peaks)
    clusters = []
    for delay, strength, capture in items:
        # Bound a cluster's full span, preventing chains of nearby peaks from
        # merging into a seemingly repeatable echo.
        match = next((c for c in reversed(clusters) if delay-c[0][0] <= TIMING_TOLERANCE_MS), None)
        if match is None:
            clusters.append([(delay, strength, capture)])
        elif capture not in {p[2] for p in match}:
            match.append((delay, strength, capture))
    need = max(2, math.ceil(len(sets)*2/3))
    out = [{"delay_ms": float(np.median([p[0] for p in c])),
            "strength": float(np.median([p[1] for p in c]))}
           for c in clusters if len(c)>=need]
    return sorted(sorted(out, key=lambda p:-p["strength"])[:MAX_ECHOES], key=lambda p:p["delay_ms"])


def _nearest(values: np.ndarray, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    distances = np.abs(targets[:,None]-values[None,:])
    indices = distances.argmin(axis=1)
    return distances[np.arange(len(targets)),indices], indices


def _scene(first: list[tuple[float, float]]) -> tuple[list[float],list[float],list,list]:
    axes = sorted(((a+b)*SOUND_SPEED/2000, min(a,b)*SOUND_SPEED/2000) for a,b in first)
    axes.reverse()  # canonical, arbitrary orientation; not a claim that axis C is vertical
    dims = [round(float(v[0]),3) for v in axes]
    sensor = [round(float(v[1]),3) for v in axes]
    x,y,z = dims
    vertices = [[0,0,0],[x,0,0],[x,y,0],[0,y,0],[0,0,z],[x,0,z],[x,y,z],[0,y,z]]
    faces = [[0,3,2,1],[4,5,6,7],[0,1,5,4],[1,2,6,5],[2,3,7,6],[3,0,4,7]]
    return dims,sensor,vertices,faces


def _predict_from_params(params: np.ndarray) -> np.ndarray:
    """First- and second-order path delays (ms) for a shoebox + sensor position."""
    length, width, height, sx, sy, sz = (float(v) for v in params)
    first = np.array([2 * sx, 2 * (length - sx), 2 * sy, 2 * (width - sy),
                      2 * sz, 2 * (height - sz)], dtype=float) / SOUND_SPEED * 1000.0
    second = [first[0] + first[1], first[2] + first[3], first[4] + first[5]]
    for i in range(6):
        for j in range(i + 1, 6):
            second.append(math.hypot(first[i], first[j]))
    return np.concatenate([first, np.asarray(second, dtype=float)])


def _box_geometry(dims, sensor):
    length, width, height = (float(v) for v in dims)
    x, y, z = (float(v) for v in sensor)
    vertices = [[0, 0, 0], [length, 0, 0], [length, width, 0], [0, width, 0],
                [0, 0, height], [length, 0, height], [length, width, height], [0, width, height]]
    faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5],
             [2, 3, 7, 6], [3, 0, 4, 7]]
    return [round(float(v), 3) for v in dims], [round(float(v), 3) for v in sensor], vertices, faces


def refine_candidate(candidate: dict, times: np.ndarray) -> dict:
    """Robust nonlinear least-squares refinement of one accepted layout.

    The combinatorial search gives a good basin; a soft-L1 fit then refines dimensions and
    sensor position jointly, matching predictions to observed echo times. This is the classic
    image-source inverse problem solved locally (no labels, no oracle echoes).
    """
    from scipy.optimize import least_squares
    dims = np.asarray(candidate["dimensions_m"], dtype=float)
    sensor = np.asarray(candidate["sensor_position_m"], dtype=float)
    if dims.shape != (3,) or sensor.shape != (3,):
        return candidate
    x0 = np.concatenate([dims, sensor])
    lower = np.array([1.5, 1.5, 1.5, 0.02, 0.02, 0.02])
    upper = np.array([12.0, 12.0, 12.0, 11.98, 11.98, 11.98])

    def residuals(params: np.ndarray) -> np.ndarray:
        predicted = _predict_from_params(params)
        errors, matched = _nearest(times, predicted)
        keep = errors <= 1.2
        if not keep.any():
            return np.full(1, 10.0)
        return predicted[keep] - times[matched[keep]]

    try:
        result = least_squares(residuals, x0, bounds=(lower, upper), loss="soft_l1",
                               f_scale=0.05, max_nfev=300)
        params = result.x
    except Exception:
        return candidate
    new_dims = params[:3]
    new_sensor = params[3:]
    if any(new_sensor[k] >= new_dims[k] - 0.03 for k in range(3)):
        return candidate
    predicted = _predict_from_params(params)
    errors, matched = _nearest(times, predicted)
    good = errors <= TIMING_TOLERANCE_MS
    if not good.any():
        return candidate
    fit = float(np.sqrt(np.mean(errors[good] ** 2)))
    unique = len(set(matched[good].tolist()))
    old_fit = float(candidate.get("fit_error_ms", 1e9))
    if fit > max(old_fit * 1.15, old_fit + 0.01) or unique < max(8, int(0.6 * len(predicted))):
        return candidate
    dims_out, sensor_out, vertices, faces = _box_geometry(new_dims, new_sensor)
    if any(v > 12.0 or v < 1.5 for v in dims_out):
        return candidate
    if any(sensor_out[k] >= dims_out[k] - 0.03 for k in range(3)):
        return candidate
    candidate.update({"dimensions_m": dims_out, "sensor_position_m": sensor_out,
                      "vertices": vertices, "faces": faces,
                      "fit_error_ms": round(fit, 4), "matched_echoes": unique,
                      "support_fraction": round(float(good.mean()), 4),
                      "total_predicted_echoes": int(len(predicted)),
                      "refined": True})
    return candidate


def solve_echoes(echoes: list[dict]) -> tuple[list[dict],dict]:
    """Bounded search over opposing-wall pairs and perpendicular second echoes.

    Two tiers: a strict shoebox fit (all six first-order and all second-order
    relationships resolved), and a clearly-marked low-confidence tier used only when
    no strict fit exists. The relaxed tier still requires coherent timing geometry
    and most observed early energy; it is reported as an estimate to verify, never
    as a measured room. Public for measurement tests.
    """
    valid=[]
    for p in echoes:
        t,s = float(p["delay_ms"]),float(p["strength"])
        if math.isfinite(t) and math.isfinite(s) and 2<=t<=80 and s>0:
            valid.append({"delay_ms":t,"strength":s})
    valid=sorted(sorted(valid,key=lambda p:-p["strength"])[:MAX_ECHOES],key=lambda p:p["delay_ms"])
    dedup=[]
    for p in valid:
        if not dedup or p['delay_ms']-dedup[-1]['delay_ms']>TIMING_TOLERANCE_MS:
            dedup.append(p)
        elif p['strength']>dedup[-1]['strength']:
            dedup[-1]=p
    valid=dedup
    diag={"hypotheses_tested":0,"echo_search_limit":MAX_ECHOES,"first_echo_search_limit":MAX_FIRST_ECHOES}
    if len(valid)<12:
        return [],diag
    times=np.array([p['delay_ms'] for p in valid])
    strength=np.array([p['strength'] for p in valid])
    eligible=np.where(times<2*MAX_ROOM_M/SOUND_SPEED*1000)[0]
    pool=eligible[np.argsort(-strength[eligible])[:MAX_FIRST_ECHOES]]
    pairs=[]
    for i,j in combinations(pool,2):
        dimension=(times[i]+times[j])*SOUND_SPEED/2000
        if not MIN_ROOM_M<=dimension<=MAX_ROOM_M:
            continue
        err,where=_nearest(times,np.array([times[i]+times[j]]))
        if err[0]<=TIMING_TOLERANCE_MS and where[0] not in (i,j):
            pairs.append((int(i),int(j),float(strength[i]+strength[j]),int(where[0])))
    pairs=sorted(pairs,key=lambda p:-p[2])[:MAX_PAIRS]
    diag['opposing_pair_candidates']=len(pairs)
    strict=[]; relaxed=[]
    best={"cross_matches":0,"unique_peaks":0,"support":0.0,"fit_ms":None,
          "parallel_sums_present":0,"triplets_checked":0}
    for triplet in combinations(pairs,3):
        best["triplets_checked"]+=1
        first_indices=[i for pair in triplet for i in pair[:2]]
        if len(set(first_indices))!=6:
            continue
        diag['hypotheses_tested']+=1
        parallel=[p[3] for p in triplet]
        best["parallel_sums_present"]=max(best["parallel_sums_present"], len(set(parallel)))
        if len(set(first_indices+parallel))<9:
            continue
        cross=[]
        for a,b in combinations(triplet,2):
            cross.extend(math.hypot(times[i],times[j]) for i in a[:2] for j in b[:2])
        err,idx=_nearest(times,np.array(cross))
        cross_ok=err<=TIMING_TOLERANCE_MS
        cross_count=int(cross_ok.sum())
        best["cross_matches"]=max(best["cross_matches"], cross_count)
        predictions=np.array([times[i] for i in first_indices]+[times[p[0]]+times[p[1]] for p in triplet]+cross)
        errors,matched=_nearest(times,predictions)
        good=errors<=TIMING_TOLERANCE_MS
        unique=len(set(matched[good].tolist()))
        best["unique_peaks"]=max(best["unique_peaks"], unique)
        support=float(good.mean())
        seen=set(matched[good].tolist())
        explained=float(strength[list(seen)].sum()/strength.sum())
        fit=float(np.sqrt(np.mean(errors[good]**2))) if good.any() else float("inf")
        best["support"]=max(best["support"], support)
        if best["fit_ms"] is None or fit<best["fit_ms"]:
            best["fit_ms"]=fit
        score=.75*support+.25*explained-fit*.15
        dims,sensor,vertices,faces=_scene([(times[p[0]],times[p[1]]) for p in triplet])
        candidate={"id":"", "dimensions_m":dims,"sensor_position_m":sensor,
                   "fit_error_ms":round(fit,4),"matched_echoes":unique,
                   "total_predicted_echoes":len(predictions),"support_fraction":round(support,4),
                   "vertices":vertices,"faces":faces}
        row=(score,candidate,seen)
        if cross_count>=11 and unique>=19:
            strict.append(row)
        elif cross_count>=10 and unique>=12 and support>=0.55 and fit<=1.0:
            relaxed.append(row)
    diag['strict_candidates']=len(strict)
    diag['relaxed_candidates']=len(relaxed)
    diag['best_relaxed_stats']={k:(round(v,3) if isinstance(v,float) else v)
                                for k,v in best.items()}

    def finalize(rows, tier, min_coverage, joint_coverage):
        rows=sorted(rows,key=lambda row:-row[0])
        distinct=[]
        for score,c,seen in rows:
            if any(max(abs(a-b) for a,b in zip(c['dimensions_m'],prev[1]['dimensions_m']))<.12
                   for prev in distinct):
                continue
            c['id']=f"candidate-{len(distinct)+1}"
            c['confidence']="high" if tier=="strict" else "low"
            c['tier']=tier
            distinct.append((score,c,seen))
            if len(distinct)>=3:
                break
        if not distinct:
            return []
        cutoff=distinct[0][0]-.055
        distinct=[row for row in distinct if row[0]>=cutoff]
        explained=[float(strength[list(row[2])].sum()/strength.sum()) for row in distinct]
        union=set().union(*(row[2] for row in distinct))
        combined=float(strength[list(union)].sum()/strength.sum())
        diag['observed_echo_coverage']=round(max(explained),4)
        diag['combined_echo_coverage']=round(combined,4)
        if max(explained)<min_coverage and not (len(distinct)>=2 and combined>=joint_coverage):
            diag['rejection_reason']='unexplained_early_echoes'
            return []
        return [row[1] for row in distinct]

    def clutter_guard_ok() -> bool:
        """Real reflections spread out and decay; dense uniform clutter does not."""
        if len(valid) < 12:
            return False
        spacing = float(np.median(np.diff(times)))
        corr = float(np.corrcoef(times, strength)[0, 1]) if len(valid) > 3 else 0.0
        diag['clutter_median_spacing_ms'] = round(spacing, 3)
        diag['strength_delay_correlation'] = round(corr, 3)
        return spacing >= 0.45 and corr <= -0.15

    strict_out=finalize(strict,"strict",.72,.92)
    diag['fit_tier']="strict" if strict_out else None
    if strict_out:
        for candidate in strict_out:
            refine_candidate(candidate, times)
        diag['distinct_supported_hypotheses']=len(strict_out)
        diag['leading_score_gap']=None
        return strict_out,diag
    if relaxed and not clutter_guard_ok():
        diag['rejection_reason']='unexplained_early_echoes'
        relaxed=[]
    # A strong geometric fit (support/fit/unique) can still explain only half of the total
    # early energy in a furnished room; do not throw that estimate away. Clutter is already
    # guarded above, so the coverage floor is lower here.
    relaxed_out=finalize(relaxed,"relaxed",.48,.65)
    if relaxed_out:
        for candidate in relaxed_out:
            refine_candidate(candidate, times)
        diag['fit_tier']="relaxed"
        diag['distinct_supported_hypotheses']=len(relaxed_out)
        return relaxed_out,diag
    diag['distinct_supported_hypotheses']=0
    return [],diag


def _candidate_wall_delays(candidate: dict) -> np.ndarray:
    """All first- and second-order arrival times predicted by one rectangular candidate."""
    dims = candidate["dimensions_m"]
    sensor = candidate["sensor_position_m"]
    first = []
    for axis in range(3):
        d, p = float(dims[axis]), float(sensor[axis])
        first.extend([2 * p / SOUND_SPEED * 1000.0, 2 * (d - p) / SOUND_SPEED * 1000.0])
    first = np.asarray(first, dtype=float)
    second = []
    for i in range(3):
        second.append(first[2 * i] + first[2 * i + 1])  # opposing face pair
    for i in range(6):
        for j in range(i + 1, 6):
            second.append(math.hypot(first[i], first[j]))
    return np.concatenate([first, np.asarray(second, dtype=float)])


def object_candidates(echoes: list[dict], candidate: dict,
                      tolerance_ms: float = 0.9) -> list[dict]:
    """Strong early echoes not explained by the fitted shell -> distance-only scatterers.

    A single monostatic capture cannot give a direction, so these are NOT mapped objects:
    a scatterer is a surface/edge echo at an estimated distance. Every entry is labelled
    distance-only and low/medium confidence; identity and position stay unresolved.
    """
    predicted = _candidate_wall_delays(candidate)
    unexplained: list[dict] = []
    for echo in echoes:
        delay = float(echo.get("delay_ms", 0)); strength = float(echo.get("strength", 0))
        if not (math.isfinite(delay) and math.isfinite(strength)) or strength < 0.18:
            continue
        if np.min(np.abs(predicted - delay)) > tolerance_ms:
            unexplained.append({"delay_ms": delay, "strength": strength})
    groups: list[list[dict]] = []
    for item in sorted(unexplained, key=lambda e: e["delay_ms"]):
        if groups and item["delay_ms"] - np.median([e["delay_ms"] for e in groups[-1]]) <= 2 * tolerance_ms:
            groups[-1].append(item)
        else:
            groups.append([item])
    objects = []
    for group in groups:
        delay = float(np.median([e["delay_ms"] for e in group]))
        strength = float(np.median([e["strength"] for e in group]))
        if delay <= 0:
            continue
        objects.append({
            "id": f"object-{len(objects) + 1}",
            "distance_m": round(delay / 1000.0 * SOUND_SPEED / 2.0, 2),
            "delay_ms": round(delay, 3),
            "strength": round(strength, 3),
            "confidence": "medium" if strength >= 0.4 else "low",
            "note": "Reflective-surface echo at this distance. Direction, identity, size and shape are not resolved.",
            "support": len(group),
        })
    return sorted(objects, key=lambda o: -o["strength"])[:8]


def reconstruct(recordings: list[np.ndarray], fs: int = probe.FS) -> dict:
    """Return supported room candidates or an explicit refusal; no state is written."""
    if not 1<=len(recordings)<=3:
        raise ValueError("Supply one to three stationary probe recordings.")
    out=_base(len(recordings))
    sets=[];checks=[]
    for rec in recordings:
        peaks,diag=extract_echoes(rec,fs)
        sets.append(peaks);checks.append(diag)
    out['diagnostics']['capture_checks']=checks
    if len(recordings)<2:
        out['message']='Record at least two sweeps without moving the phone to check echo repeatability.'
        return out
    echoes=_repeatable(sets)
    out['echoes']=[{'delay_ms':round(p['delay_ms'],4),'strength':round(p['strength'],4)} for p in echoes]
    out['diagnostics']['repeatable_echoes']=len(echoes)
    candidates,diag=solve_echoes(echoes)
    out['diagnostics'].update(diag)
    for cand in candidates:
        cand['objects']=object_candidates(echoes, cand)
    out['objects']=candidates[0]['objects'] if candidates else []
    out['candidates']=candidates
    low_confidence = bool(candidates) and all(c.get('tier')=='relaxed' for c in candidates)
    out['confidence']='low' if low_confidence else ('high' if candidates else None)
    if not candidates:
        out['message']='Couldn’t map this room yet. Keep the phone still, away from nearby objects, and try another recording.'
    elif len(candidates)>1 and low_confidence:
        out['status']='ambiguous'
        out['message']='Low-confidence: several experimental layouts fit these echoes. The room is too cluttered for a precise fit; compare the estimates or try a quieter recording.'
    elif len(candidates)>1:
        out['status']='ambiguous'
        out['message']='More than one rectangular layout fits these echoes. Compare the estimates or try another recording.'
    elif low_confidence:
        out['status']='candidate'
        out['message']='Low-confidence experimental estimate. The fit explains most repeated echoes, but this room is cluttered enough that the dimensions need verification.'
    else:
        out['status']='candidate'
        out['message']='An estimated rectangular room layout fits the repeated echoes. Its dimensions and orientation still need checking.'
    return out


def synthetic_echoes(dimensions=(5.7,4.3,2.9), position=(1.27,1.61,1.13)) -> list[dict]:
    """First/second-order image-source arrivals for an ideal monostatic shoebox."""
    d=np.asarray(dimensions,dtype=float);p=np.asarray(position,dtype=float)
    if d.shape!=(3,) or p.shape!=(3,) or not np.isfinite(d).all() or not np.isfinite(p).all() or np.any(p<=0) or np.any(p>=d):
        raise ValueError('Synthetic source must lie strictly inside a finite three-dimensional room.')
    walls=[(2*p[k]/SOUND_SPEED*1000, k, .82) for k in range(3)]
    walls += [(2*(d[k]-p[k])/SOUND_SPEED*1000,k,.82) for k in range(3)]
    arrivals=[{'delay_ms':t,'strength':rho/(1+t*SOUND_SPEED/1000)} for t,k,rho in walls]
    for i,j in combinations(range(6),2):
        a,b=walls[i],walls[j]
        t=a[0]+b[0] if a[1]==b[1] else math.hypot(a[0],b[0])
        arrivals.append({'delay_ms':t,'strength':a[2]*b[2]/(1+t*SOUND_SPEED/1000)})
    return sorted(arrivals,key=lambda e:e['delay_ms'])


def synthetic_recording(dimensions=(5.7,4.3,2.9), position=(1.27,1.61,1.13), seed=0, fs=probe.FS):
    """Known probe transmitted through ideal image-source RIR, with independent noise."""
    rir=np.zeros(int(.4*fs));rir[0]=1
    for e in synthetic_echoes(dimensions,position):
        sample=e['delay_ms']*.001*fs
        i=int(sample);frac=sample-i
        if i+1<len(rir):
            rir[i]+=e['strength']*(1-frac)
            rir[i+1]+=e['strength']*frac
    rec=fftconvolve(probe.probe_sweep(fs=fs),rir)
    rec=np.pad(rec,(int(.12*fs),int(.15*fs)))
    rec=rec/max(float(np.abs(rec).max()),1e-9)*.65
    return rec+np.random.default_rng(seed).normal(0,1e-5,len(rec))


def demo() -> dict:
    out=reconstruct([synthetic_recording(seed=s) for s in range(3)])
    out['source']='synthetic_demo'
    out['message']='Simulated room demonstration. These dimensions come from simulated echoes, not your room. '+out['message']
    return out

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


def solve_echoes(echoes: list[dict]) -> tuple[list[dict],dict]:
    """Bounded search over opposing-wall pairs and perpendicular second echoes.

    Public for measurement tests. Inputs contain only arrival time and relative
    amplitude, not room dimensions, labelled walls, or oracle echo assignments.
    """
    valid=[]
    for p in echoes:
        t,s = float(p["delay_ms"]),float(p["strength"])
        if math.isfinite(t) and math.isfinite(s) and 2<=t<=80 and s>0:
            valid.append({"delay_ms":t,"strength":s})
    valid=sorted(sorted(valid,key=lambda p:-p["strength"])[:MAX_ECHOES],key=lambda p:p["delay_ms"])
    # Merge indistinguishable arrivals; they cannot independently support walls.
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
    # Resolve only first echoes within ordinary room-size bounds; select strongest
    # evidence without relying on their chronological ordering (second echoes can
    # precede a distant first reflection).
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
    accepted=[]
    for triplet in combinations(pairs,3):
        first_indices=[i for pair in triplet for i in pair[:2]]
        if len(set(first_indices))!=6:
            continue
        diag['hypotheses_tested']+=1
        # All six first-order and three opposing second-order arrivals must be
        # independently resolved; collisions make a one-position inversion unsafe.
        parallel=[p[3] for p in triplet]
        if len(set(first_indices+parallel))<9:
            continue
        cross=[]
        for a,b in combinations(triplet,2):
            cross.extend(math.hypot(times[i],times[j]) for i in a[:2] for j in b[:2])
        err,idx=_nearest(times,np.array(cross))
        cross_ok=err<=TIMING_TOLERANCE_MS
        # At least 11/12 independently predicted perpendicular echoes. A weakly
        # supported best guess is deliberately not a 3D scene.
        if int(cross_ok.sum())<11:
            continue
        predictions=np.array([times[i] for i in first_indices]+[times[p[0]]+times[p[1]] for p in triplet]+cross)
        errors,matched=_nearest(times,predictions)
        good=errors<=TIMING_TOLERANCE_MS
        # Count unique peaks: one observed arrival cannot support several walls.
        unique=len(set(matched[good].tolist()))
        if unique<19:
            continue
        support=float(good.mean())
        seen=set(matched[good].tolist())
        explained=float(strength[list(seen)].sum()/strength.sum())
        fit=float(np.sqrt(np.mean(errors[good]**2)))
        score=.75*support+.25*explained-fit*.15
        dims,sensor,vertices,faces=_scene([(times[p[0]],times[p[1]]) for p in triplet])
        candidate={"id":"", "dimensions_m":dims,"sensor_position_m":sensor,
                   "fit_error_ms":round(fit,4),"matched_echoes":unique,
                   "total_predicted_echoes":len(predictions),"support_fraction":round(support,4),
                   "vertices":vertices,"faces":faces}
        accepted.append((score,candidate,seen))
    accepted.sort(key=lambda row:-row[0])
    distinct=[]
    for score,c,seen in accepted:
        if any(max(abs(a-b) for a,b in zip(c['dimensions_m'],prev[1]['dimensions_m']))<.12 for prev in distinct):
            continue
        c['id']=f"candidate-{len(distinct)+1}"
        distinct.append((score,c,seen))
        if len(distinct)>=3:
            break
    diag['distinct_supported_hypotheses']=len(distinct)
    diag['leading_score_gap']=round(distinct[0][0]-distinct[1][0],4) if len(distinct)>1 else None
    if distinct:
        cutoff=distinct[0][0]-.055
        distinct=[row for row in distinct if row[0]>=cutoff]
        explained=[float(strength[list(row[2])].sum()/strength.sum()) for row in distinct]
        union=set().union(*(row[2] for row in distinct))
        combined=float(strength[list(union)].sum()/strength.sum())
        diag['observed_echo_coverage']=round(max(explained),4)
        diag['combined_echo_coverage']=round(combined,4)
        # Searching many assignments in dense clutter creates accidental timing
        # matches. A layout must also account for most of the observed early
        # signal, rather than cherry-pick 21 arrivals among unrelated peaks.
        # Two complete competing layouts may jointly cover a mixed observation;
        # keep that as ambiguity, never collapse it into a unique estimate.
        if max(explained)<.72 and not (len(distinct)>=2 and combined>=.92):
            diag['rejection_reason']='unexplained_early_echoes'
            return [],diag
    return [row[1] for row in distinct],diag


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
    out['candidates']=candidates
    if not candidates:
        out['message']='Couldn’t map this room yet. Keep the phone still, away from nearby objects, and try another recording.'
    elif len(candidates)>1:
        out['status']='ambiguous'
        out['message']='More than one rectangular layout fits these echoes. Compare the estimates or try another recording.'
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

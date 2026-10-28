"""Multi-node fusion for RoomSense.

One phone hears an event and guesses what/where. Several phones (an old iPhone, a Mac,
a tablet) hearing the same event can decide *where* much better, because the level and
spectral attenuation pattern across nodes is a spatial fingerprint.

Input: recent node reports, each {node_id, room_name, room_confidence, event_label,
event_confidence, level_db, snr_db, ts}. Output: fused event + room + confidence, plus
which node dominated and the attenuation pattern. The same house-level Bayes rule works
for 2 nodes (this demo) or many (product).
"""
from __future__ import annotations

import math
import time

# room -> node mapping is learned by enrollment; here each node declares its room.
LEVEL_WEIGHT = 1.0
CONF_WEIGHT = 1.0
DECAY_WEIGHT = 1.5     # match the event's early decay to each room's active-probe RT60


def _softmax(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    m = max(scores.values())
    exps = {k: math.exp(v - m) for k, v in scores.items()}
    z = sum(exps.values())
    return {k: v / z for k, v in exps.items()}


def fuse(reports: list[dict], max_age_s: float = 10.0,
         room_probe: dict[str, float] | None = None) -> dict:
    """Fuse reports from multiple nodes that heard the same event."""
    now = time.time()
    live = [r for r in reports if abs(now - float(r.get("ts", now))) <= max_age_s]
    live = [r for r in live if float(r.get("snr_db", 30)) >= 8.0]
    if not live:
        return {"event_label": None, "room_name": None, "confidence": 0.0,
                "n_nodes": 0, "reason": "no_live_reports"}

    # ---- where: combine node confidence, level, and active-probe decay consistency.
    # Each room's active probe measured its true RT60; for an impulsive event the early decay
    # rate the nodes hear (~60/RT60 dB/s) should match the *source* room's probe, even when the
    # loudest node is in an adjacent room.
    room_scores: dict[str, float] = {}
    event_decay = next((float(r["event_decay"]) for r in live
                        if r.get("event_decay") not in (None, 0)), None)
    for r in live:
        # If a node knows its own room (phone in the living room, laptop in the kitchen),
        # that is the candidate room it contributes; otherwise fall back to attribution.
        room = r.get("node_room") or r.get("room_name") or "unknown"
        level = float(r.get("level_db", -60.0))
        conf = float(r.get("room_confidence", 0.0))
        score = LEVEL_WEIGHT * (level + 60.0) / 20.0 + CONF_WEIGHT * conf * 2.0
        probe_rt = (room_probe or {}).get(room)
        if event_decay and probe_rt:
            expected = 60.0 / max(probe_rt, 0.05)   # decay rate implied by the probed RT60
            mismatch = abs(math.log(max(event_decay, 1.0) / max(expected, 1.0)))
            score += DECAY_WEIGHT * (1.0 - min(1.0, mismatch))
        room_scores[room] = max(room_scores.get(room, -1e9), score)
    room_p = _softmax(room_scores)
    best_room = max(room_p, key=room_p.get)

    # ---- what: confidence-weighted vote across nodes (Apple labels mapped upstream)
    event_scores: dict[str, float] = {}
    for r in live:
        label = r.get("event_label") or "unknown"
        if label == "unknown":
            continue
        w = max(0.1, float(r.get("event_confidence", 0.0))) * (1.0 + max(0.0, float(r.get("snr_db", 0))) / 40.0)
        event_scores[label] = event_scores.get(label, 0.0) + w
    event_p = _softmax(event_scores)
    best_event = max(event_p, key=event_p.get) if event_p else "unknown"

    # ---- agreement: nodes hearing the same event should share the class
    labels = [r.get("event_label") for r in live if r.get("event_label") not in (None, "unknown")]
    agreement = 0.0
    if labels:
        agreement = labels.count(best_event) / len(labels)
    confidence = round(float(room_p[best_room]) * (0.5 + 0.5 * agreement), 2)
    return {
        "event_label": best_event,
        "room_name": best_room,
        "confidence": confidence,
        "n_nodes": len(live),
        "agreement": round(agreement, 2),
        "room_posteriors": {k: round(v, 2) for k, v in sorted(room_p.items(), key=lambda kv: -kv[1])},
        "event_posteriors": {k: round(v, 2) for k, v in sorted(event_p.items(), key=lambda kv: -kv[1])},
        "probe_informed": bool(room_probe and event_decay),
        "event_decay_db_s": round(event_decay, 1) if event_decay else None,
        "nodes": [{"node_id": r.get("node_id"), "room": r.get("node_room") or r.get("room_name"),
                   "level_db": r.get("level_db"), "snr_db": r.get("snr_db"),
                   "event": r.get("event_label")} for r in live],
    }

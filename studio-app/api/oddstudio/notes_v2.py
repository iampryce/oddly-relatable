"""Video notes v2 (owner decision 2026-11-21, video-first): the video is the reference for staging, read as WORDS ONLY.

What changes from v1 (video_notes.py):
- Persistent people: each person in the video keeps one number ("person 1".."person 6") across all frames, so the
  cast can later be mapped person -> character (a suggestion the owner confirms; never applied automatically).
- Per-frame states from fixed lists, per person: position, pose (now with kneeling), facing (camera, away, left,
  right or another person), gesture (the rig's gestures + nod, head shake, phone to ear, hands together), emotion, and
  whether they are talking. Per frame: shot, camera, setting, furniture, time of day.
- Denser sampling: a Short at 1 frame per second (at most 60), a long episode at 1 frame every 2 s (at most 150), sent
  in batches of at most 50 frames. Each later batch repeats the previous batch's last frame with the people listed in
  words, so the numbering carries over; if the model renumbers them anyway, the overlap frame is used to map the
  numbers back (by position and pose).
- A cost cap (Settings > Video and visual analysis, default $0.50 per episode) checked before upload.
- The v1 ranges are still produced from the frames (the speaker is the one person talking), so the Reference plan,
  set proposal, staging and scene builders keep working unchanged; older v1 notes still load.

Never: names, faces, appearance, bodies, clothing, age, gender, ethnicity, brands, logos, on-screen text or dialogue.
Anything outside the lists is removed and counted. The frames and the video are deleted after analysis.
"""
from __future__ import annotations

import math

from . import video_notes as VN

VERSION = 2
EVERY = {"short": 1.0, "long": 2.0}          # s between sampled frames
CAP = {"short": 60, "long": 150}             # frames at most
BATCH = 50                                   # frames per vision call (later batches repeat one frame of overlap)
MAX_PEOPLE = 6
DEFAULT_CAP_USD = 0.50
OUT_PER_FRAME_V2 = 140                       # output tokens per frame (people are described per frame)
# estimate x factor from real runs: OpenAI measured 1.72x on the owner's 60 s test (2026-11-21: $0.0364 vs $0.0212);
# Anthropic not measured yet (the readout shows actual / estimated so it can be set from a real run)
CALIBRATION = {"openai": 1.7, "anthropic": 1.0}
NEUTRAL_HINT = 0.9                           # share of neutral (or missing) emotions that triggers the provider hint

POSES = VN.POSES                              # includes kneeling (shown in the plan as "will be skipped")
GESTURES = ("none", "open_palms", "point", "shrug", "arms_up", "head_scratch", "hands_on_hips", "hand_on_chest",
            "facepalm", "thumbs_up", "wave", "beat", "cross_arms", "hands_on_head", "nod", "head_shake", "phone_to_ear",
            "hands_together")
FACING_FIXED = VN.FACING_FIXED
FRAME_KEYS = {"frame", "shot", "camera", "setting", "furniture", "time", "view", "people"}
PERSON_KEYS = {"person", "position", "pose", "facing", "gesture", "emotion", "talking"}
SCENE_FIELDS = (("shot", VN.SHOTS), ("camera", VN.CAMERA), ("setting", VN.SETTINGS), ("furniture", VN.FURNITURE),
                ("time", VN.TIME_OF_DAY), ("view", VN.VIEWS))
PERSON_FIELDS = (("position", VN.POSITIONS), ("pose", POSES), ("gesture", GESTURES), ("emotion", VN.EMOTIONS))


# ------------------------------------------------------------------ sampling and cost
def frame_times(start: float, end: float, fmt: str = "short") -> list[float]:
    return VN.frame_times(start, end, EVERY.get(fmt, EVERY["short"]), CAP.get(fmt, CAP["short"]))


def batches(n: int, size: int = BATCH) -> list[list[int]]:
    """Frame indexes per call: [0..size-1], then each later batch starts with the previous batch's last frame."""
    if n <= 0:
        return []
    out, start = [], 0
    while True:
        end = min(n, start + size)
        out.append(list(range(start, end)))
        if end >= n:
            return out
        start = end - 1


def estimate(seconds: float, fmt: str, provider: str, model: str = "", cap_usd: float = DEFAULT_CAP_USD) -> dict:
    """Frames, calls, tokens and USD (an upper estimate from list prices) for `seconds` of video, and whether it fits
    under the cap."""
    n = len(frame_times(0.0, seconds, fmt))
    calls = batches(n)
    sent = sum(len(b) for b in calls)
    p = VN.PRICES.get(provider)
    if not p:
        return {"frames": n, "calls": len(calls), "configured": False, "cap_usd": cap_usd}
    tin = len(calls) * VN.PROMPT_TOKENS + sent * p["per_frame"]
    tout = len(calls) * VN.OUT_BASE + sent * OUT_PER_FRAME_V2
    usd = round((tin * p["in"] + tout * p["out"]) / 1e6 * CALIBRATION.get(provider, 1.0), 4)
    priced = model or p["model"]
    return {"frames": n, "calls": len(calls), "configured": True, "provider": provider, "model": priced,
            "input_tokens": tin, "output_tokens": tout, "usd": usd, "cap_usd": cap_usd, "within_cap": usd <= cap_usd,
            "note": "" if priced == p["model"] else f"priced as {p['model']}; {priced} may cost differently"}


def actual_usd(usages: list[dict]) -> float | None:
    """The calls' cost from the tokens the API reported (list prices); None when no usage was reported."""
    total, known = 0.0, False
    for u in usages:
        p = VN.PRICES.get(u.get("provider"))
        if p and u.get("input_tokens") is not None:
            total += ((u.get("input_tokens") or 0) * p["in"] + (u.get("output_tokens") or 0) * p["out"]) / 1e6
            known = True
    return round(total, 4) if known else None


# ------------------------------------------------------------------ the prompt
def describe_people(people: list[dict]) -> str:
    return "; ".join(f"person {p['person']}: " + ", ".join(p[k] for k in ("position", "pose") if p.get(k))
                     for p in people) or "nobody"


def prompt(times: list[float], carried: list[dict] | None = None) -> str:
    when = "; ".join(f"frame {i + 1} at {t:.1f} s" for i, t in enumerate(times))
    carry = (f"Frame 1 repeats the last frame of the previous batch, where the people were numbered: "
             f"{describe_people(carried)}. Keep exactly these numbers for the same people; a new person gets the next "
             "free number.\n") if carried else ""
    return (
        "You are helping stage an ORIGINAL 2D animated comedy scene. The frames come from a reference video that we "
        "will never copy. Describe only how the scene is staged and how people move, as numbered anonymous people.\n"
        f"Frames ({when}; seconds from the start of the part being used).\n{carry}"
        "Give EVERY person the SAME number in every frame they appear in (person 1 .. person 6), by where they are and "
        "what they do, never by how they look.\n"
        'Return JSON only: {"frames": [{"frame": 1, "shot": ..., "camera": ..., "setting": ..., "furniture": ..., '
        '"time": ..., "people": [{"person": 1, "position": ..., "pose": ..., "facing": ..., "gesture": ..., '
        '"emotion": ..., "talking": true}]}]}\nOne entry per frame, in order. Allowed values ONLY:\n'
        f"- shot: {', '.join(VN.SHOTS)}\n- camera: {', '.join(VN.CAMERA)}\n- setting: {', '.join(VN.SETTINGS)}\n"
        f"- furniture (the main piece in view): {', '.join(VN.FURNITURE)}\n- time: {', '.join(VN.TIME_OF_DAY)}\n"
        f"- view: {', '.join(VN.VIEWS)}. One room filmed from two angles (shot / reverse shot) is ONE setting: "
        "\"main side\" is the angle of the first frame, \"reverse side\" the opposite angle; side-on, overhead, or wide "
        "(both sides in view)\n"
        f"- position: {', '.join(VN.POSITIONS)}\n- pose: {', '.join(POSES)}\n"
        f"- facing: {', '.join(FACING_FIXED)}, or another person (e.g. \"person 2\")\n"
        f"- gesture: {', '.join(GESTURES)}\n- emotion: {', '.join(VN.EMOTIONS)}\n"
        "- talking: true when the person seems to be speaking in that frame, else false\n"
        "Never output names of real people, actors or characters, never describe faces, appearance, bodies, clothing, "
        "age, gender or ethnicity, never mention brands or logos, never transcribe on-screen text or dialogue. "
        "If unsure of a value, leave the field out.")


# ------------------------------------------------------------------ validation (redaction)
def _person_no(v) -> int | None:
    s = str(v if v is not None else "").strip().lower().removeprefix("person").strip()
    return int(s) if s.isdigit() and 1 <= int(s) <= MAX_PEOPLE else None


def clean_frames(raw, times: list[float]) -> tuple[list[dict], int]:
    """Keep only the schema: ([{t, shot.., people: [...]}] one per known frame, stripped count)."""
    stripped = 0
    if not isinstance(raw, dict):
        return [], 1
    stripped += len(set(raw) - {"frames"})
    out, seen = [], set()
    for f in (raw.get("frames") if isinstance(raw.get("frames"), list) else [])[: len(times) * 2]:
        if not isinstance(f, dict):
            stripped += 1
            continue
        stripped += len(set(f) - FRAME_KEYS)
        k = int(f["frame"]) if str(f.get("frame", "")).isdigit() else None
        if k is None or not 1 <= k <= len(times) or k in seen:
            stripped += 1
            continue
        seen.add(k)
        fr = {"t": round(times[k - 1], 2)}
        for key, allowed in SCENE_FIELDS:
            if key in f:
                v = str(f[key] or "").strip().lower()
                if v in allowed:
                    fr[key] = v
                else:
                    stripped += 1
        people = []
        for p in (f.get("people") if isinstance(f.get("people"), list) else [])[: MAX_PEOPLE * 2]:
            if not isinstance(p, dict):
                stripped += 1
                continue
            stripped += len(set(p) - PERSON_KEYS)
            n = _person_no(p.get("person"))
            if n is None or any(x["person"] == n for x in people):
                stripped += 1
                continue
            e = {"person": n}
            for key, allowed in PERSON_FIELDS:
                if key in p:
                    v = str(p[key] or "").strip().lower().replace(" ", "_" if key == "gesture" else " ")
                    if v in allowed:
                        e[key] = v
                    else:
                        stripped += 1
            if "facing" in p:
                v = str(p["facing"] or "").strip().lower()
                other = _person_no(v) if v.startswith("person") else None
                if v in FACING_FIXED:
                    e["facing"] = v
                elif other and other != n:
                    e["facing"] = f"person {other}"
                else:
                    stripped += 1
            if "talking" in p:
                if isinstance(p["talking"], bool):
                    e["talking"] = p["talking"]
                else:
                    stripped += 1
            people.append(e)
            if len(people) >= MAX_PEOPLE:
                break
        fr["people"] = sorted(people, key=lambda x: x["person"])
        out.append(fr)
    out.sort(key=lambda x: x["t"])
    return out, stripped


def renumber(prev_last: dict | None, batch: list[dict]) -> tuple[list[dict], dict[int, int]]:
    """Map a later batch's person numbers back to the previous batch's, using the overlap frame (same position and
    pose = same person); returns (the batch without its overlap frame, mapping used). Unmatched numbers keep theirs
    unless taken, then get the next free number."""
    if not prev_last or not batch:
        return batch, {}
    if abs(batch[0]["t"] - prev_last["t"]) > 0.01:
        # the model left out the repeated frame: keep every frame and the numbers as given (nothing to compare)
        return batch, {}
    over, rest = batch[0], batch[1:]
    key = lambda p: (p.get("position"), p.get("pose"))
    before = {}
    for p in prev_last.get("people", []):
        before.setdefault(key(p), []).append(p["person"])
    mapping = {}
    for p in over.get("people", []):
        cands = before.get(key(p), [])
        if len(cands) == 1 and cands[0] not in mapping.values():
            mapping[p["person"]] = cands[0]
    used = set(mapping.values()) | {p["person"] for p in prev_last.get("people", [])}
    for fr in rest:
        for p in fr.get("people", []):
            n = p["person"]
            if n not in mapping:
                if n in used:
                    free = next((m for m in range(1, MAX_PEOPLE + 1) if m not in used), n)
                    mapping[n] = free
                else:
                    mapping[n] = n
                used.add(mapping[n])
    for fr in rest:
        for p in fr.get("people", []):
            p["person"] = mapping.get(p["person"], p["person"])
            if str(p.get("facing", "")).startswith("person "):
                o = int(p["facing"].split()[1])
                p["facing"] = f"person {mapping.get(o, o)}"
        fr["people"] = sorted(fr.get("people", []), key=lambda x: x["person"])
    return rest, mapping


# ------------------------------------------------------------------ the v1 view (for everything downstream)
def to_ranges(frames: list[dict], length: float, step: float) -> tuple[list[dict], int]:
    """v1 ranges from the frames: each frame covers its slot; consecutive frames with the same staging are merged.
    The speaker is the one person talking (none when several or nobody talk); the others are reactors 1.. in person
    order. Run through video_notes.clean_notes, so only the v1 schema survives."""
    rows = []
    for fr in frames:
        people = fr.get("people", [])
        talking = [p for p in people if p.get("talking")]
        speaker = talking[0]["person"] if len(talking) == 1 else None
        label, n = {}, 0
        for p in people:
            if p["person"] == speaker:
                label[p["person"]] = "speaker"
            else:
                n += 1
                label[p["person"]] = f"reactor {n}"
        roles = []
        for p in people:
            r = {"role": label[p["person"]], "person": p["person"]}   # the anonymous number, for "who is who"
            for k in ("position", "pose", "emotion"):
                if p.get(k):
                    r[k] = p[k]
            f = p.get("facing")
            if f in FACING_FIXED:
                r["facing"] = f
            elif f and f.startswith("person ") and int(f.split()[1]) in label:
                r["facing"] = label[int(f.split()[1])]
            roles.append(r)
        stage = {k: fr[k] for k, _ in SCENE_FIELDS if fr.get(k)}
        s, e = max(0.0, fr["t"] - step / 2), min(length, fr["t"] + step / 2)
        if rows and rows[-1]["stage"] == stage and rows[-1]["roles"] == roles and abs(rows[-1]["end"] - s) < 1e-6 + step:
            rows[-1]["end"] = e
        else:
            rows.append({"start": s, "end": e, "stage": stage, "roles": roles})
    raw = {"ranges": [{"start": r["start"], "end": r["end"], **r["stage"], **({"roles": r["roles"]} if r["roles"] else {})}
                      for r in rows]}
    return VN.clean_notes(raw, length)


# ------------------------------------------------------------------ the quality readout
def quality(frames: list[dict], frames_sent: int, stripped: int, usages: list[dict], est_usd: float | None,
            mappings: list[dict]) -> dict:
    """How well the identity tracking worked: people found, how often each number appears, frames used, the actual
    cost, items stripped, and any renumbering done from the overlap frames."""
    counts: dict[str, int] = {}
    for fr in frames:
        for p in fr.get("people", []):
            counts[str(p["person"])] = counts.get(str(p["person"]), 0) + 1
    return {"version": VERSION, "people": len(counts), "appearances": dict(sorted(counts.items(), key=lambda kv: int(kv[0]))),
            "frames_sent": frames_sent, "frames_used": len(frames),
            "frames_with_people": sum(1 for fr in frames if fr.get("people")),
            "talking_frames": sum(1 for fr in frames if any(p.get("talking") for p in fr.get("people", []))),
            "calls": len(usages), "actual_usd": actual_usd(usages), "estimated_usd": est_usd, "stripped": stripped,
            "renumbered": [m for m in mappings if any(k != v for k, v in m.items())],
            "views": sorted({fr["view"] for fr in frames if fr.get("view")}),
            "neutral_share": neutral_share(frames), "hint": provider_hint(frames, usages)}


def neutral_share(frames: list[dict]) -> float | None:
    emo = [p.get("emotion") for fr in frames for p in fr.get("people", [])]
    return round(sum(1 for e in emo if e in (None, "neutral")) / len(emo), 2) if emo else None


def provider_hint(frames: list[dict], usages: list[dict]) -> str:
    share = neutral_share(frames)
    provider = (usages[0] if usages else {}).get("provider")
    if share is not None and share >= NEUTRAL_HINT and provider != "anthropic":
        return ("Emotions are nearly all neutral: try the Anthropic vision provider for richer emotions "
                "(Settings > Video and visual analysis).")
    return ""


def summarize_mapping(m: dict[int, int]) -> dict:
    return {str(k): v for k, v in m.items()}


def clamp_cap(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return DEFAULT_CAP_USD
    return DEFAULT_CAP_USD if not math.isfinite(x) or x <= 0 else min(x, 10.0)

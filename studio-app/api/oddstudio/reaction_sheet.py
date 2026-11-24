"""The reaction sheet and the shot list (2026-11-24): plain data, the same for every renderer.

Reaction beats live on the storyboard line, inside the reacting character's entry:
    line["reactions"] = [{"character": "ralph", "expression": "neutral",
                          "beats": [{"word": 3, "word_text": "Ralph", "t": 8.24, "expression": "neutral",
                                     "move": "lift", "strength": "medium", "reason": "...", "estimated": false}]}]
  word        index into the transcript line's words (the recording's word timings); t defaults to that word's start and
              can be set by hand (a delayed reaction, or a word the transcript timed badly: then "estimated": true)
  expression  one of the character's approved (usable) expressions
  move        a head movement from MOVES; strength from STRENGTHS

Shots live on the storyboard scene (storyboard_scenes.shots):
    [{"start": 6.22, "end": 7.94, "type": "ots", "camera": "behind Ralph's shoulder", "on_screen": ["uncle-mortimer"],
      "over_shoulder_of": "ralph"}]
  times are the recording's (audio episodes), inside the scene's span (from the previous scene's last line end to the
  next scene's first line start), in order and not overlapping.

Both are exported in the render spec unchanged (lines[].reactions[].beats, spec["shots"]); the renderers of today do
not act on them, so a render with or without them looks the same. The 3D camera reads them. Pure functions here (no
database), so the example data file is validated by the same rules as the routes.
"""
from __future__ import annotations

MOVES = ("none", "lift", "flinch", "dip", "tilt", "turn_to", "lean_in", "chin_up", "glance")
STRENGTHS = ("light", "medium", "strong")
SHOT_TYPES = ("wide", "medium", "mcu", "cu", "ots")
MAX_BEATS = 12
MAX_SHOTS = 40
REASON_MAX = 160
CAMERA_MAX = 120
SLACK = 0.5          # a beat may fall this long before the line starts (a reaction to the line coming)
AFTER = 4.0          # ... or this long after it ends (a delayed reaction; the next line's beats belong to that line)


class SheetError(ValueError):
    """A reaction beat or a shot that breaks a rule; the message names it for the owner."""


def _num(v, what: str) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SheetError(f"{what} must be a number of seconds")
    if x != x or x in (float("inf"), float("-inf")):
        raise SheetError(f"{what} must be a number of seconds")
    return round(x, 3)


def check_beats(beats, *, name: str, usable: set[str], words: list[dict], start: float, end: float) -> list[dict]:
    """The beats of one reacting character on one line, normalised and ordered by time, or SheetError.
    words: the transcript line's words ({start, end, word}); start/end: the line's window on the recording."""
    if not isinstance(beats, list):
        raise SheetError("beats must be a list")
    if len(beats) > MAX_BEATS:
        raise SheetError(f"at most {MAX_BEATS} beats per character and line")
    if beats and not words:
        raise SheetError("beats need the recording's word timings, and this line has none")
    out = []
    for i, b in enumerate(beats):
        n = f"{name}'s beat {i + 1}"
        if not isinstance(b, dict):
            raise SheetError(f"{n} must be an object")
        try:
            w = int(b.get("word"))
        except (TypeError, ValueError):
            raise SheetError(f"{n}: choose the word it reacts to")
        if not 0 <= w < len(words):
            raise SheetError(f"{n}: word {w + 1} is not in this line (it has {len(words)} words)")
        e = str(b.get("expression") or "neutral").strip().lower()
        if e not in usable:
            raise SheetError(f"{n}: {name} has no approved '{e}' pose: choose one of {', '.join(sorted(usable))}")
        mv = str(b.get("move") or "none").strip().lower()
        if mv not in MOVES:
            raise SheetError(f"{n}: the move must be one of {', '.join(MOVES)}")
        st = str(b.get("strength") or "medium").strip().lower()
        if st not in STRENGTHS:
            raise SheetError(f"{n}: the strength must be light, medium or strong")
        t = _num(b["t"], f"{n}: the time") if b.get("t") is not None else round(float(words[w]["start"]), 3)
        if not start - SLACK <= t <= end + AFTER:
            raise SheetError(f"{n}: {t:.2f} s is outside this line ({start:.2f}-{end:.2f} s)")
        reason = " ".join(str(b.get("reason") or "").split())[:REASON_MAX]
        out.append({"word": w, "word_text": str(words[w].get("word", "")).strip(), "t": t, "expression": e, "move": mv,
                    "strength": st, "reason": reason, **({"estimated": True} if b.get("estimated") else {})})
    out.sort(key=lambda x: x["t"])
    return out


def check_shots(shots, *, lo: float, hi: float, cast: set[str]) -> list[dict]:
    """A scene's shot list, normalised, or SheetError. lo/hi: the scene's span on the recording; cast: the episode's
    character keys."""
    if not isinstance(shots, list):
        raise SheetError("shots must be a list")
    if len(shots) > MAX_SHOTS:
        raise SheetError(f"at most {MAX_SHOTS} shots per scene")
    out = []
    for i, s in enumerate(shots):
        n = f"shot {i + 1}"
        if not isinstance(s, dict):
            raise SheetError(f"{n} must be an object")
        a, b = _num(s.get("start"), f"{n}: the start"), _num(s.get("end"), f"{n}: the end")
        if b <= a:
            raise SheetError(f"{n}: it must end after it starts")
        if a < lo - 1e-6 or b > hi + 1e-6:
            raise SheetError(f"{n}: {a:.2f}-{b:.2f} s is outside this scene ({lo:.2f}-{hi:.2f} s)")
        if out and a < out[-1]["end"] - 1e-6:
            raise SheetError(f"{n}: it starts at {a:.2f} s, before shot {i} ends ({out[-1]['end']:.2f} s): shots run in order "
                             "and do not overlap")
        ty = str(s.get("type") or "").strip().lower()
        if ty not in SHOT_TYPES:
            raise SheetError(f"{n}: the type must be one of {', '.join(SHOT_TYPES)}")
        on = [str(k) for k in (s.get("on_screen") or [])]
        if not on:
            raise SheetError(f"{n}: say who is on screen")
        bad = [k for k in on if k not in cast]
        if bad:
            raise SheetError(f"{n}: {', '.join(bad)} is not in this episode's cast")
        ots = s.get("over_shoulder_of") or None
        if ots is not None and str(ots) not in cast:
            raise SheetError(f"{n}: {ots} is not in this episode's cast")
        if ty == "ots" and ots is None:
            raise SheetError(f"{n}: an over-the-shoulder shot needs whose shoulder")
        out.append({"start": a, "end": b, "type": ty, "camera": " ".join(str(s.get("camera") or "").split())[:CAMERA_MAX],
                    "on_screen": list(dict.fromkeys(on)), **({"over_shoulder_of": str(ots)} if ots else {})})
    return out


def scene_span(scenes: list, index: int, duration: float | None = None) -> tuple[float, float]:
    """(lo, hi) of scene `index` among the episode's scenes in order: from the previous scene's last line end (0 for the
    first) to the next scene's first line start (the recording's duration, else its own last line end + AFTER, for the
    last). scenes: objects or dicts with a `lines` list of {start, end}."""
    def lines(s):
        return [x for x in (s.get("lines") if isinstance(s, dict) else s.lines) or [] if x.get("start") is not None]
    prev = [float(x["end"]) for s in scenes[:index] for x in lines(s)]
    nxt = [float(x["start"]) for s in scenes[index + 1:] for x in lines(s)]
    own = lines(scenes[index])
    lo = max(prev) if prev else 0.0
    if nxt:
        hi = min(nxt)
    elif duration:
        hi = float(duration)
    else:
        hi = max((float(x["end"]) for x in own), default=lo) + AFTER
    return round(lo, 3), round(hi, 3)


def sanitize_beats(beats) -> list[dict]:
    """Beats carried through a whole-scene edit (the script schema): known fields only, types kept; the full check
    (approved expressions, word timings) is the reactions route's."""
    out = []
    for b in (beats if isinstance(beats, list) else [])[:MAX_BEATS]:
        if not isinstance(b, dict):
            continue
        try:
            x = {"word": int(b["word"]), "t": round(float(b["t"]), 3)}
        except (KeyError, TypeError, ValueError):
            continue
        x["word_text"] = str(b.get("word_text") or "")[:40]
        x["expression"] = str(b.get("expression") or "neutral")[:40].lower()
        x["move"] = b.get("move") if b.get("move") in MOVES else "none"
        x["strength"] = b.get("strength") if b.get("strength") in STRENGTHS else "medium"
        x["reason"] = " ".join(str(b.get("reason") or "").split())[:REASON_MAX]
        if b.get("estimated"):
            x["estimated"] = True
        out.append(x)
    return out


def spec_shots(scenes: list) -> list[dict]:
    """Every scene's shots for the render spec, in time order, each with its scene's position; [] when none."""
    out = []
    for s in scenes:
        for sh in getattr(s, "shots", None) or []:
            out.append({"scene": s.position, **sh})
    return sorted(out, key=lambda x: x["start"])

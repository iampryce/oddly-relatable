"""Long-form episodes (owner decisions D-L1 to D-L5, 2026-11-16): outline rules, quality checks, segment planning,
segment fingerprints and the final join.

- Outline: exactly three acts. The 5–7 minute target guides the outline but is never a quota: a story estimated under
  five minutes is flagged for the owner (approve it as it is, or make it a Short), never padded. Over 7½ minutes is
  refused. Repeated jokes are flagged.
- Segments: at most SEGMENT_MAX seconds each (under the renderer's 60 s full-render limit). Boundaries fall on scene
  cuts; a scene longer than a segment is split between lines, never inside a line.
- Fingerprint: a segment's inputs (its engine story, voice clips, character registries and the engine code). An
  unchanged fingerprint means the earlier render is reused, so a revision re-renders only what changed.
- Join: video packets copied (every segment comes from the same renderer settings), audio concatenated from each
  segment's exact mixed WAV and encoded once (no gaps or clicks at joins), then checked.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from .config import REPO_ROOT, get_settings
from .script_schema import ScriptError, _str, KEY

TARGET_MIN, TARGET_MAX, HARD_CAP = 300, 420, 450          # 5–7 minutes, 7½-minute cap (D-L3)
SEGMENT_MAX = 58.0                                        # renderer renders up to 60 s in full; keep a margin
SCENES_MIN, SCENES_MAX = 15, 40


# ------------------------------------------------------------------ outline
def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def validate_outline(doc: dict, known_characters: set[str] | None = None) -> dict:
    """Normalised outline or OutlineError. Warnings (under target, repeated jokes) are returned, not raised."""
    if not isinstance(doc, dict):
        raise ScriptError("outline must be an object")
    out = {k: _str(doc, k, "outline", required=k in ("title", "logline"), max_len=600 if k != "title" else 100)
           for k in ("title", "logline", "premise", "twist", "ending")}
    out["quality_notes"] = _str(doc, "quality_notes", "outline", required=False, max_len=1500)
    new_chars = []
    for i, c in enumerate(doc.get("new_characters") or []):
        w = f"outline.new_characters[{i}]"
        key = _str(c, "key", w, max_len=40).lower()
        if not KEY.match(key):
            raise ScriptError(f"{w}.key must be lowercase letters, digits and dashes")
        if known_characters is not None and key in known_characters:
            continue
        style = (c.get("bubble_style") or "neutral").lower()
        new_chars.append({"key": key, "name": _str(c, "name", w, max_len=120), "description": _str(c, "description", w, required=False),
                          "visual_description": _str(c, "visual_description", w), "bubble_style": style if style in ("him", "her", "neutral") else "neutral",
                          "voice_style": _str(c, "voice_style", w, required=False, max_len=600)})
    out["new_characters"] = new_chars
    known = set(known_characters or set()) | {c["key"] for c in new_chars} if known_characters is not None else None
    chars = doc.get("characters") or []
    if not isinstance(chars, list) or not chars:
        raise ScriptError("outline.characters must list the cast")
    out["characters"] = []
    for i, c in enumerate(chars):
        key = _str(c, "key", f"outline.characters[{i}]", max_len=60)
        if known is not None and key not in known:
            raise ScriptError(f"outline.characters[{i}].key {key!r} is not a studio character (introduce it in new_characters)")
        out["characters"].append({"key": key, "role": _str(c, "role", f"outline.characters[{i}]", required=False, max_len=300)})
    cast = {c["key"] for c in out["characters"]}
    acts = doc.get("acts")
    if not isinstance(acts, list) or len(acts) != 3:
        raise ScriptError("outline.acts must contain exactly three acts")
    out["acts"], seen, total, n = [], set(), 0.0, 0
    for ai, a in enumerate(acts, 1):
        w = f"outline.acts[{ai - 1}]"
        act = {"act": ai, "title": _str(a, "title", w, max_len=120), "purpose": _str(a, "purpose", w, max_len=600), "scenes": []}
        scenes = a.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ScriptError(f"{w}.scenes must not be empty")
        for si, s in enumerate(scenes):
            sw = f"{w}.scenes[{si}]"
            sid = (_str(s, "id", sw, required=False, max_len=40) or f"a{ai}s{si + 1}").lower()
            if not re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", sid) or sid in seen:
                raise ScriptError(f"{sw}.id must be unique (lowercase letters, digits, dashes)")
            seen.add(sid)
            beats = [b.strip() for b in (s.get("beats") or []) if isinstance(b, str) and b.strip()]
            if not beats:
                raise ScriptError(f"{sw}: every scene needs at least one story beat (a development, not filler)")
            est = s.get("est_seconds")
            if not isinstance(est, (int, float)) or not 4 <= est <= 90:
                raise ScriptError(f"{sw}.est_seconds must be between 4 and 90")
            who = [k for k in (s.get("characters") or []) if isinstance(k, str)]
            for k in who:
                if k not in cast:
                    raise ScriptError(f"{sw}: character {k!r} is not in outline.characters")
            if len(who) > 4:
                raise ScriptError(f"{sw}: at most 4 characters on screen in a scene (D-L3)")
            act["scenes"].append({"id": sid, "heading": _str(s, "heading", sw, max_len=200), "summary": _str(s, "summary", sw, max_len=1200),
                                  "beats": beats[:10], "jokes": [j.strip() for j in (s.get("jokes") or []) if isinstance(j, str) and j.strip()][:8],
                                  "characters": who, "location": _str(s, "location", sw, required=False, max_len=80), "est_seconds": round(float(est), 1)})
            total += float(est)
            n += 1
        out["acts"].append(act)
    if not SCENES_MIN <= n <= SCENES_MAX:
        raise ScriptError(f"the outline has {n} scenes; a long episode has {SCENES_MIN} to {SCENES_MAX}")
    if total > HARD_CAP:
        raise ScriptError(f"the outline runs about {total:.0f} s, over the 7½-minute cap ({HARD_CAP} s). Tighten it")
    out["runtime_estimate_seconds"] = round(total, 1)
    return out


def outline_warnings(outline: dict) -> list[str]:
    """Owner-facing quality flags. These never change the outline: the owner decides."""
    warns = []
    total = outline["runtime_estimate_seconds"]
    if total < TARGET_MIN:
        warns.append(f"Runs about {total:.0f} s, under the 5-minute target. Do not pad it: approve it as it is, or make the idea a Short.")
    elif total > TARGET_MAX:
        warns.append(f"Runs about {total:.0f} s, over the 7-minute target (cap 7½ minutes).")
    jokes: dict[str, list[str]] = {}
    for a in outline["acts"]:
        for s in a["scenes"]:
            for j in s["jokes"]:
                jokes.setdefault(_norm(j), []).append(s["id"])
    for j, where in jokes.items():
        if j and len(where) > 1:
            warns.append(f"Joke repeated in scenes {', '.join(where)}: \"{j[:80]}\"")
    thin = [s["id"] for a in outline["acts"] for s in a["scenes"] if len(s["beats"]) == 1 and not s["jokes"]]
    if len(thin) > 3:
        warns.append(f"{len(thin)} scenes have a single beat and no joke ({', '.join(thin[:6])}...): check they earn their time.")
    return warns


def repeated_lines(script: dict) -> list[str]:
    """Lines repeated verbatim across the script (beyond short reactions): a padding signal for the owner."""
    seen: dict[str, list[str]] = {}
    for s in script["scenes"]:
        for ln in s["lines"]:
            t = _norm(ln["text"])
            if len(t) >= 18:
                seen.setdefault(t, []).append(s["id"])
    return [f"Line repeated in scenes {', '.join(w)}: \"{t[:70]}\"" for t, w in seen.items() if len(w) > 1]


# ------------------------------------------------------------------ segments
def plan_segments(scene_timings: list[dict], max_seconds: float = SEGMENT_MAX) -> list[list[dict]]:
    """Pack scenes into segments of at most max_seconds, cutting only at scene boundaries; a scene longer than a segment
    is split between lines. scene_timings: [{"scene": id, "duration": s, "lines": [{"start": s (scene-relative), "duration": s}]}].
    Returns segments as lists of parts {"scene": id, "lines": [first, last_exclusive], "duration": s}."""
    segments, cur, cur_len = [], [], 0.0
    for sc in scene_timings:
        parts = []
        if sc["duration"] <= max_seconds:
            parts.append({"scene": sc["scene"], "lines": [0, len(sc["lines"])], "duration": sc["duration"]})
        else:
            first, start = 0, 0.0
            starts = [ln["start"] for ln in sc["lines"]] + [sc["duration"]]
            for i in range(1, len(starts)):
                if starts[i] - start > max_seconds:
                    if i - 1 == first:
                        raise ValueError(f"scene {sc['scene']}: a single line lasts over {max_seconds} s")
                    parts.append({"scene": sc["scene"], "lines": [first, i - 1], "duration": starts[i - 1] - start})
                    first, start = i - 1, starts[i - 1]
            parts.append({"scene": sc["scene"], "lines": [first, len(sc["lines"])], "duration": sc["duration"] - start})
        for p in parts:
            if cur and cur_len + p["duration"] > max_seconds:
                segments.append(cur)
                cur, cur_len = [], 0.0
            cur.append(p)
            cur_len += p["duration"]
    if cur:
        segments.append(cur)
    return segments


_engine_hash: str | None = None


def engine_fingerprint() -> str:
    """Hash of the engine and renderer code: a change to either invalidates every reused segment."""
    global _engine_hash
    if _engine_hash is None:
        h = hashlib.sha256()
        roots = [REPO_ROOT / "production" / "lib", REPO_ROOT / "skills" / "directing-stickman-videos" / "scripts"]
        for root in roots:
            for f in sorted(root.rglob("*.mjs")):
                h.update(str(f.relative_to(REPO_ROOT)).encode())
                h.update(f.read_bytes())
        _engine_hash = h.hexdigest()
    return _engine_hash


def segment_fingerprint(story: dict, clip_hashes: list[str], registry_files: list[Path]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps(story, sort_keys=True).encode())
    for c in clip_hashes:
        h.update(c.encode())
    for f in sorted(set(registry_files)):
        h.update(Path(f).read_bytes())
    h.update(engine_fingerprint().encode())
    return h.hexdigest()


# ------------------------------------------------------------------ join
def _run(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(args[0]).name} failed: {(r.stderr or r.stdout)[-600:]}")
    return r


def probe(path: Path) -> dict:
    s = get_settings()
    r = _run([s.ffprobe, "-v", "error", "-count_packets", "-show_entries",
              "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_packets,duration,sample_rate:format=duration",
              "-of", "json", str(path)])
    d = json.loads(r.stdout)
    v = next(x for x in d["streams"] if x["codec_type"] == "video")
    a = next((x for x in d["streams"] if x["codec_type"] == "audio"), None)
    return {"width": v["width"], "height": v["height"], "fps": v["r_frame_rate"], "codec": v["codec_name"],
            "frames": int(v["nb_read_packets"]), "duration": float(d["format"]["duration"]),
            "audio": {"codec": a["codec_name"], "duration": float(a.get("duration") or 0), "rate": a.get("sample_rate")} if a else None}


def mean_volume(path: Path, start: float, seconds: float) -> float | None:
    s = get_settings()
    r = subprocess.run([s.ffmpeg, "-v", "info", "-ss", f"{max(0, start):.3f}", "-t", f"{seconds:.3f}", "-i", str(path), "-map", "0:a:0",
                        "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True, timeout=300,
                       stdin=subprocess.DEVNULL)
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", r.stderr)
    if not m or m.group(1) == "-inf":
        return None
    return float(m.group(1))


def join_segments(videos: list[Path], wavs: list[Path], out: Path, work: Path) -> dict:
    """Join rendered segments: video copied, audio concatenated sample-exactly and encoded once. Returns checks."""
    s = get_settings()
    if not videos or len(videos) != len(wavs):
        raise ValueError("every segment needs its video and its mixed audio")
    infos = [probe(v) for v in videos]
    first = infos[0]
    for i, inf in enumerate(infos):
        for k in ("width", "height", "fps", "codec"):
            if inf[k] != first[k]:
                raise ValueError(f"segment {i + 1} has {k} {inf[k]}, segment 1 has {first[k]}: segments must share the renderer settings")
    work.mkdir(parents=True, exist_ok=True)
    esc = lambda p: str(Path(p).resolve()).replace("\\", "/").replace("'", "'\\''")  # noqa: E731
    vlist, alist = work / "video.txt", work / "audio.txt"
    vlist.write_text("".join(f"file '{esc(v)}'\n" for v in videos), encoding="utf-8")
    alist.write_text("".join(f"file '{esc(a)}'\n" for a in wavs), encoding="utf-8")
    _run([s.ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(vlist), "-f", "concat", "-safe", "0", "-i", str(alist),
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    joined = probe(out)
    frames = sum(i["frames"] for i in infos)
    durations = [i["duration"] for i in infos]
    checks = {"segments": len(videos), "frames": joined["frames"], "expected_frames": frames,
              "duration": round(joined["duration"], 3), "expected_duration": round(sum(durations), 3),
              "audio_duration": round(joined["audio"]["duration"], 3) if joined["audio"] else None, "joins": []}
    problems = []
    if joined["frames"] != frames:
        problems.append(f"joined video has {joined['frames']} frames, the segments have {frames}")
    if joined["audio"] is None or abs(joined["audio"]["duration"] - joined["duration"]) > 0.1:
        problems.append("joined audio does not cover the whole video")
    # Audio continuity at each join: the level just before and after the join in the joined file matches the level of
    # the same moments in the source segments (the join adds no gap, click or level jump).
    t = 0.0
    for i in range(len(videos) - 1):
        t += durations[i]
        joined_before, joined_after = mean_volume(out, t - 0.4, 0.4), mean_volume(out, t, 0.4)
        # Compared with the WAVs that were joined (the joined audio is built from them, not from the MP4s' AAC).
        src_before, src_after = mean_volume(wavs[i], durations[i] - 0.4, 0.4), mean_volume(wavs[i + 1], 0, 0.4)
        j = {"at": round(t, 3), "before": joined_before, "after": joined_after, "source_before": src_before, "source_after": src_after}
        for a, b, side in ((joined_before, src_before, "before"), (joined_after, src_after, "after")):
            if (a is None) != (b is None) or (a is not None and abs(a - b) > 1.5):
                problems.append(f"audio level changes at join {i + 1} ({side} {t:.2f} s): {a} dB joined vs {b} dB in the segment")
        checks["joins"].append(j)
    checks["problems"] = problems
    checks["ok"] = not problems
    return checks

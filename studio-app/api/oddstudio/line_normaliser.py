"""Audio-first Stage 1c: re-split transcribed lines at natural beats (owner request 2026-11-20).

Transcription providers give word timings WITHOUT punctuation (OpenAI) and, separately, a punctuated text. The first
split (audio_first.split_lines) only sees the words, so a line can hold the end of one thought and the start of the
next ("…to know I leave", "I leave nothing To my niece Winifred"). This module:

  1. punctuate()      aligns the words with the punctuated text, so each word knows its trailing punctuation (and
                      hyphenated words such as "bone-idle" or "K-Tel" are rejoined);
  2. propose_lines()  re-splits each speaker's words at beats: a sentence end, a cue phrase (editable per episode,
                      e.g. "To my", "I leave"), a pause of PAUSE seconds or more; then tidies: a line never ends on a
                      dangling word ("and", "the", "my" …), a short fragment joins its neighbour, an over-long line is
                      split at its best comma or pause. Speakers are kept; two speakers are never merged.
  3. trailing_fragment() flags a last line that looks cut off (ends on a connecting word, no final full stop in the
                      transcript, or audio continuing after the last word).

Pure functions on plain dicts: the API layer (audio_first.py) stores proposals only when the owner applies them.
"""
from __future__ import annotations

import difflib
import re

PAUSE = 0.4                 # a pause this long is a beat at punctuation (after "Ralph,") or before a cue phrase
LONG_PAUSE = 1.0            # a pause this long is a beat anywhere (mid-phrase pauses shorter than this stay inside
                            # the line, so "he managed to | scrounge" is not split)
MAX_SECONDS = 10.0          # a longer line is split at its best comma or pause
MIN_SECONDS, MIN_WORDS = 0.8, 2   # a shorter line joins its neighbour (same speaker)
TAIL_SECONDS = 1.5          # audio continuing this long after the last word flags the last line
DEFAULT_CUES = ["To my", "I leave", "And finally", "Failing", "Thank you"]
DANGLING = {"and", "or", "but", "the", "a", "an", "to", "of", "my", "your", "his", "her", "their", "our", "in", "on",
            "at", "for", "with", "from", "by", "that", "who", "which", "i", "so", "as", "if", "because", "than"}
HARD_STOP = ".!?…"
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "mt", "jr", "sr", "prof", "vs", "etc", "no"}   # "Mr." is not a sentence end


def _key(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", token.lower().replace("’", "'"))


def _text_tokens(text: str) -> list[dict]:
    """Punctuated text -> sub-tokens (hyphenated words split like the provider's words), each with the punctuation
    that follows it and whether a hyphen joins it to the next sub-token."""
    out = []
    for tok in re.findall(r"\S+", text or ""):
        trail = re.search(r"[.,!?;:…\"')\]]*$", tok).group(0)
        core = tok[: len(tok) - len(trail)] if trail else tok
        parts = [p for p in re.split(r"-", core) if p] or [core]
        for i, p in enumerate(parts):
            last = i == len(parts) - 1
            punct = "".join(c for c in trail if c in ".,!?;:…") if last else ""
            out.append({"key": _key(p), "punct": punct, "hyphen": not last})
    return [t for t in out if t["key"]]


def punctuate(words: list[dict], text: str) -> list[dict]:
    """Words with their trailing punctuation ("punct") and a hyphen flag ("hyphen": joined to the next word), aligned
    with the punctuated transcript text. Words that cannot be aligned keep no punctuation."""
    toks = _text_tokens(text)
    wkeys = [_key(w["word"]) for w in words]
    out = [{**w, "word": w["word"].strip(), "punct": "", "hyphen": False} for w in words]
    sm = difflib.SequenceMatcher(a=wkeys, b=[t["key"] for t in toks], autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            out[a + k]["punct"] = toks[b + k]["punct"]
            out[a + k]["hyphen"] = toks[b + k]["hyphen"]
    return out


def _cue_keys(cues: list[str]) -> list[list[str]]:
    return [k for k in ([_key(t) for t in c.split()] for c in cues or []) if k and all(k)]


def _cue_at(words: list[dict], i: int, cues: list[list[str]]) -> bool:
    for cue in cues:
        if [_key(w["word"]) for w in words[i:i + len(cue)]] == cue:
            return True
    return False


def line_text(ws: list[dict]) -> str:
    out = ""
    for k, w in enumerate(ws):
        out += w["word"] + w.get("punct", "")
        if k < len(ws) - 1:
            out += "-" if w.get("hyphen") and not w.get("punct") else " "
    return out.strip()


def _ends_sentence(w: dict) -> bool:
    return bool(w.get("punct")) and w["punct"][-1] in HARD_STOP and _key(w["word"]) not in ABBREVIATIONS


def _dangling(ws: list[dict]) -> bool:
    last = ws[-1]
    return not last.get("punct") and _key(last["word"]) in DANGLING


def _split_long(ws: list[dict], max_seconds: float) -> list[list[dict]]:
    """Split a too-long run at its best break: a comma (or pause) nearest the middle; recursively."""
    if len(ws) < 2 * MIN_WORDS or ws[-1]["end"] - ws[0]["start"] <= max_seconds:
        return [ws]
    mid = (ws[0]["start"] + ws[-1]["end"]) / 2
    best, score = None, None
    for i in range(MIN_WORDS - 1, len(ws) - MIN_WORDS):
        gap = ws[i + 1]["start"] - ws[i]["end"]
        quality = 2 if ws[i].get("punct") in (",", ";", ":") else (1 if gap >= 0.2 else 0)
        if quality == 0 or _dangling(ws[: i + 1]):
            continue
        s = (quality, -abs(ws[i]["end"] - mid))
        if score is None or s > score:
            best, score = i, s
    if best is None:
        return [ws]
    return _split_long(ws[: best + 1], max_seconds) + _split_long(ws[best + 1:], max_seconds)


def propose_lines(lines: list[dict], text: str, cues: list[str] | None = None, pause: float = PAUSE,
                  long_pause: float = LONG_PAUSE, max_seconds: float = MAX_SECONDS) -> list[dict]:
    """New lines from the current ones (their words, speakers and the punctuated transcript). Each proposed line:
    {id, start, end, text, speaker, words, from: [ids of the current lines it came from]}."""
    flat = []
    for ln in lines:
        for w in ln.get("words") or []:
            flat.append({**w, "speaker": ln.get("speaker", ""), "src": ln["id"]})
    if not flat:
        return [dict(ln, **{"from": [ln["id"]]}) for ln in lines]   # no word timings: nothing to re-split
    words = punctuate(flat, text)
    for w, f in zip(words, flat):
        w["speaker"], w["src"] = f["speaker"], f["src"]
    ck = _cue_keys(cues if cues is not None else DEFAULT_CUES)
    # 1. beats
    groups, cur = [], []
    for i, w in enumerate(words):
        if cur:
            prev = cur[-1]
            gap = w["start"] - prev["end"]
            cue = _cue_at(words, i, ck)
            if (w["speaker"] != prev["speaker"] or _ends_sentence(prev) or cue or gap >= long_pause
                    or (gap >= pause and (prev.get("punct") or cue))):
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    # 2. no line ends on a dangling word: move it (and any dangling words before it) to the next line, same speaker
    for g in range(len(groups) - 1):
        while (len(groups[g]) > 1 and _dangling(groups[g]) and groups[g + 1]
               and groups[g + 1][0]["speaker"] == groups[g][-1]["speaker"]):
            groups[g + 1].insert(0, groups[g].pop())
    # 3. short fragments join a neighbour of the same speaker (the previous one unless it ends a sentence)
    def short(gr):
        return len(gr) < MIN_WORDS or gr[-1]["end"] - gr[0]["start"] < MIN_SECONDS
    changed = True
    while changed:
        changed = False
        for g, gr in enumerate(groups):
            if not gr or not short(gr):
                continue
            prev = groups[g - 1] if g > 0 else None
            nxt = groups[g + 1] if g + 1 < len(groups) else None
            prev_ok = prev and prev[-1]["speaker"] == gr[0]["speaker"] and not _ends_sentence(prev[-1])
            nxt_ok = nxt and nxt[0]["speaker"] == gr[-1]["speaker"] and not _ends_sentence(gr[-1])
            if prev_ok:
                prev.extend(gr)
            elif nxt_ok:
                nxt[:0] = gr
            else:
                continue
            groups[g] = []
            changed = True
        groups = [gr for gr in groups if gr]
    # 4. over-long lines split at their best comma or pause
    final = []
    for gr in groups:
        final.extend(_split_long(gr, max_seconds))
    out = []
    for i, gr in enumerate(final):
        out.append({"id": f"l{i + 1}", "start": round(gr[0]["start"], 3), "end": round(gr[-1]["end"], 3),
                    "text": line_text(gr), "speaker": gr[0]["speaker"],
                    "words": [{"start": round(w["start"], 3), "end": round(w["end"], 3), "word": w["word"]} for w in gr],
                    "from": list(dict.fromkeys(w["src"] for w in gr))})
    return out


def trailing_fragment(lines: list[dict], text: str, duration: float | None) -> dict | None:
    """The last line, if it looks cut off: it ends on a connecting word, the transcript has no final full stop, or the
    audio continues well after the last word. None when it looks complete."""
    if not lines:
        return None
    last = lines[-1]
    words = last.get("words") or []
    last_word = _key(words[-1]["word"]) if words else _key((last.get("text") or "").split()[-1] if last.get("text") else "")
    reasons = []
    if last_word in DANGLING:
        reasons.append(f'ends on "{last_word}"')
    if (text or "").strip() and (text or "").strip()[-1] not in HARD_STOP + "\"')":
        reasons.append("the transcript has no final full stop")
    after = round(float(duration) - float(last["end"]), 2) if duration else 0.0
    if after >= TAIL_SECONDS:
        reasons.append(f"{after:.1f} s of audio after the last word")
    if not reasons or (len(reasons) == 1 and reasons[0].startswith(tuple("0123456789"))):
        return None   # trailing silence alone (applause, a pause) is not a cut-off line
    return {"line_id": last["id"], "text": last.get("text", ""), "start": last["start"], "end": last["end"],
            "reasons": reasons, "audio_after": after}

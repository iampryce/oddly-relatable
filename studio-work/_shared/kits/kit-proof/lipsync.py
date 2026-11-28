"""Mouth track from Whisper word times + loudness (no AI). Writes web/lipsync.js.
Words are trimmed to their natural length (0.07 s/char + 0.10 s, anchored at the word end, as in
stick-cast/acting-test/mouth_from_audio.py) so laughs stretched into a word keep the mouth shut.
Each trimmed word is split into letter groups -> visemes: vowels open (a=wide, e/i=mid, o/u/w=round),
m/b/p closed, other consonants small. Frames where the audio is silent are forced shut."""
import json, wave, re
import numpy as np
FPS = 25
SHOTS = {"s19": (51.8, 14.0, "audio/s19.wav"), "s13": (33.9, 2.0, "audio/s13.wav")}
words = json.load(open("audio/ep15-words.json"))
def rms_track(path, n):
    w = wave.open(path); sr = w.getframerate(); a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
    hop = sr // FPS; r = np.array([np.sqrt(np.mean(a[i*hop:(i+1)*hop]**2)) if i*hop < len(a) else 0 for i in range(n)])
    return r / (r.max() or 1)
def visemes(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if len(w) > 2 and w.endswith("e") and w[-2] not in "aeiou": w = w[:-1]   # silent e
    segs = []
    for m in re.finditer(r"[aeiouy]+|[^aeiouy]+", w):
        g = m.group()
        if g[0] in "aeiouy":
            v = "round" if any(c in g for c in "ou") else "wide" if "a" in g else "mid"
            segs.append((v, 2.0))
        else:
            for c in g:
                segs.append(("closed" if c in "mbp" else "round" if c == "w" else "small", 0.8))
    return segs or [("small", 1)]
out = {}
for key, (t0, dur, path) in SHOTS.items():
    n = int(round(dur * FPS)); lv = rms_track(path, n)
    ws = [dict(w) for w in words if w["end"] > t0 - 1 and w["start"] < t0 + dur + 1]
    merged = []; i = 0
    while i < len(ws):                       # zero-length Whisper words: merge with the next word
        w = ws[i]
        if w["end"] - w["start"] < 0.1 and i + 1 < len(ws):
            nx = ws[i + 1]; w = {"start": w["start"], "end": nx["end"], "word": w["word"] + " " + nx["word"]}; i += 1
        merged.append(w); i += 1
    shape = ["closed"] * n; amp = [0.0] * n; spans = []
    for w in merged:
        nat = 0.07 * len(w["word"].replace(" ", "")) + 0.10
        st, en = max(w["start"], w["end"] - nat) - t0, w["end"] - t0
        if en <= 0 or st >= dur: continue
        spans.append([round(st, 3), round(en, 3), w["word"]])
        segs = [s for part in w["word"].split() for s in visemes(part)]
        tot = sum(d for _, d in segs)
        for f in range(max(0, int(st * FPS)), min(n, int(np.ceil(en * FPS)))):
            t = (f + 0.5) / FPS; u = (t - st) / (en - st) * tot; acc = 0; v = segs[-1][0]
            for s, d in segs:
                if u < acc + d: v = s; break
                acc += d
            if lv[f] < 0.07: v = "closed"      # silence inside the word span
            shape[f] = v; amp[f] = round(float(min(1.15, 0.55 + lv[f] * 1.1)), 2)
    for f in range(1, n - 1):                 # no one-frame flickers
        if shape[f] != shape[f-1] and shape[f] != shape[f+1] and shape[f-1] == shape[f+1]: shape[f] = shape[f-1]
    out[key] = {"mouth": shape, "amp": amp, "words": spans}
    from collections import Counter; print(key, n, dict(Counter(shape))); print(spans)
open("web/lipsync.js", "w").write("export const LIPSYNC = " + json.dumps(out) + ";\n")

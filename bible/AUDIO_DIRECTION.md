# Audio Direction

> ⚠️ **PARTLY SUPERSEDED (owner direction, 2026-11-11):** the channel is for the **world at large**: **no Nigerian/African-specific stories, settings, names or language, and Femi is retired.** The cast, names, locations, language notes and jokes in this document were drafted for a West African setting and are **paused pending a rewrite**. Treat them as archive and templates (roles, structure and technique may carry over), **not as approved content**. See `DECISIONS.md` (AP-16 to AP-18).

**Status:** all **[PROPOSED]**. Voice, narrator and music choices are decisions **D8, D9, D16**.
**Approved constraints for this phase:** consider separate character voice tracks so conversations can be edited independently; do not select paid voice subscriptions; do not generate audio. [APPROVED]

No audio has been generated, no voice service has been chosen and no music has been sourced.

---

## 1. Audio principles

1. **Voice first.** Dialogue is always intelligible; music and effects sit underneath it.
2. **Every character sounds different** in pitch, pace and rhythm, so the audience can tell who is speaking with the picture off.
3. **Comedy lives in timing.** Gaps between lines are written and edited, not left to chance.
4. **Separate stems** for every character, SFX, music and ambience, so any line can be re-timed without re-recording everything.
5. **Original or properly licensed only**, recorded in a rights ledger (§9).

## 2. Voice personalities [PROPOSED, D8]

Direction notes for casting or voice selection. They describe delivery, not specific voices or services.

| Character | Voice | Pace | Delivery notes |
|---|---|---|---|
| **Femi** | Warm baritone, slightly nasal when nervous | Medium, speeds up to a gabble under stress | Soft voice cracking on "it's fine". Self-correcting ("I mean, no, yes, I mean"). Honest, never smug. |
| **Amara** | Clear mid-range alto, crisp consonants | Measured, deliberate | Dry and precise; deadpan one-liners; a warm drop in pitch when she is being sincere |
| **Tunde** | Big, bright, gravelly bass-baritone | Fast and loud, laughing mid-sentence | Public-speaker confidence; Pidgin flavour; wheeze laugh |
| **Dez** | Upbeat tenor | Quick, rising intonation | Podcast-host cadence; every sentence sounds like a question |
| **Madam F** | Low, smooth alto | Slow, even | Never raises her voice; the stillness is the threat; long pauses |
| **Zee** | Bright mezzo, fast, expressive | Very fast, big dynamic range | Gasps, drawn-out "BABE"; voice-note rambling |
| **Mummy Eze** | Rich, commanding contralto | Deliberate, projecting | Principal-to-assembly voice; sing-song proverbs; "Hmmm" |
| **Pepper** | None | N/A | Cat sounds only (a brief "mrrp", a hiss), used sparingly |

### Male and female dialogue characteristics
- Distinct **pitch bands** keep a two-person conversation clear: Femi (lower-mid) vs Amara (mid) vs Tunde (low and loud) vs Zee (higher).
- Different **rhythm signatures**: Femi trails off and restarts, Amara ends sentences cleanly, Tunde talks over, Zee runs sentences together.
- **No stereotyping:** the woman is not the nag and the man is not the fool by default (balance rules, `CHARACTER_BIBLE.md` §11).

### Accent and language [PROPOSED, D7]
- Clear international English as the base, with Nigerian English rhythm for the Nigerian characters, a light Ghanaian flavour for Dez.
- Pidgin and Igbo phrases only as short, context-clear exclamations.
- Voices must be **intelligible to non-Nigerian listeners** without slowing the comedy. Captions always on.

### Voice sourcing options (decision, not chosen) [D8]

| Option | Pros | Cons / cautions |
|---|---|---|
| **Human voice actors** (freelance) | Best comedic timing; authentic accents; a human performance can be directed | Cost per episode; scheduling; contract and usage rights must cover commercial YouTube use |
| **AI text-to-speech** | Fast, cheap, always available, easy to re-record | Comedy timing is hard; accent authenticity varies; **check the service's commercial-use terms and avoid cloning real people**; the Phase 0 tools tested only a Gemini speech adapter, not chosen |
| **Hybrid** | Humans for the two leads, TTS for minor roles | Mixed quality; careful matching needed |

**Recommendation:** audition at least two AI options and one human actor for Femi and Amara *before* the pilot. Decide with a short blind test. Do not subscribe to anything until you approve the choice and cost.

## 3. Narrator [PROPOSED, D9]

- **Comedy episodes (marriage, workplace, friendship):** *no narrator.* Characters carry the story; captions and visuals supply context. A narrator would explain jokes.
- **Interesting-facts and psychology videos:** an optional **dry, friendly narrator** who may be a recurring character (Zee in "listicle mode" or a neutral voice). Narration states facts only.
- **Hypothetical stories ("What if…"):** short narration allowed for setup, with characters taking over for scenes.
- Narrator rules: never explains a joke, never narrates what the picture already shows, never speaks over a punchline.

## 4. Music direction [PROPOSED, D16]

- **Overall feel:** light, rhythmic, contemporary; upbeat and warm with a hint of Afrobeats-inspired rhythm, using original or licensed tracks, not recognisable existing songs.
- **Instrumentation:** plucked bass, soft percussion, mallets, light guitar, finger snaps and claps, with occasional brass stabs for punchlines.
- **Levels:** music sits 12–18 dB under dialogue and ducks further during lines.
- **Cue types:**

| Cue | Purpose | Length |
|---|---|---|
| **Sonic logo** | Channel identity, 2–3 seconds; the opening or the end card | 2–3 s |
| **Main bed** | Light loop under normal scenes | Looped |
| **Tension bed** | Low pulse during Doom Tint scenes | Looped |
| **Reveal sting** | The moment of the twist | 1–2 s |
| **Silence** | Deliberate; the awkward pause with no music | Whole beats |
| **Warm ending** | A short resolved phrase for the closing beat | 5–8 s |

- **Sourcing:** decision at pilot planning. Options include composing original music, buying a licence for a library, or using free-licence tracks with attributions. Each track needs a recorded licence and proof (see §9). **Do not use "royalty-free" as a synonym for "no licence"**: check each asset's actual terms, including monetisation and Content ID.

## 5. Comedic sound effects [PROPOSED]

A small library, built or licensed once and reused:

| Category | Examples |
|---|---|
| **Reactions** | Record-scratch, gasp, "dun-dun-DUN" sting, sad trombone (use rarely), tiny bell "ding" for realisation |
| **Impact** | Pose-snap "pop", door slam, thud, boing, clunk |
| **Movement** | Whoosh (slide-ins), quick footsteps, tiptoe plinks, chair roll |
| **UI and phone** | Message ping, typing blip, voice-note start, call ring, low-battery chime (our own invented tones, not a real app's) |
| **Environment** | Generator hum, fan, traffic, office murmur, printer jam, cooler lid |
| **Gags** | Brow lift-off "pwing", sweat-drop "plip", Doom Tint drop (a low drone sweep), heart pop |
| **Ambience beds** | Home night, office day, street, restaurant, bus |

Rules: one effect per action; **sync to the exact frame of the pose snap**; do not stack more than three sounds at once; never cover a punchline line; use silence as an effect.

The renderer has five synthesised accents (`tap`, `paper`, `pop`, `chime`, `jingle`, verified) but no file-based SFX outside style B4. Our SFX therefore live in the **external mix** (see §7).

## 6. Audio transitions [PROPOSED]

- **Scene changes:** a 0.2–0.4 s whoosh or a quick music swell; ambience crossfades over 0.3 s.
- **Doom Tint drop:** a low "thum" plus music duck; recover over about 1 s.
- **Smash cut:** abrupt silence for 0.3 s, then the new scene's ambience.
- **Flashback and daydream:** reverb-washed entry and exit sweeps.
- **Cold open to title:** a short sting leads into the sonic logo.

## 7. Dialogue stems and mixing [PROPOSED]

### Stem structure per episode

```
stems/
  femi.wav   amara.wav   tunde.wav   ...   (one file per speaking character, full length, silent between lines)
  narrator.wav (if used)
  sfx.wav
  ambience.wav
  music.wav
mix/
  master.wav   → passed to the renderer as the single audio file, marked contains_sfx
```

- **All stems share the same start time, length and sample rate** (48 kHz, 24-bit working files).
- **Separate character tracks** let us re-time one line, replace one performance, or move a laugh, without touching the others. (Approved goal.)
- **Line-level files** (one per line, named `E01_S03_L07_femi.wav`) are kept alongside the full-length stems for quick edits.

### Why a separate mix step (verified renderer limit)
The renderer takes **one** audio file and applies no mixing of per-character tracks (verified). Our mixer therefore creates `master.wav`; the renderer is told it already contains effects and music. A small FFmpeg-based script will do this in a later phase; **nothing is built now**.

### Mixing targets

| Item | Target |
|---|---|
| Integrated loudness of the final mix | About −14 LUFS (the repo's own accepted reference sample measured about −15 LUFS, documented in its notes) |
| True peak | ≤ −1 dBTP |
| Dialogue relative to music | Music 12–18 dB below dialogue |
| Dialogue relative to SFX | Effects sit 3–8 dB below dialogue, except punch hits (up to −3 dB) |
| Ducking | Music drops 6–10 dB under speech, 120 ms attack, 400 ms release |
| EQ | Gentle low-cut at 80 Hz on voices; keep Tunde's lows from masking Femi |
| Stereo | Dialogue centred; character position pans of ±10–20% allowed for two-shots; ambience wide |
| Pitch/speed | **Never time-stretch dialogue to fit visuals** (the renderer also forbids changing voice speed, verified) |

### Dialogue editing rules
- Trim silence at line starts to 0.05–0.1 s; keep natural breaths.
- Remove clicks; no heavy processing that makes voices sound alike.
- Add **room tone** between lines so silences do not sound digitally dead.
- Laughs and gasps are recorded or sourced as their own cues, not extracted from lines.

### Voice-note and phone effects
- Phone audio (e.g. Zee's voice notes) uses a band-limited filter (300 Hz–3.4 kHz) plus slight compression.

## 8. Audio QA checklist [PROPOSED]

- [ ] Every line is intelligible at low volume on laptop speakers.
- [ ] No clipping; true peak within target.
- [ ] Characters are distinguishable by voice alone.
- [ ] No effect covers a punchline.
- [ ] Silence is intentional.
- [ ] Captions match the audio exactly.
- [ ] Mono-compatibility check.
- [ ] Rights ledger updated for every track and effect.

## 9. Rights ledger [PROPOSED]

For every voice, music track and sound effect, record: source and URL, creator, licence type and link, date checked, attribution text if required, permitted uses (commercial, monetised YouTube), edits allowed, file name and SHA-256, and any Content ID notes. Treat "unknown" as "not cleared".

## 10. Decisions requiring approval (audio)

| ID | Decision |
|---|---|
| D8 | Human voice actors, AI voices or a hybrid; run auditions first |
| D9 | No narrator in comedy; optional in facts and hypothetical videos |
| D16 | Music direction and sonic logo; sourcing method later |

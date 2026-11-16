# Long-form episodes (5–7 minutes): investigation and plan

**Status (2026-11-16): PLAN ONLY.** Nothing here is implemented, and the short-form workflow is unchanged. The owner decisions in §6 come before any implementation.

## 1. What limits episode length today (verified in the code)

| Limit | Where | Today |
|---|---|---|
| Renderer approval gate | `production/lib/produce.mjs` (`PREVIEW_LIMIT = 60`) | Up to 60 s renders in full. Longer stops at a 60 s preview until the owner's approval note is passed to the renderer's own `approve` command; the toolkit never writes approval itself |
| Studio production limit | Settings → Production `max_seconds` (60) | Production refuses scripts estimated above it |
| Script size | `script_schema.py` | At most 12 scenes, 24 lines per scene, 4 characters |
| Writer | `writer.py` | Asks for 2–6 scenes and returns the whole script in one answer |
| Format | `scene.mjs`, `face-to-face.mjs` | 1080×1920 (9:16). Framing rules, bubbles and safe areas are tuned for vertical |
| Composition | AP-86 S4 (not authorised) | 16:9 framing profiles from one staged scene are S4 work |
| Storyboard review | Episode page | One long page; fine for 4 scenes, unwieldy for 40 |

## 2. Measured performance (this PC, CPU only)

From the 2026-11-16 demo episode, 30 s and 900 frames:
- **Render:** 59–75 s;
- **Storyboard stills:** 18–21 s;
- **QA:** 6–7 s;
- **Compile:** under 1 s;
- **Per-scene preview:** 8–12 s.

| Episode | Frames | Render (this PC, linear estimate) | Server (4 vCPU, estimate ×2) |
|---|---|---|---|
| 45 s Short | 1,350 | about 1.5–2 min | about 3–4 min |
| 6 min episode | 10,800 | about 12–15 min | about 25–30 min |

- These are linear estimates. Memory for a 6-minute render has not been measured.
- The output is about 3.2 MB per 30 s at the current settings, so about 40 MB per 6 minutes. Storage is not a concern.

## 3. Design (short-form untouched)

An episode gets a **format**: `short` (default; everything exactly as today) or `long`. Every change below applies only to `long`.

1. **Writing in two passes (new approval gate).**
   1. **Outline:** 3 acts, 15–40 scenes, recurring bits, cast and twist. The owner approves it.
   2. **Scene scripts:** written act by act from the approved outline, so each answer stays within model output limits and acts stay consistent.

   The script schema gains `acts[]` grouping scenes. Long-format limits are higher: about 60 scenes and 400 lines.
2. **Storyboard by act.** Approval is per act plus a final whole-storyboard approval, with scene stills as today.
3. **Segmented production.**
   - Each act, or block of at most about 60 s, renders as its own engine story through the unchanged `produce` command.
   - The segments are joined with FFmpeg's concat demuxer: same codec and settings, no re-encode. The audio bed is continuous per segment, with crossfades at joins.
   - A failed segment is retried alone, and a revision re-renders only the affected segments, as scene revisions already do for Shorts.
   - The worker renders segments in parallel within its CPU limit.
4. **Renderer approval.** Two options for the owner (D-L2):
   - (a) segments of 60 s or less each render in full under the renderer's preview path;
   - (b) one full render, with the owner's dashboard approval passed as the renderer's approval note.

   Option (a) gives retries and speed. Option (b) keeps the renderer's single-file approval semantics.
5. **Audio.**
   - Voices as today.
   - A music bed: the engine already supports a licensed music track with fades, but it needs a music source decision (D-L4).
   - Loudness normalised to the platform target, YouTube about −14 LUFS, as a final FFmpeg pass.
6. **Format 16:9.** Long YouTube episodes follow AP-20, with 9:16 primary and 16:9 secondary. That depends on AP-86 S4 framing profiles: its approval request is prepared but not authorised, and O11/D18 are open. Until then, long-form can be produced in 9:16 for testing.
7. **QA and review.**
   - Chapter markers from the acts, used in the YouTube description.
   - Per-segment QA plus whole-file QA: duration, frame count and audio continuity at joins.
   - The review page jumps to each act.
8. **Production limits:** a per-format `max_seconds`, with 60 for Shorts and 480 for long-form.

## 4. Implementation phases and effort

| Phase | Scope | Effort |
|---|---|---|
| L1 | Episode format field; long-format schema limits; outline step and gate; act-by-act writer | 2–3 days |
| L2 | Segmented production and FFmpeg concat; per-segment retry and revision; progress per segment | 2–3 days |
| L3 | Act-grouped storyboard and review UI; chapters | 1–2 days |
| L4 | Music bed and loudness normalisation | 1 day (plus D-L4) |
| L5 | 16:9 profile | Depends on AP-86 S4 approval |
| Test | A real 5-minute episode end to end; measure time and memory on the server | 1 day |

## 5. Costs per long episode

Estimates; see `VOICE-AND-CASTING.md`.
- **Voices:** about $0.09 with OpenAI; $0.25–$1.50 with ElevenLabs.
- **Writing:** about $0.05–$0.30 with an API writer, or $0 with Codex.
- **Rendering:** CPU only, $0.

## 6. Owner decisions before implementation

- **D-L1:** long-form aspect ratio: 9:16 now and 16:9 after AP-86 S4, or wait for S4.
- **D-L2:** renderer approval: segments of 60 s or less (recommended), or a full render with the owner's dashboard approval passed as the renderer approval note.
- **D-L3:** target length and structure: for example 3 acts, 5–7 minutes, number of characters on screen (the engine caps it at 4).
- **D-L4:** music: a licensed library, or none.
- **D-L5:** whether long episodes reuse Short storylines (for example "part 2" of an interactive Short) or are always standalone.

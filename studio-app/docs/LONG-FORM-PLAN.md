# Long-form episodes (5–7 minutes): investigation and plan

**Status (2026-11-16): APPROVED AT THE PLANNING LEVEL; DECISIONS D-L1 TO D-L5 SETTLED (§6); NOT IMPLEMENTED.** Implementation starts only on the owner's go, and the short-form workflow is unchanged.

## 1. What limits episode length today (verified in the code)

| Limit | Where | Today |
|---|---|---|
| Renderer approval gate | `production/lib/produce.mjs` (`PREVIEW_LIMIT = 60`) | Up to 60 s renders in full. Longer stops at a 60 s preview until the owner's approval note is passed to the renderer's own `approve` command; the toolkit never writes approval itself |
| Studio production limit | Settings → Production `max_seconds` (60) | Production refuses scripts estimated above it |
| Script size | `script_schema.py` | At most 12 scenes, 24 lines per scene, 4 characters |
| Writer | `writer.py` | Asks for 2–6 scenes and returns the whole script in one answer |
| Format | `scene.mjs`, `face-to-face.mjs` | 1080×1920 (9:16). Framing rules, bubbles and safe areas are tuned for vertical |
| Composition | AP-86 S4 (implemented 2026-11-16; needs a registered set) | 16:9 framing profiles from one staged scene are S4 work |
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
4. **Renderer approval (decided, D-L2 A).** Segments of 60 s or less each render in full under the renderer's preview path, and the approved segments are joined. The owner's approval gates (outline, storyboard, final video) stay in the dashboard.
5. **Audio.**
   - Voices as today.
   - No music at first (D-L4 A): voices and sound effects only. A licensed music bed (the engine supports one with fades) comes later, after the owner chooses a library.
   - Loudness normalised to the platform target, YouTube about −14 LUFS, as a final FFmpeg pass.
6. **Format 16:9.** Long YouTube episodes follow AP-20, with 9:16 primary and 16:9 secondary. That depends on AP-86 S4 framing profiles: S4 is implemented (1080×1920 and 1920×1080 test profiles), but it composes on a registered set plate, and no real set exists yet (O5, O8 open); O11/D18 are open. Until then, long-form can be produced in 9:16 for testing.
7. **QA and review.**
   - Chapter markers from the acts, used in the YouTube description.
   - Per-segment QA plus whole-file QA: duration, frame count and audio continuity at joins.
   - The review page jumps to each act.
8. **Production limits:** a per-format `max_seconds`, with 60 for Shorts and 450 (7½-minute cap, D-L3) for long-form.
9. **Continuation of a Short (D-L5 B).** A long episode is standalone by default. Optionally, the owner can start it from a published or approved Short, whose script and cast are then given to the outline step as the premise.

## 4. Implementation phases and effort

| Phase | Scope | Effort |
|---|---|---|
| L1 | Episode format field; long-format schema limits; outline step and gate; act-by-act writer | 2–3 days |
| L2 | Segmented production and FFmpeg concat; per-segment retry and revision; progress per segment | 2–3 days |
| L3 | Act-grouped storyboard and review UI; chapters | 1–2 days |
| L4 | Loudness normalisation; continuation of a Short (D-L5); music bed later, once a library is chosen | 1 day |
| L5 | 16:9 profile | S4 is implemented; needs a registered real set (O5, O8) |
| Test | A real 5-minute episode end to end; measure time and memory on the server | 1 day |

## 5. Costs per long episode

Estimates; see `VOICE-AND-CASTING.md`.
- **Voices:** about $0.09 with OpenAI; $0.25–$1.50 with ElevenLabs.
- **Writing:** about $0.05–$0.30 with an API writer, or $0 with Codex.
- **Rendering:** CPU only, $0.

## 6. Owner decisions (SETTLED 2026-11-16; do not reopen)

| Decision | Owner's choice | Meaning for implementation |
|---|---|---|
| **D-L1** Aspect ratio | **A** | Long-form starts in 9:16 (1080×1920). 16:9 is added once AP-86 S4 (approved, not yet implemented) is built |
| **D-L2** Rendering | **A** | Segments of 60 s or less, each rendered in full by the unchanged engine; individual retries; a final join of the approved segments |
| **D-L3** Structure | **3 acts, 5–7 minutes, 7½-minute cap** | `max_seconds` 450 for long-form; at most 4 characters on screen at once (engine limit); the episode's total cast is not capped |
| **D-L4** Music | **A initially** | Voices and sound effects only. Licensed music is added later, as its own decision on the library |
| **D-L5** Relationship to Shorts | **B** | Standalone by default; optionally continues a successful Short (for example the winning choice of an interactive Short) |

**Owner requirements for the implementation (binding):**
1. **Story quality over duration.** Never stretch a weak story to reach five minutes.
   - The 5–7 minute target guides the outline. It is not a quota the writer must fill.
   - The outline step reports the estimated runtime and flags padding.
   - A strong story that runs short is offered to the owner as it is, or as a Short, rather than lengthened.
2. **Segment continuity.** Characters, backgrounds, voices, camera direction and audio stay consistent across segments.
   - Every segment is built from the same approved character registries, environment, voice assignments, voice settings and framing defaults.
   - Segment boundaries fall on scene cuts, never inside a line.
   - The audio of adjacent segments is checked at each join (level and silence gaps).
   - The joined file is checked as a whole: duration, frame count and continuous audio.
3. **Selective regeneration.** Editing one scene re-renders only the segment or segments containing it. The other approved segments are reused unchanged, identified by the hash of their inputs, and the final join is redone.

**Status:** approved at the planning level. **Implementation has not started and needs the owner's go.** Shorts are unchanged.

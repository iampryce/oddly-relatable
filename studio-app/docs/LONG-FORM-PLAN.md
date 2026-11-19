# Long-form episodes (5–7 minutes): investigation and plan

**Status (2026-11-16): IMPLEMENTED** on the owner's go (decisions D-L1 to D-L5 in §6; implementation in §7). The short-form workflow is unchanged.

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

**Status:** implemented (§7). Shorts are unchanged.

## 7. Implementation (2026-11-16)

| Part | Where | What it does |
|---|---|---|
| Format | `models.py`, migration `0003` | Ideas and episodes have `format` (short or long) and an optional `continues_episode_id` (D-L5). Additive migration |
| Outline (pass 1) | `longform.validate_outline`, `tasks_long.generate_outline`, `writer.outline_prompt` | Exactly 3 acts; 15–40 scenes; every scene needs at least one story beat; at most 4 characters on screen; over 450 s is refused. Quality flags shown to the owner, never acted on automatically: under 5 minutes ("do not pad: approve as it is or make it a Short"), repeated jokes, thin scenes. Stories can introduce characters, registered as in Shorts. A continuation of a Short gets that Short's script as context |
| Gate | `workflow.py`, `routes_episodes.py` | `outline_review → outline_approved`: no scene is written before the owner approves the outline. Owner edits are saved as new outline versions |
| Scenes (pass 2) | `tasks_long.generate_act`, `writer.act_prompt` | Act 1, then 2, then 3, each from the approved outline, consistent with the acts already written. Each act is validated before the next starts. One act can be rewritten later (`act:N`); single scenes can be regenerated as in Shorts. Over the cap blocks script approval |
| Segments | `longform.plan_segments`, `tasks_long.plan_segments` | Exact timings from the engine (voice-extended). Segments of at most 58 s, cut at scene boundaries; a long scene is split between lines, never inside one. A split keeps the scene's cast, placements and the poses in effect, so continuity holds |
| Continuity | `engine.build_story` | Every segment is built from the same character registries, environments, voice assignments and framing defaults. Only the first segment has the hook and only the last the end card |
| Render | `tasks_long.render_segment` | Each segment goes through the unchanged engine `produce`, with voices placed at the engine's own line timings. Engine QA runs per segment |
| Join | `longform.join_segments` | Video packets are copied (identical renderer settings are verified). Audio is concatenated from each segment's exact mixed WAV and encoded once. Checks: frame count equals the sum of the segments; audio covers the video; audio level just before and after each join matches the joined WAVs (no gap, click or level jump). A join report is stored with the episode |
| Selective regeneration | segment fingerprints; `start_long_scene_jobs` | A segment's fingerprint covers its engine story (minus its revision-specific id), its voice clips, character registries and the engine and renderer code. An unchanged fingerprint reuses the earlier render. Unchanged scenes keep their preparation and voices on a new production run, so editing one scene re-renders only its segment(s) |
| Retries and revisions | `routes_episodes.py` | A failed segment, plan or join is retried on its own. Revisions: script, storyboard scenes, re-produce scenes, or re-render chosen segments |
| Dashboard | `OutlineTab`, `SegmentsPanel`, episode page | Outline review and editing, act-by-act development, act rewrite, segment table (status, render time, reused, preview, retry), segment revisions, final approval |

**Engine fix found by the first long render** (`production/lib/scene.mjs`): the renderer checks each layer's end against the shot span computed by float subtraction of the rounded shot start and end (for example 55.5333 − 51.5667 = 3.96659999…). A layer ending exactly at the scene end (3.9666) failed by a float hair. That can happen in any multi-scene story, but Shorts had not hit it. Such an end is now rounded down to the span; projects the renderer already accepted are unchanged. All seven AP-85 scenes are frame-for-frame identical to the previous commit, and Short 001 baselines pass.

**Tests:** `studio-app/api/tests/test_long_form.py` covers:
- outline rules and quality flags;
- segment planning, including split scenes and the single-line limit;
- joins on real FFmpeg clips, including a refused mismatch;
- outline → acts → act rewrite;
- the complete workflow through the real engine:
  - voiced scenes, several segments and the join;
  - a one-scene revision that re-renders only its segment;
  - an injected segment failure retried on its own;
  - final approval.

**Not yet measured:** a real 5–7 minute episode on the server's CPU (the local test episode is in the progress log).

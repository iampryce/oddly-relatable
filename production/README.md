# Oddly Relatable production toolkit (AP-78, AP-79, AP-82, AP-85 P1)

Turns a story, written as structured data, into a project for the existing renderer (`skills/directing-stickman-videos/`), which is **not modified**. The toolkit only produces the renderer's normal `project.json` input and uses its public functions read-only.

**No new dependencies.** It reuses the renderer's installed `@napi-rs/canvas` and bundled fonts (Noto Sans, Caveat). Requires Node ≥ 20 and, for preview and render, the `FFMPEG` and `FFPROBE` environment variables (as the renderer does).

## Produce an episode (AP-82): one command

```bash
export FFMPEG=/path/to/ffmpeg FFPROBE=/path/to/ffprobe
node production/cli.mjs produce production/stories/short-001-v2.story.json studio-work/short-001-production
```

Stages: validate and compile (characters and environments resolved by ID, hashes verified), then audio bed, storyboard, render with the **unmodified** renderer, audio export, QA, reports and manifest. Exit code 0 means `produced`; 2 means QA failed or the run is awaiting approval. Output folder:

| Path | Content |
|---|---|
| `project/` | compiled renderer project (`project.json`, copied artwork, generated graphics, audio bed, renderer `output/`) |
| `storyboard/storyboard-sheet.png`, `storyboard/frames/` | renderer-exact stills at every beat and camera move |
| `render/<id>.mp4` | the episode (1080×1920, 30 fps) |
| `audio/<id>.wav` | the final mixed audio, exported from the MP4 |
| `reports/layout-report.json`, `reports/qa-report.json` | layout checks and machine-readable QA (pass / fail / warn per check, with fixes) |
| `production-manifest.json` | inputs (story, registries, environment registry, artwork, audio sources) and outputs with SHA-256, renderer script hashes, git HEAD, Node and FFmpeg versions |
| `production-run.json` | stage timings, status, errors |

- **Overwrite protection:** a new or empty folder, or an earlier `produce` folder with `--replace`. Any other folder is refused, and nothing is deleted.
- **Full-length render:** episodes up to 60 s are rendered in full through the renderer's `preview`. Longer episodes stop as `awaiting-approval` after a 60 s preview. Once the owner has reviewed it, re-run with `--approval-note "<owner's words>"`, and the renderer's own `approve` and `render` run. The tool never writes approval itself.
- **Audio:** optional. A story may add `"audio": {"voice": [{source, sha256, licence, start, gain}], "music": {source, sha256, licence, gain, fadeIn, fadeOut}}`. Sources must be existing local files whose recorded hash matches, with a licence note. They are mixed with a limiter (no clipping) into a bed of the exact episode length, and the renderer adds its built-in SFX on top. Without sources the bed is silent, so the audio is SFX only. Nothing is downloaded or generated.
- **QA checks:**
  - Referenced assets are present and unchanged since the build.
  - H.264 codec, resolution, frame rate, duration, and exact frame count (packet count).
  - Full decode, black-frame runs (0.5 s or longer), audio present, no clipping, audio activity when SFX or a bed are expected.
  - Audio file duration, and layout issues.
  - Softness warnings are reported as `warn`.
- **QA is technical only:** a pass is not publication approval.

## Commands

```bash
# Compile a story (or an AP-78 conversation episode) into a renderer project
node production/cli.mjs build production/stories/short-001-v2.story.json studio-work/short-001-v2-ap79

# Inspect: renderer-exact stills at every beat and camera move, as one labelled sheet (no encode)
node production/cli.mjs storyboard studio-work/short-001-v2-ap79/project.json

# Optional MP4 preview through the unmodified renderer CLI (max 60 s)
node production/cli.mjs video studio-work/short-001-v2-ap79/project.json --seconds 60 --replace

# Tests (renderer-backed and production tests need FFMPEG/FFPROBE)
node --test production/tests/*.test.mjs
```

`build` fails if a check fails: a bubble outside the platform safe zone, the hook over the header, or the camera cropping a face. `--allow-issues` writes the project anyway and lists the issues in `layout-report.json`. Softness warnings (a pose enlarged above 1.7× on screen) are reported but do not fail the build.

## Architecture (AP-79): one responsibility per layer

| Layer | Data | Module |
|---|---|---|
| Story | `stories/*.story.json`: title, format, hook, end card, ordered scenes | `lib/story.mjs` (validation, AP-78 episode adapter, environment resolution) |
| Scene format | each scene names a format; one strategy per format | `lib/formats/` (`text-chat` and `face-to-face` implemented; `phone-call`, `split-screen`, `solo` declared, not implemented) |
| Environment | `environments/environments.json` (ID → file, SHA-256) | `lib/story.mjs` |
| Character / cast | `characters/<character-id>.json` pose registries; a scene's `cast` lists members by character ID with placement, height, `z`, `facing` and (for members who speak) `speech` | `lib/cast.mjs`, `lib/character.mjs` |
| Dialogue / audio | scene `speakers` and `events` (messages, typing, pauses, pose changes, built-in SFX cues) | `lib/conversation.mjs` |
| Camera | per-beat `camera` notes taken from the script | `lib/camera.mjs` |
| Animation timeline | pose segments per cast member, transitions | `lib/timeline.mjs` |
| UI graphics and layout | bubbles, typing indicator, header, hook, end card; chat stack | `lib/graphics.mjs`, `lib/layout.mjs` |
| Render / post | renderer project (one shot per scene), silent track, reports, provenance, storyboard | `lib/scene.mjs`, `lib/preview.mjs`, `lib/wav.mjs` |

Stories never contain image paths for characters. They name a character ID, and the registry resolves the pose files, verifying each file's SHA-256.

**Renderer contract used (verified in `autopilot-core.mjs` and `autopilot-render.mjs`):**
- Style B1, contiguous shots.
- `image` layers with `from`/`to` visibility windows and `keys` (`t`, `x`, `y`, `w`, `alpha`), painted in array order.
- At least one single-line caption.
- An audio track whose length sets the duration.
- Built-in SFX `tap`, `paper`, `pop`, `chime`, `jingle` (gain ≤ 0.3).

## Camera (outside the renderer)

- **How it moves:**
  - Zoom about a pivot that stays fixed on screen. The pivot is the focus cast member's head top, so the face grows downward and never rises into the chat zone; feet crop in medium shots.
  - The camera transforms world layers only (environment, characters, shadows). Screen-space UI (bubbles, header, hook, end card) is never moved or scaled.
- **Frame-exact keys:** keys are sampled on the frame grid wherever the camera or a transition changes, and compressed on holds. The renderer never interpolates between moving keys.
- **Limits:**
  - Zoom is limited to 1×–1.5× (the approved limit for sheet poses).
  - Shake and drift offsets are clamped so the background always covers the frame.
  - A per-frame check fails the build if a face is cropped.

| Script note | Mapping |
|---|---|
| `Wide` | zoom 1.0, cut at the beat start |
| `Medium N×` (or `Medium`) | zoom N (default 1.3), cut |
| `Close` | zoom = 1.5 (cap), cut |
| `Hard cut, …` | explicit cut. Framing changes at a beat start are cuts anyway |
| `Slow push-in to N×` | eased zoom over the whole beat. `Push-in` without "slow" runs over min(1 s, beat) |
| `Pull back to wide` | eased zoom to 1.0 over min(1.2 s, beat) |
| `Hold`, `Still` | no change |
| `small shake`, `shake` / `drift` | decaying shake / slow drift over the beat |

Unknown wording is rejected, not guessed.

## Pose transitions

`transition` on an event applies to the pose change it makes:
- `cut` (default): the AP-78 behaviour.
- `pop`: a 0.2 s scale bounce anchored at the feet; the size returns exactly to 1.
- `crossfade`: a 0.16 s dissolve-over. The incoming pose fades in on top while the outgoing pose stays opaque, so the room never shows through.

Transitions only move, scale or fade existing artwork; no in-between drawings are created.

## Story format (`oddly-relatable/story@1`)

```jsonc
{
  "schema": "oddly-relatable/story@1", "id": "my-story", "title": "My Story",
  "format": {"width": 1080, "height": 1920, "fps": 30},
  "hook": {"text": "Four words. No warning.", "start": 0, "duration": 3},
  "endCard": {"duration": 3, "lines": [{"text": "My Story", "size": 92}], "caption": "Oddly Relatable"},
  "scenes": [{
    "id": "scene-1", "format": "text-chat", "environment": "living-room-empty-03",
    "cast": [{"id": "him", "character": "character-01", "placement": {"feetX": 640, "feetY": 2070, "figureHeight": 880}, "z": 0, "facing": "native"}],
    "reactionCast": "him", "camera": {"focus": "him", "maxZoom": 1.5},
    "header": {"label": "Wife", "icon": "heart"},
    "speakers": {"her": {"side": "left", "style": "her"}, "him": {"side": "right", "style": "him"}},
    "events": [
      {"type": "message", "speaker": "her", "text": "We need to talk.", "duration": 3, "pose": "02", "sfx": "chime", "camera": "Wide, still"},
      {"type": "typing", "speaker": "her", "duration": 3, "visible": 2.4, "camera": "Hold"},
      {"type": "message", "speaker": "him", "text": "Define March.", "duration": 2, "poses": {"him": "03"}, "transition": "pop", "camera": "Medium 1.3×"}
    ]
  }]
}
```

- **Multi-character:** `pose` targets `reactionCast`; `poses: {castId: poseId}` sets several members at once.
- **Multi-scene:** stories with several scenes become several contiguous renderer shots. The hook overlays the first shot and the end card extends the last.
- **AP-78 files still work:** `oddly-relatable/conversation-episode@1` is converted to a one-scene story.
- **Units:** renderer design units (the frame is 1280 wide; 1080×1920 output is 1280×2275.6).

### Face-to-face scenes (AP-85 P1)

```jsonc
{
  "id": "two-shot", "format": "face-to-face", "environment": "living-room-empty-03",
  "cast": [
    {"id": "a", "character": "character-01", "placement": {"feetX": 400, "feetY": 2070, "figureHeight": 800}, "z": 0,
     "speech": {"style": "him"}},
    {"id": "b", "character": "character-02", "placement": {"feetX": 880, "feetY": 2070, "figureHeight": 760}, "z": 1,
     "facing": "left", "speech": {"style": "her"}}
  ],
  "lines": [
    {"speaker": "a", "text": "Wide.", "duration": 1.5, "poses": {"a": "02", "b": "p1"}, "shot": {"camera": "Wide"}},
    {"speaker": "b", "text": "Single on b.", "duration": 1.5, "pose": "p2", "shot": {"camera": "Medium 1.3×", "focus": "b", "single": true}},
    {"speaker": "b", "text": "Reaction on a.", "duration": 1.5, "poses": {"a": "05"}, "shot": {"camera": "Close", "focus": "a", "single": true}}
  ]
}
```

(`character-02` above is illustrative: no Character 02 registry or artwork exists.)

- Every speaker is a cast member with `speech: {style}`. Every member needs a pose on the first line; `pose` targets the speaker.
- **Bubble side follows the speaker** (AP-85 owner review): each bubble, and its tail, goes on the side of the screen where its speaker stands in that line's shot, including a speaker who is off camera. A declared `speech.side` is checked against that, and a contradiction is an error. Bubbles are screen-space.
- Every line has a `shot`. Medium and close shots need a `focus` (a cast member) and are **composed**: zoom levels are unchanged, and the camera pans to centre the focus member within the background. Every other member must be fully in frame or fully out, never cut by the frame edge, and the focus member must be clearly the most central figure. `"single": true` shows only the focus member for that shot. A framing that cannot meet these rules is an error with a reason. Positions and scale are never changed. Camera moves, shake and drift are refused in this format.

### No silent defaults (AP-85 P1)

- **Bubble styles** come from the speaker's configuration (`style`, or the linked cast member's `speech.style` via `"cast"` in text-chat speakers), never from left/right. A speaker with no style is an error.
- **Characters:** a story scene must name its `format`; a registry must name its `character` and match the member that uses it; an unknown cast member, focus, reaction member or speaker is an error. Nothing falls back to Character 01.
- **Facing is data.** `native` (the default) uses each pose as drawn. `left`, `right` or `front` resolves each pose to artwork the registry declares as facing that way (the pose's own `facing`, or its `facingVariants`), or fails. Artwork is never mirrored, and `mirror` is refused.
- **Synthetic registries** (`"synthetic": true`, labelled test placeholders) are refused unless the caller passes `allowSynthetic`, which only tests do. `produce` and the CLI never pass it.

## Fixtures and evidence

- **`stories/short-001-v2.story.json`:** Short 001. Its dialogue is identical to `fixtures/short-001-v2.conversation.json`, and its camera notes are verbatim from `bible/episodes/short-001-we-need-to-talk/SCRIPT_V2.md` (tests enforce both). Character 01 only; pose changes stay hard cuts, because the script specifies none.
- **`fixtures/synthetic-two-member-cast.story.json`:** **technical test only.** Two independently placed instances of Character 01 exercise the cast model, z-order, every transition and every camera feature. It is not a second character.
- **`tests/fixtures/ap85-placeholder.mjs`:** **test fixture only.** Writes a labelled synthetic placeholder ("SYNTHETIC / PLACEHOLDER / NOT ARTWORK", blue body, green head) and a `synthetic: true` registry into temporary folders for the AP-85 Track A tests. It is not Character 02, not a design, and can never be produced.
- **`tests/ap85-track-a.test.mjs`:** AP-85 Track A (composition architecture) checks A-1 to A-10 on scenes A1 to A6. Track A results say nothing about any character's identity (Track B). `evidence/ap85/regression-baseline.json` holds the pre-AP-85 hashes that A-10 compares against.
- **Evidence:** `evidence/ap78/` and `evidence/ap79/` hold storyboards, previews, layout reports, the AP-78 vs AP-79 comparison and a render summary with a PSNR regression check. All technical evidence only, not production approval.

## Limitations

- **Formats:** `text-chat` and `face-to-face` are implemented. The other formats are declared strategies that fail clearly.
- **Facing:** Character 01's registry declares no facings, so it can only be used `native`. Another facing needs artwork drawn that way (owner decision M7). The B1 renderer cannot mirror images and the engine never mirrors.
- **Close-up softness:** sheet poses are about 550 px tall, so at 1.5× zoom they are enlarged about 2× on screen (reported as softness warnings).
- **Crossfade ghosting:** a short dissolve between two different drawings briefly shows both.
- **Not built:** lip-sync, voices and music. SFX are the renderer's built-in synthesized sounds.
- **One caption required:** the renderer requires at least one caption, so the end card carries one by default.

# Oddly Relatable production toolkit (AP-78)

Turns a comedy **conversation script, written as structured data,** into a project for the existing renderer: text-message bubbles, typing indicator, hook, end card and character reactions in a 9:16 scene. The existing renderer (`skills/directing-stickman-videos/`) is **not modified**; this toolkit only produces its normal `project.json` input and uses its public functions read-only.

**No new dependencies.** It reuses the renderer's installed `@napi-rs/canvas` and bundled fonts (Noto Sans, Caveat). Requires Node ≥ 20 and, for preview/render, `FFMPEG` and `FFPROBE` environment variables (as the renderer does).

## Commands

```bash
# 1. Compile an episode into a renderer project (assets, silent track, project.json, reports)
node production/cli.mjs build production/fixtures/short-001-v2.conversation.json studio-work/short-001-v2-compat-test

# 2. Inspect: renderer-exact stills at every beat, as one labelled sheet (no video encode)
node production/cli.mjs storyboard studio-work/short-001-v2-compat-test/project.json

# 3. Optional MP4 preview through the unmodified renderer CLI (max 60 s)
node production/cli.mjs video studio-work/short-001-v2-compat-test/project.json --seconds 60 --replace

# Tests
node --test production/tests/*.test.mjs
```

`build` fails if the layout checks fail (bubble over the face, hook over the header, text outside the platform safe zone); `--allow-issues` writes the project anyway and lists the issues in `layout-report.json`.

## Architecture (one responsibility per module)

| Module | Responsibility |
|---|---|
| `lib/conversation.mjs` | Conversation data: validation and sequencing (messages, typing, pauses, pose changes, SFX cues, hook/end-card timing). Generic; no episode knowledge. |
| `lib/graphics.mjs` | Message bubbles (left/right), typing shell and dots, contact header with vector heart, title card (hook and end card), contact shadow. Drawn as PNGs because the B1 renderer composites image layers only. |
| `lib/layout.mjs` | Chat stack: newest at the bottom, earlier bubbles slide up, items above the zone fade out, typing takes and releases a slot. Emits renderer keyframes; composition checks. |
| `lib/character.mjs` | Character reactions: pose registry, feet-anchored placement and scale, face boxes, softness warning. Existing artwork only. |
| `lib/scene.mjs` | Compiler: episode → renderer project folder (copies sources, writes generated PNGs, silent track, `project.json`, `layout-report.json`, `production-manifest.json` with SHA-256 of every file). |
| `lib/preview.mjs` | Storyboard: exact frames from the renderer's own `loadProject` + `painter`, as a labelled sheet. |
| `lib/palette.mjs`, `lib/text.mjs`, `lib/wav.mjs`, `lib/runtime.mjs` | Canon colour tokens, wrapping and emoji guard, silent WAV, shared runtime and write-protection. |

**Renderer contract used (verified in `autopilot-core.mjs` / `autopilot-render.mjs`):** style B1, one shot covering the whole duration, `image` layers with `from`/`to` visibility windows and `keys` (`t`, `x`, `y`, `w`, `alpha`), painted in array order; at least one single-line caption; an audio track whose length sets the duration; built-in SFX kinds `tap`, `paper`, `pop`, `chime`, `jingle` (gain ≤ 0.3).

## Episode format (`oddly-relatable/conversation-episode@1`)

```jsonc
{
  "schema": "oddly-relatable/conversation-episode@1",
  "id": "my-episode", "title": "My Episode",
  "format": {"width": 1080, "height": 1920, "fps": 30},
  "background": {"path": "bible/concepts/lookdev-richenv/lookdev-room-empty-03.png"},
  "character": {"registry": "production/characters/character-01.json", "placement": {"feetX": 640, "feetY": 2070, "figureHeight": 880}},
  "header": {"label": "Wife", "icon": "heart"},
  "speakers": {"her": {"side": "left", "style": "her"}, "him": {"side": "right", "style": "him"}},
  "timing": {"readingCps": 15, "minMessage": 2.0, "maxMessage": 4.5},
  "hook": {"text": "Four words. No warning.", "start": 0, "duration": 3},
  "events": [
    {"type": "message", "speaker": "her", "text": "We need to talk.", "duration": 3, "pose": "02", "sfx": "chime"},
    {"type": "typing", "speaker": "her", "duration": 3, "visible": 2.4},
    {"type": "pause", "duration": 1},
    {"type": "pose", "pose": "03"}
  ],
  "endCard": {"duration": 3, "lines": [{"text": "My Episode", "size": 92}], "caption": "Oddly Relatable"}
}
```

- Units are renderer design units (the frame is 1280 wide; 1080×1920 output is 1280×2275.6).
- `start` is optional; events run back to back. A message's `duration` is its beat length; it stays in the chat afterwards. Missing durations use a reading-time estimate.
- Optional overrides: `layout` (margins, chat zone, slide timing, safe zone), `bubbles` (font size, padding, max width), `captions` (otherwise the end card's `caption` is used, shown on a light footer band).
- Emoji are rejected (the bundled font has none); use `header.icon: "heart"`.

## Short 001 compatibility test

`fixtures/short-001-v2.conversation.json` transcribes `bible/episodes/short-001-we-need-to-talk/SCRIPT_V2.md` (unchanged) as test data, with the expected hook revision "Four words. No warning.". Evidence in `evidence/ap78/`: storyboard sheet (21 renderer frames), motion frames from the rendered MP4 (slide-in, typing pulse and removal, end-card fade), the 54 s preview MP4, layout report and render summary. **Technical compatibility only; not production-approved.**

## Limitations

- Static framing: no camera moves (the script's "push-in" / "pull back" notes are not implemented). The background is fixed and the character scale is constant.
- Pose changes are hard cuts; no in-between animation or lip-sync.
- Sheet poses are about 550 px tall and are enlarged about 1.3× here; the report flags anything above 1.7×.
- Pose 06 is the uncorrected extract (skin correction not yet done); poses 02 and 05 are TEST corrections awaiting owner review (see `characters/character-01.json`).
- SFX are the renderer's built-in synthesized sounds; no music.
- The renderer requires at least one caption, so the end card carries one by default.

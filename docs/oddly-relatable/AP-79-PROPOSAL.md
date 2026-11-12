# AP-79 proposal: animation system (camera, transitions) on a multi-character, multi-format architecture

**Status: APPROVED by the owner (2026-11-12) and IMPLEMENTED in AP-79** (see `production/README.md` and `DECISIONS.md` AP-79). Section 4 approvals were all given; text-chat is the only implemented format. Prepared 2026-11-12 after AP-80.

## 1. Owner requirements this proposal must respect

1. **Short 001 keeps its approved format:** text-message conversation, Character 01 on screen, the wife off screen as messages (`bible/episodes/short-001-we-need-to-talk/SCRIPT_V2.md`, approved working script).
2. **Multiple characters (future):**
   - Independent character registries, with separate poses, expressions and reactions per character.
   - Several characters sharing a scene, each with its own position, scale and layering.
   - Character-to-character interaction and dialogue.
   - Consistent designs across episodes.
   - No Character 02 is created now.
3. **Flexible storytelling formats (future):**
   - Phone calls.
   - Split-screen conversations.
   - Face-to-face dialogue.
   - Text-message stories.
   - Multi-scene stories with locations, camera angles and transitions.
   - Solo scenes: monologue, reactions, physical comedy.
4. **Separation of concerns:** story/script, scenes/environments, characters, dialogue/audio, camera/shots, animation timelines/transitions, rendering/post.
5. **Unchanged constraints:**
   - The renderer is not modified.
   - No image generation without approval.
   - Locked visual identity.
   - Propose architecture before major changes.

## 2. Proposed architecture (layers, each a separate data file and module)

| Layer | Data | Module (outside the renderer) |
|---|---|---|
| Story | `story.json`: title, ordered scenes, cast list | `story` loader / validator |
| Scene | `scene` entries: environment, format (text-chat, phone-call, split-screen, face-to-face, solo), cast placements, duration | `scene` compiler, one strategy per format |
| Character | one registry per character (`production/characters/<id>.json`): poses, expressions, anchors, head box, status | `character` (already registry-based in AP-78) |
| Dialogue / audio | lines with speaker, text, timing, optional voice file, SFX | `dialogue` sequencer (generalises AP-78 `conversation`) |
| Camera | per-scene shot list: framing (wide/medium/close), push-in, pull-back, pan, shake, cut, with zoom caps per asset resolution | `camera` (new in AP-79) |
| Animation | pose timeline per character, transitions (cut, quick cross-fade, squash pop, slide-in) | `timeline` (new in AP-79) |
| Render / post | renderer `project.json` (one or more shots), captions, preview, storyboard | existing `scene` compiler + `preview` |

**Key design choice:** every layer refers to characters by **ID** (`character-01`, later `character-02`), never by hard-coded paths. Each scene declares a cast with per-character placement (feet point, height, z-order, facing). The AP-78 single-character code becomes the one-member case of this. A text-chat scene is one format strategy. Phone call, split screen, face to face and solo are further strategies that share the camera, timeline and character layers.

## 3. AP-79 scope (proposed; for Short 001 first)

1. **Camera layer:**
   - Push-in, pull-back, gentle drift and a small shake, applied consistently to the background and character layers.
   - Bubbles stay screen-fixed (UI), not scaled with the camera.
   - Zoom capped per pose resolution (sheet poses ≤ 1.5×).
2. **Pose transitions:** hard cut (current), plus a short "pop" (a few-frame scale bounce anchored at the feet) and a quick cross-fade.
3. **Cast model:**
   - Generalise `character.placement` to `cast: [{character, registry, placement, z}]`.
   - Short 001 uses one member, so its output stays the same unless camera moves are added.
4. **Script-to-timeline:** map the script's camera notes ("push-in", "pull back to wide", "hard cut, medium") to camera keys.
5. **Tests:**
   - Keyframe maths: camera keys stay strictly increasing and apply the same transform to the background and characters.
   - A two-member cast built from Character 01's own poses, as a synthetic test only, to prove multi-character layering and z-order without new art.
   - Renderer-backed pixel checks, storyboard and an MP4 preview of Short 001 as a technical test.
6. **Not in AP-79:** new characters, phone-call/split-screen/face-to-face strategies (designed for, not built), lip-sync, voices, music, final production.

## 4. Approvals needed before AP-79 starts

1. This architecture (layers, character IDs, cast model, format strategies).
2. The AP-79 scope in section 3.
3. Whether pose 06's corrected TEST version replaces the uncorrected extract in the Character 01 registry once you approve it visually. The AP-78 registry still lists poses 02 and 05 as "awaiting review". Updating it is a toolkit data change, so it is proposed here, not done.

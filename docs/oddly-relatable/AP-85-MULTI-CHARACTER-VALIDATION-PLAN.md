# AP-85: multi-character validation plan

**Status (2026-11-15): M1 and M2 APPROVED; Phase 1 (Track A) IMPLEMENTED (§5.3); Track A NOT YET ACCEPTED: first owner review done (A1 passes; A3a/A3b pass the technical layer-order checks; A2 and A4 needed corrections, now made); the owner's review of the corrected A2 and A4 sheets is pending. M3 to M8 OPEN; Track B not started.**
- No Character 02 artwork exists or is created by this plan. No existing character asset, registry, story or renderer is changed.
- No GPU, account, spending, model download or image generation. AP-84B3 and its approved locks are not touched or extended, and AP-84B3 D1-7 remains NOT AUTHORISED.
- Every phase below needs its own owner approval (§9). Only P0 (M1) and P1 (M2) are approved.

**Builds on:** owner requirement AP-80R (multiple characters, flexible formats, separation of concerns), the AP-79 architecture (story/scene/cast/camera/timeline/format layers), and the locked visual identity (AP-51 to AP-57, `bible/VISUAL_IDENTITY.md` §4 and §5). It does not restate or change them.

## 1. Purpose

Prove, in two separate ways, that two characters can share dialogue scenes without losing their identities:

1. **Track A: composition architecture.** The production engine places, layers, times and voices two independent characters correctly. Deterministic, local, $0. Uses Character 01's approved poses and a clearly labelled synthetic placeholder for Character 02.
2. **Track B: identity consistency.** Real Character 02 artwork (however it is eventually produced) and Character 01 keep their own faces, clothing, proportions and expressions across poses and shots, with no swapping or blending.

**Passing one track never implies the other has passed.** Track A shows that the engine does not mix characters up. It says nothing about whether any artwork, hand-made or AI-generated, keeps a character's identity. Track B says nothing about the engine. Every report states its track, and neither can be cited as evidence for the other.

## 2. Fixed constraints

| Constraint | Source |
|---|---|
| Character 01 is the canonical existing character; its design, poses, registry and approvals are unchanged | AP-52, AP-58 to AP-80, `production/characters/character-01.json` |
| Every new character belongs to the same visual universe and passes the same-universe check before approval | `bible/VISUAL_IDENTITY.md` §5 |
| No new character is designed or generated without the owner's approval | `bible/CHARACTER_BIBLE.md`, `VISUAL_IDENTITY.md` §5 |
| Short 001 keeps its approved text-message format with Character 01 on screen | AP-77, AP-80R |
| The renderer is not modified | AP-79 |
| AP-84B3 scope, locks and gates unchanged; D1-7 not authorised | `DECISIONS.md` AP-84B3 records |

## 3. Character 02: design brief requirements (not a design)

Character 02 is to be a **genuinely distinct, clearly feminine** character in the same locked 2D universe. This section lists requirements and the choices the owner must make. It does not propose a design.

**Shared with Character 01 (must not differ):**
- The same flat 2D technique, bold clean black outline weight, no shading.
- The same construction: simple body, thin black limbs, round expressive face.
- The same expression language: large white eyes with dark pupils, thick expressive brows, simple mouth shapes.
- The same polish, and the same relationship to detailed environments.

**Distinct from Character 01 (must differ clearly):**
- **Silhouette.** Character 01 is bald with a round head and small ears, so a hairstyle is the strongest silhouette difference available. It must be recognisable in solid black alone.
- **Colour identity.** A signature clothing colour clearly separate from Character 01's rust (in hue, not only shade), so the two never read as the same outfit.
- **Facial characteristics** within the same line language, for example brow shape, lashes drawn in the same outline weight, and mouth shape.
- **Clothing silhouette** different from a turtleneck.
- **Proportions** where appropriate, without breaking the shared construction rules.

**Feminine reading.** The owner requires Character 02 to read as clearly feminine at a glance, including in a wide two-shot. Which cues carry that (hairstyle, lashes, clothing silhouette, accessories) is an owner decision (M4). The design must not rely on a single small feature that disappears at small sizes.

**Distinctness tests applied to the design before approval:**
1. The seven-point same-universe check in `VISUAL_IDENTITY.md` §5.
2. **Silhouette test:** both characters filled solid black at the same height must be told apart instantly.
3. **Greyscale test:** both converted to greyscale must still be told apart.
4. **Small-size test:** both at 120 px tall (a wide shot on a phone) must still be told apart.
5. **Originality:** no resemblance to the owner's reference creator's characters or any existing character.

**Open decisions this touches.** Character 02's role and relationship to Character 01 (for example, whether she is the wife who is off screen in Short 001) connect to the still-open cast decisions D4 and D5. This plan does not decide them (M3).

## 4. Findings in the current code (inspected 2026-11-15)

| # | Finding | Where | Effect on multi-character work |
|---|---|---|---|
| F1 | The cast model already takes several members, each with its own character ID, registry, placement, height, z order and facing, and verifies each registry's file hashes | `production/lib/cast.mjs` | The foundation exists; Track A tests it with two members |
| F2 | Only the `text-chat` format is implemented; `face-to-face`, `phone-call`, `split-screen` and `solo` are registered as planned | `production/lib/formats/index.mjs` | Dialogue scenes with both characters on screen need `face-to-face` |
| F3 | Chat bubble and typing styles default to `her` (left) and `him` (right) | `production/lib/graphics.mjs`, `formats/text-chat.mjs` | Speaker styling is tied to side and gender words; it should come from the speaker's own configuration |
| F4 | Facing is limited to `native`: the renderer cannot mirror images | `production/lib/cast.mjs` | Characters facing each other need artwork drawn for each facing; mirroring an asymmetric design would change the character (M7) |
| F5 | The story loader falls back to `character-01` when a registry names no character | `production/lib/story.mjs` | A missing field must be an error, not a silent Character 01 |
| F6 | Studio validation compares a candidate only with approved poses of its own character | `studio/lib/asset-intel.mjs` (`palette-consistency`, `pose-proportions`) | Nothing checks that a candidate is NOT the other character; Track B adds cross-character checks |
| F7 | Canonical references are listed per character | `studio/config/canonical-references.json` | Character 02 needs its own entry once its master is approved |

## 5. Track A: composition architecture tests (deterministic, local, $0)

**Character 02 stand-in.** A synthetic placeholder figure generated by code, in the shape of a character registry (`character-02-placeholder`), with flat, unmistakable test colours and the label "SYNTHETIC PLACEHOLDER, NOT ARTWORK". It exists only in test fixtures, can never be promoted, and is never an attempt at Character 02's design. Character 01 uses its approved poses unchanged.

**Why it can detect swapping and blending.** The placeholder's colours are chosen to share no pixels with Character 01. Any rendered frame can therefore be checked pixel by pixel: every pixel inside a cast member's expected region must belong to that member, so a swap or mix shows up as wrong-coloured pixels.

### 5.1 Test scenes

| Scene | Content | What it exercises |
|---|---|---|
| A1 two-shot | Character 01 left, placeholder right, both full figure, 8 alternating lines, a pose change on every line | Independent pose timelines, speaker attribution |
| A2 swapped | The same lines with positions swapped and z order reversed | Nothing depends on left/right or on declaration order |
| A3 overlap | Placeholder partly in front of Character 01, then behind | Layering and occlusion |
| A4 shot sequence | Wide, single A, single B, reaction A, reaction B, wide, over 6 shots | Camera focus per speaker, consistency across shots |
| A5 scale and depth | One character at 0.8× height further back | Independent scale and placement |
| A6 three members | Character 01 and two placeholder instances | No assumption of exactly two |

### 5.2 Checks and acceptance criteria

| # | Check | Pass when |
|---|---|---|
| A-1 | Registry independence | Each member resolves its own registry and hashes; a member pointing at another character's registry is refused; changing one registry leaves the other member's render plan byte-identical |
| A-2 | Pose timelines | Changing one member's poses changes no layer of the other member (render-plan diff is empty for the other member) |
| A-3 | Placement | Feet anchor within ±1 px and figure height within ±1 px of the declared values at every keyframe, for every member |
| A-4 | Layering | Layer order equals the declared z order in every frame; in overlaps, every sampled overlap pixel belongs to the front member |
| A-5 | Identity separation in frames | In sampled frames (at least every 0.5 s and every pose change), 100% of opaque pixels in each member's region belong to that member; zero foreign pixels |
| A-6 | Speaker attribution | Every line is attributed to the declared cast member; bubble side and style come from the speaker's configuration, not from left/right defaults |
| A-7 | Camera | Each shot's focus matches the declared speaker; reaction shots frame the declared reactor |
| A-8 | No silent defaults | A registry without a character ID, an unknown facing, an unknown format or a speaker with no cast member is an error |
| A-9 | Determinism | The same story gives a byte-identical render plan twice |
| A-10 | Regression | Short 001 renders unchanged; all existing suites keep their current results |

**Track A acceptance requires both:** (1) every check A-1 to A-10 passes on scenes A1 to A6, and (2) the owner reviews the contact sheets of A1 to A4 (A3 in both orders) and confirms the scenes read as intended. The owner review is **required, not optional**; passing checks alone do not accept Track A. Acceptance approves the engine only.

### 5.3 Phase 1 results (2026-11-15)

Implemented in `production/lib` (`formats/face-to-face.mjs`, `cast.mjs`, `character.mjs`, `conversation.mjs`, `graphics.mjs`, `story.mjs`, `scene.mjs`, `formats/text-chat.mjs`). Findings F3 (styles by side), F4 (facing as data, without new artwork; never mirrored) and F5 (no Character 01 fallback) are resolved. The placeholder lives only in `production/tests/fixtures/ap85-placeholder.mjs`, is labelled on the figure, is marked `synthetic: true`, and is refused by every production path.

Tests: `production/tests/ap85-track-a.test.mjs`, 14 tests, all passing (renderer painter with FFmpeg).

| # | Result | Scenes |
|---|---|---|
| A-1 | Pass | A1 (own registry and hashes; wrong, unnamed and synthetic registries refused; another registry leaves the member's plan byte-identical) |
| A-2 | Pass | A1 (pose changes for one member leave the other member's layers unchanged, both ways) |
| A-3 | Pass | all (feet and height within 1 px at every key) |
| A-4 | Pass | A1, A2, A3a, A3b, A5, A6 (paint order); A3a and A3b in pixels (the front member wins every overlapping pixel) |
| A-5 | Pass | A1, A2, A4, A5 in rendered frames: zero foreign pixels, every pixel inside its declared rectangle; a swapped plan is detected. A6's two placeholder instances share colours, so they are separated by A-3 and A-4, not by colour |
| A-6 | Pass | A1, A2 (bubble colour sampled from the speaker's style; swapped positions keep each speaker's style); text-chat `cast` link |
| A-7 | Pass | A4 (wide, single, reaction shots; focus and pivot) |
| A-8 | Pass | A1 variants (missing or invalid character, registry, facing, format, speaker, focus, unposed member) |
| A-9 | Pass | all (byte-identical plan, report and assets twice) |
| A-10 | Pass | Short 001, AP-78 fixture, AP-79 fixture byte-identical to the baseline at `2b480b3`; Short 001 renderer frames identical |

**Owner review 1 (2026-11-15) and corrections.** A1 passes; A3a and A3b pass the technical layer-order checks. The owner asked for two corrections before acceptance:
- **A2:** bubbles stayed on their configured screen side after positions were swapped. Bubbles now go on the side where the speaker stands in each shot, tail included; style still comes only from the speaker's configuration. A declared `speech.side` is a checked constraint.
- **A4:** shots 2 and 3 were not distinct, and shot 5 cut Character 01 at the edge. Medium and close shots are now composed, with zoom, positions and scale unchanged:
  - the camera pans to centre the focus member within the background;
  - no member is cut by the frame edge;
  - the focus member must be clearly the most central figure;
  - an explicit `"single": true` shows only the focus member.

  A4's shots 2 to 5 now declare the singles their captions describe. Framings that cannot meet the rules are refused with a reason.

A1, A3a, A3b, A5 and A6 render byte-identically: the render plan, the generated assets and every frame at 0.1 s steps (`production/evidence/ap85/review/unchanged-check.json`). The corrected A2 and A4 sheets are in `production/evidence/ap85/review/`. Track A remains **not accepted** until the owner reviews them.

At P1: production 82/82 with FFmpeg; studio 64/64; renderer 134/135 (the pre-existing Jensen baseline failure). Track A says nothing about Character 02's identity. The required owner contact-sheet review is **pending**; the sheets are in `production/evidence/ap85/review/` (README there lists what to inspect, including how the A4 "focus" pivot frames shots). Track A is not accepted until the owner completes it.

## 6. Track B: identity-consistency tests (real Character 02 artwork)

Track B starts only when an owner-approved Character 02 master and pose set exist (Phase 3). It applies to artwork however it was made. If the owner chooses AI generation for Character 02, that is a **separate experiment with its own lock, budget and approval gates**; AP-84B3 locks and approvals do not carry over.

### 6.1 Sub-tracks

| Sub-track | Material | Question |
|---|---|---|
| B1 single character | Each Character 02 pose and expression, alone | Does every pose stay Character 02? |
| B2 composited scenes | Approved single poses of both characters composited by the engine (Track A scenes with real artwork) | Do both identities survive side by side across shots? |
| B3 joint generation (optional) | Both characters generated together in one image | Does the generator keep them apart? Highest risk; only if the owner wants it |

### 6.2 Test matrix

- **Expressions per character:** at least five (neutral, worried, happy or laughing, annoyed, surprised), matching Character 01's existing pose set where possible.
- **Shots:** the six shot types of scene A4, in each of three dialogue scenes, with positions swapped in one scene and an overlap in another.
- **Coverage:** every expression of each character appears in at least two different shots and at least one shot next to the other character.

### 6.3 Measurable checks

Each figure is measured from its cut-out. "Own reference" means the character's approved master and poses; "other reference" means the other character's.

| # | Check | Proposed pass threshold (M6) |
|---|---|---|
| B-1 | Own palette coverage | At least the existing validator's `palette-consistency` pass level against the own reference |
| B-2 | Cross-character separation | Own-reference palette coverage exceeds other-reference coverage by at least 0.20 |
| B-3 | Signature-colour exclusivity (blending) | At most 2% of figure pixels within ΔE 10 of the OTHER character's signature clothing colour |
| B-4 | Proportions | Head-to-figure height ratio within ±10% of the own reference (existing `pose-proportions` check) |
| B-5 | Per-shot assignment (swapping) | In every shot, each cast member is assigned to its expected character by B-1 and B-2; zero swaps across the whole matrix |
| B-6 | Cross-shot stability | For each character, the spread of B-1 coverage across all shots is at most 0.10 |
| B-7 | Silhouette, greyscale and small-size tests | Still told apart in the §3 tests, on the generated poses as well as the master |
| B-8 | Technical | The existing validator reports no `fail` (canvas, transparency, edges, feet anchor) |

**What the measurements cannot settle.** Faces (eye, brow and mouth construction), hairstyle detail, clothing detail and the overall reading of a character cannot be measured reliably here. They are owner review items. Passing B-1 to B-8 is necessary, not sufficient.

### 6.4 Owner visual approval gate

1. For each character: a same-scale sheet of the approved master beside every candidate pose, with labels and hashes.
2. For each test scene: a contact sheet of every shot, each cast member labelled by character.
3. The owner reviews against a written checklist: the same-universe check (§3), face, hair or head, clothing and colour, proportions, expression, and whether either character has changed or borrowed from the other.
4. The owner records approve or reject per pose and per scene, with a note. Rejections name the failing item.
5. Approval of Character 02 poses follows the existing quarantine, review and promotion gates. Nothing becomes a production asset automatically.

**Track B acceptance:** B-1 to B-8 pass on the whole matrix, AND the owner approves every pose and every scene in §6.4.

## 7. Modularity requirements

- **One registry per character**, in the same shape as `character-01.json`. No code names a specific character; the cast refers to characters by ID.
- **Cast member versus character.** A scene's cast member (for example `left-speaker`) points at a character ID, so the same character can appear in many roles and formats.
- **Speakers belong to cast members.** Dialogue lines name a cast member; styling (bubble colour, caption, voice) comes from that member's speaker configuration, never from left/right or gender defaults (F3).
- **Formats stay strategies** behind the existing format interface. `face-to-face` is implemented as one more strategy; phone-call and split-screen stay planned and can follow without changing the cast model.
- **Facing as data.** A pose's facing is declared in the registry; a scene asks for a facing and gets the matching artwork, or an error. Nothing is mirrored silently (F4, M7).
- **Validation per character, plus cross-character.** Per-character checks stay; cross-character checks (B-2, B-3, B-5) compare against every other character in the scene.

## 8. Phases

| Phase | Content | Cost | Needs |
|---|---|---|---|
| P0 | This plan | $0 | Approval of the plan (M1) |
| P1 | Track A: `face-to-face` format; speaker styling from cast configuration (F3); errors instead of silent defaults (F5); facing as data (F4, without new artwork); placeholder fixtures; tests A-1 to A-10 | $0, local | M2 |
| P2 | Character 02 design brief: role, name, feminine cues, colour identity, hairstyle; production route | $0 | M3, M4, M5 |
| P3 | Character 02 master and pose set, by the route chosen in M5; owner approval of the master | Depends on M5; any AI route is a separate experiment with its own budget | Its own approvals |
| P4 | Track B: B1 and B2 on the approved artwork; optional B3; owner visual gate | $0 for B1 and B2 (local measurement and compositing); B3 only within an approved experiment | M6, M8 |

## 9. Decisions requiring the owner

| # | Decision |
|---|---|
| M1 | Approve this plan and the milestone ID AP-85. **APPROVED 2026-11-15** |
| M2 | Approve the Phase 1 implementation scope (§8, P1): local, $0, no artwork. **APPROVED 2026-11-15; implemented (§5.3)** |
| M3 | Character 02's role and relationship to Character 01, including how it relates to the open cast decisions D4 and D5 |
| M4 | The design brief choices in §3: which cues make her clearly feminine, her signature colour, hairstyle and name |
| M5 | How Character 02's artwork is produced (for example hand-drawn, commissioned, or an AI experiment with its own lock and budget) |
| M6 | The Track B thresholds in §6.3 (all proposed, none validated on real artwork) |
| M7 | How characters face each other: artwork drawn for each facing, or a single facing with staging that avoids it. Mirroring is not proposed |
| M8 | The owner visual review protocol in §6.4 |

## 10. Risks

| Risk | Mitigation |
|---|---|
| Track A passes are read as identity evidence | Every report names its track; §1 states the rule; the decision record repeats it |
| The placeholder is mistaken for a design | Synthetic colours, an on-figure label, test fixtures only, never promotable |
| Palette metrics pass on images that a person sees as wrong | Owner review is required for acceptance; metrics are necessary, not sufficient |
| Character 02 drifts towards Character 01 (or the reverse) in generated poses | Cross-character checks B-2, B-3 and B-5; silhouette and greyscale tests |
| Facing each other needs artwork that does not exist | M7 decided before P3; F4 kept as an error, not a silent mirror |
| Scope creep into AP-84B3 | AP-84B3 files, locks and gates are out of scope for every phase here |

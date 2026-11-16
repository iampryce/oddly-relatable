# AP-86 S4: framing and camera — approval request

**Status (2026-11-16): REQUEST PREPARED; S4 IS NOT AUTHORISED.** Nothing in this request is implemented. S4 starts only after the owner approves it. S5 to S7 stay unauthorised, and O5 to O13 stay open unless the owner decides them separately.

**Context:** AP-86 proposal §8 (camera workflow, items 1 to 5) and §11 (roadmap row S4). S1, S2 and S3 are implemented; S4 depends on S2 (sets, plates, parallax), which is done. The AP-85 shadow correction (`59e6f3e`) was accepted by the owner on 2026-11-16, so S4 starts from a clean Track A baseline.

## 1. Scope

| # | Capability | Expected implementation |
|---|---|---|
| 1 | **Superframe composition** | When a set's plate is larger than the frame, the existing composer (`composeShot`) pans within the whole plate instead of a just-fitting background, so true singles and reverse shots no longer need the `single` cheat. The Track A rules are unchanged: focus centred as far as the plate allows, nobody cut by a frame edge, focus clearly the most central figure, build fails otherwise. Just-fitting plates and story@1 scenes behave exactly as now. |
| 2 | **Framing profiles from one staged scene** | Two profiles, **P-916** and **P-169**, each a frame window on the same staged scene with its own action-safe area, UI-safe margins and a reserved caption zone (`bible/MULTI_PLATFORM_ARCHITECTURE.md` §4 and §5; provisional values, see §4 below). One story compiles to one project per requested profile. Per-shot overrides are allowed only when a staging cannot satisfy both profiles, and are reported. Bubbles are laid out per profile with the existing speaker-side rule. |
| 3 | **Face-to-face camera moves** | Push-in, pull-back and pan between two composed framings, written as per-frame keys (eased, monotonic, no stutter). Every frame of a move must satisfy the framing rules, or the build fails and names the frame. Today these are refused; they become allowed for story@2 only. Parallax (S2) applies through moves, about the moving camera. |
| 4 | **Continuity checks across cuts** | Shot/reverse-shot keeps screen sides: the build reports (and, where the owner chooses, fails on) a member who changes screen side or relative scale between consecutive shots without blocking that explains it. Eyelines are not checked: they need facing art (M7 / O10). |

**Not in S4:** caption burn-in (S7; S4 only keeps the caption zone clear), movement of characters (S5), any artwork (S6), audio (S7), shake and drift in face-to-face, text-chat changes.

## 2. Files and modules likely to change

| File | Change |
|---|---|
| `production/lib/framing.mjs` (new) | Profile definitions (window, safe areas, caption zone), the per-frame framing-rule evaluator shared by cuts and moves, and the continuity checks |
| `production/lib/formats/face-to-face.mjs` | `composeShot` takes a profile and a superframe window; camera keys for moves; one composition per profile; continuity report |
| `production/lib/camera.mjs` | Move tracks for face-to-face (eased keys between two composed windows). The text-chat camera path stays byte-identical |
| `production/lib/depth.mjs` | `parallaxCamera` reused under moving cameras (no behaviour change for static shots) |
| `production/lib/sets.mjs` | Use the plate `superframe` for the camera's reachable area (the schema already accepts it; no new set fields expected) |
| `production/lib/story-v2.mjs`, `production/lib/scene.mjs` | Lift the move refusal for story@2; a `profiles` option on the scene/story; compile per profile |
| `production/lib/layout.mjs` | Profile-specific safe area and caption zone for bubble placement checks |
| `production/lib/produce.mjs` | One output folder per profile, listed in the manifest |
| `production/tests/ap86-s4-framing-camera.test.mjs` (new), `production/tests/fixtures/ap86-synthetic.mjs` | Tests and a labelled synthetic superframe set (temporary folders only) |
| Docs | AP-86 proposal §11.4, `DECISIONS.md`, `HANDOFF.md`, `NEXT_STEPS.md`, `PROGRESS_LOG.md` |

**Not changed:** the renderer (`skills/directing-stickman-videos`), text-chat, character artwork and registries, AP-84B3, S1 to S3 behaviour for scenes that do not use S4 features.

## 3. Exit criteria (regression gate)
- The same staged synthetic scene compiles to P-916 and P-169, and every frame of both passes all framing rules (checked per frame in the render plan and by rendered-pixel tests through the unmodified renderer).
- A superframe single shows only its focus member without `single`; a just-fitting plate gives the same result as today.
- A push-in, a pull-back and a pan each pass the framing rules at every frame, with smooth keys; a move that would cut a member is refused, naming the frame.
- Continuity checks catch a deliberately flipped side and an unexplained scale jump.
- Deliberate rule breaks are each caught (mutation checks, as in S1 to S3).
- **Unchanged:** Short 001 byte and pixel baselines; AP-85 Track A A1 to A6 byte-identical, including the accepted corrected A4; the S1, S2 and S3 tests; studio 64/64; renderer 134/135 (only the pre-existing Jensen baseline failure).

## 4. Decisions the owner is asked to make
1. **Approve S4** with the scope above: local engineering, $0, synthetic fixtures only, no artwork, no GPU, image generation, external or paid services, no renderer changes.
2. **Profile sizes for engineering only:** use 1080×1920 (P-916) and 1920×1080 (P-169) as test profiles. This does **not** decide O11 (framing formats) or D18 (master format); AP-20 (9:16 primary, 16:9 secondary) is the only format direction assumed.
3. **Safe areas and caption zone:** use the bible's action-safe square (0.5625 S × 0.5625 S, centred; `MULTI_PLATFORM_ARCHITECTURE.md` §4) as the default. The bible records platform UI-safe margins and the caption zone as **unverified** (§5), so S4 uses conservative, configurable placeholder margins, labelled provisional; locking real platform values stays with O11.
4. **Continuity strictness:** report only (recommended for S4), or fail the build on an unexplained side change.

## 5. Risks
| Risk | Mitigation |
|---|---|
| A 16:9 window shows more of the stage, so a staging that is clean in 9:16 can expose plate edges or extra members | Superframe coverage check per profile; per-shot override, reported; build fails rather than cutting a member |
| Bubble layout was tuned for 9:16 | Per-profile layout checks; existing 9:16 behaviour unchanged |
| Moves plus parallax can make floor-carrying layers slide against feet | S2 rule kept (floor layers use factor 1); pixel test on a move |
| Render time grows with per-frame keys | Camera cache per frame (exists); measured and reported |
| Regressions in accepted work | Byte and pixel gates above, run before commit |

## 6. Cost
$0: local Node, canvas and FFmpeg only. No services, GPU, downloads or spending.

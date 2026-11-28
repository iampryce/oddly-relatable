# CLAUDE.md: current direction (read first)

Updated 2026-11-28. Longer detail lives in the docs linked in section 5; this file only holds what a new session must know.

## 1. Workflow
- Work on `main` only. Small commits with clear messages ("docs: studios", "kit: add walk cycle"). Push straight to main.
  No feature branches, no PRs.
- Before each push: `git pull --rebase`, run the local tests, and check Actions. Do not push app code while a Deploy run
  is in progress (docs-only commits may skip that check). Never force-push. Never rewrite history.
- Commit messages carry no AI author or co-author lines.
- No paid API call without the owner's explicit go. Show the expected cost first, even for tiny calls.
- Nothing is deleted without the owner's explicit approval. Move to `_to_delete/` first and show its contents.
- Never mark an approval (script, storyboard, pose, publish) unless the owner says so.

## 2. Direction
- One dashboard with a studio switcher and a shared core. Three studios:
  1. **Stick Man Studio** (active), 2. **Cinematic Studio** (locked), 3. **Kids Stories Studio** (locked).
- The other two stay locked until Stick Man Studio passes these gates:
  (1) one finished 30 s Explainer Short approved; (2) one finished Remake Audio short approved;
  (3) animation engine chosen with real costs known; (4) licences checked and a variety guard in place.
- Stick Man Studio has two paths: **Explainer Shorts** (narrated, with action acting) and **Remake Audio** (talking,
  lip-sync). Both use the code-drawn sets and locked character masters.
- Goal: solve acting, lip-sync and character drift. Do not start the next studio before that is achieved.

## 3. Style
- Current stickman style (WaveSpeed-generated): large white head with soft grey shading, big eyes, pink blush,
  expressive face, thin black limbs, rounded black mitten hands and shoes, white blob torso, soft grey ground shadow,
  identity carried by hat and hair.
- The Episode 15 style, its nine masters and the storyboard frames are **legacy** (see the `_archive` plan in
  `docs/studios.md`). Do not use them for new work.
- AI draws still images only; code does the motion, unless the engine shootout shows otherwise.
- `docs/RIVET-STYLE-GUIDE.md` and `studio-app/api/oddstudio/house_style.py` still describe the old look; update
  them to this style (not done yet).

## 4. Current status (updated 2026-11-28 evening)
**Done and live:** `studio-work` restructure (log: `studio-work/MOVES.md`); `docs/studios.md`; server cleaned (disk 53%,
46 GB free; maintenance keeps the live release plus 2 previous); 3D camera (#109) reverted as 42d31b0; studio switcher
(dbd9e1c, Stick Man active, other two locked) pushed, CI green, Deploy succeeded, live release tree f93fce9c.
`categories.py` (#108) is in main: dead code, no test, docstring names providers (`code-kit`, `gemini-tts`,
`omni-flash`) missing from `capabilities.py`.

**Backups on the remote (never merge `backup/*`):** `backup/asset-import-pr1` (Import screen, provenance; migration 0016
collides, renumber to 0018+, drop the pose part, land when the cast import needs it), `backup/cinematic-mode` (locked),
`backup/3d-camera`, `backup/clean-dashboard`. Already in main, branches can be archived: episode-sets, edit-seats,
clean-dashboard, plan-unconfirmed-persons. The Mac has no Python deps; API tests run only in CI.

**Blocked on the owner:** the new stickman reference images (`studio-work/refs/` does not exist yet); then copy to
`_shared/cast/` with a README (WaveSpeed, owner-supplied, 2026-11-28, not approved as masters). Engine shootout needs
the owner's go and shown costs (~$10 ceiling).

**Open decisions:** kit painted sets vs flat outlined sets for the new style; cut-out vs whole-frame generation; rebuild
or replace kit characters; parent brand name; where kit rendering runs (server has no node/Chromium, none wanted).

**Next, in order:** (1) first test frame: a flat outlined code-drawn set plus the new stickman as a cut-out (free);
(2) engine shootout after the owner's go (Path A builders action; Path B a 5 s spoken line); (3) YouTube research feeds
1-2 (leads: Wan 2.2 Animate, SCAIL-2; treat as leads only); (4) later: land asset-import, variety guard, fix
`categories.py`, update `docs/RIVET-STYLE-GUIDE.md` and `house_style.py`, Codex/OpenAI image-terms check.

**Known risks:** main deploys to production on any `studio-app` change; Mac cannot run API tests locally.

## 5. Pointers
- `docs/studios.md`: studios, gates, target folder tree, migration list, open decisions.
- `DECISIONS.md` (repo root, the decisions register; there is no `docs/DECISIONS.md`): decisions, including 2026-11-28.
- `docs/character-and-set-kit.md`: identity layers, house-style rules, asset kit recipe.
- `studio-app/docs/`: deployment, maintenance, sets, voice, audio-first, GPU.
- Cast references: `studio-work/_shared/cast/` (empty; the new reference goes here). Legacy masters: `studio-work/_archive/legacy-ep15-style/masters/`.
- Kit code: `studio-work/_shared/kits/{kit-proof,cartoon-short-kit}/`; scenes in `studio-work/stick-man/explainer-shorts/`.
  Render: `WEB=<scene dir> node render-gpu.mjs <outdir> "0-719"` from `kits/kit-proof`. Not wired into the app or Docker.
- Style guide: `docs/RIVET-STYLE-GUIDE.md` (still the old style).

## 6. Handoff rule
At the end of each session, update section 4 (Current status) and commit it, so the next session starts correctly.

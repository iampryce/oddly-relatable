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

## 4. Current status
**Merged:** New short wizard (#107, migration 0017), Rivet name (#106), `docs/studios.md` plan and this direction.
CI and Deploy on main were green before the docs commits.

**In progress:**
- Cleanup listing (worktrees, duplicate kit copies, bulk renders, `~/Documents` duplicates). Step 1 is list-only and
  waits for the owner's approval before anything is removed.
- Hash scan of `~/Documents` for duplicates is done (`dups.json` in the session scratchpad); the report is not sent yet.

**Blocked / waiting on the owner:**
- The new stickman reference image (flat cap, grey hair) is not on disk. Save it (for example `studio-work/refs/`);
  then it goes to `_shared/cast/` with its source noted (WaveSpeed).
- Approval of the cleanup list.

**Unsaved work found (do NOT delete these worktrees):** `.claude/worktrees/agent-a30969db7472ca6b1` holds the
uncommitted asset provenance / Import screen / pose dimension work (migration `0016_asset_dimension_provenance`);
`agent-a86ba0e5d041e5c90` holds the uncommitted cinematic mode (`0017_episode_mode`); `agent-a75e7540a9cbf6959` holds
3D camera edits. Both migrations collide with main's `0016_episode_style` and `0017_episode_kind` and must be renumbered
(0018 and up) before landing. `feat/spec-characters-prototype` also has staged, unpushed work.

**Open decisions:** (a) do the kit's painted sets suit the new style; (b) cut-out route (clean masks for the white body
and shadow) vs whole-frame generation; (c) rebuild or replace the kit characters to match; (d) parent brand name
(Oddly Relatable vs Rivet AI Studio); also the engine shootout and the sensitive lines in Episode 15.

**Next three tasks, in order:**
1. Owner approves or edits the cleanup list; first save the unsaved work in the three worktrees above.
2. Save the new stickman reference to `_shared/cast/`; update `docs/RIVET-STYLE-GUIDE.md` and `house_style.py` to it.
3. Decide sets vs the new style and cut-out vs whole-frame, then build the 30 s Explainer Short as gate 1.

**Known risks:** server disk at 95% (cleanup pending); main deploys to production on every push; Codex image terms not
yet verified; the Mac has no ffmpeg or numpy, so some local API tests fail (same on clean main).

## 5. Pointers
- `docs/studios.md`: studios, gates, target folder tree, migration list, open decisions.
- `DECISIONS.md` (repo root, the decisions register; there is no `docs/DECISIONS.md`): decisions, including 2026-11-28.
- `docs/character-and-set-kit.md`: identity layers, house-style rules, asset kit recipe.
- `studio-app/docs/`: deployment, maintenance, sets, voice, audio-first, GPU.
- Cast references: `_shared/cast/` (planned; the new reference goes here) and `studio-work/refs/` (to be created).
- Kit code: `studio-work/kit-proof/` and `cartoon-short-kit/` (both untracked).

## 6. Handoff rule
At the end of each session, update section 4 (Current status) and commit it, so the next session starts correctly.

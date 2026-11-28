# Studios

Status: proposal for the owner's review, written 2026-11-28. Nothing here is approved, built or moved. It records the
target structure so the next sessions stop guessing. Where this file and `DECISIONS.md` disagree, `DECISIONS.md` wins
until the owner records a new decision there.

## 1. Target style (what every studio draws)

Decided by the owner on 2026-11-28 (recorded here; add it to `DECISIONS.md` when approved). This replaces the Episode 15
style, which is now legacy (section 5).

The new stickman:

- **Head:** large, white, with soft grey shading.
- **Face:** big eyes, pink blush, an expressive face.
- **Limbs:** thin black limbs.
- **Hands and shoes:** rounded black mitten hands and rounded black shoes.
- **Torso:** a white blob torso.
- **Ground:** a soft grey shadow on the ground under the character.
- **Identity:** carried by hat and hair, not by outfit or face shape.
- **Reference:** the owner's new stickman, a figure in a flat cap with grey hair, generated with WaveSpeed. The image
  file is not in the repo yet; once supplied it is saved under `_shared/cast/` with its source noted (WaveSpeed,
  owner-supplied, 2026-11-28, not yet approved as a locked master).

Motion rule, unchanged: AI draws stills only; code does the motion.

Environment style is not settled: the old rule was richly painted warm 2D rooms built as painted textures by the code
kit. Whether those suit the new character is an open decision (section 6).

## 2. Three studios in one dashboard

A studio switcher at the top of the dashboard picks the studio. Each studio has its own projects, cast and defaults;
cast and sets in `_shared/` can be used by any of them.

| # | Studio | State |
|---|---|---|
| 1 | **Stick Man Studio** | Active. The only one being built now. |
| 2 | **Cinematic Studio** | Locked. Bible stories first, then power-struggle sagas. Realistic invented actors. |
| 3 | **Kids Stories Studio** | Locked. |

### 2.1 Stick Man Studio: two paths

| Path | What it is | Both paths use |
|---|---|---|
| **Explainer Shorts** | Narrated, scene per sentence, characters act the sentence out (hammering, measuring, stacking). The "New short" wizard. | Code-drawn sets plus locked new-style character masters |
| **Remake Audio** | Take an existing audio track, characters talk to it, lip-sync. Episode 15 is this type. | Code-drawn sets plus locked new-style character masters |

### 2.2 Locked studios

Cinematic Studio and Kids Stories Studio stay locked, visible in the switcher but not usable, until all four unlock gates
below are met for Stick Man Studio.

## 3. Unlock gates

1. One finished 30 s Explainer Short, approved by the owner.
2. One finished Remake Audio short, approved by the owner.
3. Animation engine chosen, with real costs known (see the engine shootout in section 6).
4. Licences checked for every tool in use, and a variety guard in place (YouTube penalises repetitive mass-produced
   content, so stories and scenes must differ).

Nothing is self-approved: each gate is the owner's call.

## 4. Proposed folder tree (not applied)

```
studio-work/
  stick-man/
    explainer-shorts/<project>/
    remake-audio/<project>/
  cinematic/
    bible-stories/<project>/
    power-sagas/<project>/
  kids-stories/<project>/
  _shared/
    cast/      new-style masters and character specs (the new stickman reference goes here)
    sets/      set plates and set definitions
    kits/      cartoon-short-kit, kit-proof engine
  _archive/    superseded work, kept until the owner deletes it
    legacy-ep15-style/   Episode 15 masters, storyboard frames, stills, clips and cuts
```

### Migration list (do NOT run; the owner decides each line)

| Now | Proposed | Note |
|---|---|---|
| `studio-work/stick-cast/approved/` (Episode 15 masters, 9 files, 3.7 MB) | `_archive/legacy-ep15-style/masters/` | LEGACY style. Keep intact for reference; they are no longer the identity source |
| `studio-work/stick-cast/sets/` | `_shared/sets/` | 12 MB |
| `studio-work/stick-cast/ep15-*` (stills, clips, cuts) | `_archive/legacy-ep15-style/` | LEGACY style; about 200 MB; two cuts are 23 and 26 MB. The audio (`ep15-audio`) stays available for a Remake Audio test in the new style |
| `studio-work/stick-cast/react`, `acting-test` | `_archive/` | 2.8 GB and 0.8 GB, the bulk of the 3.9 GB folder; review before deleting |
| `studio-work/stick-cast/` rest (`build`, `talk-run`, `pose-test`, `s2v-test`, `gpu-qwen-test`) | `_archive/` | experiments |
| `studio-work/episode-15/` (storyboard frames-v1 and character stage-c1) | `_archive/legacy-ep15-style/` | LEGACY style; Codex-drawn, drifts from the masters (section 5) |
| `studio-work/episode-14/` | `_archive/` | 121 MB; the owner decides if it is legacy |
| `studio-work/kit-proof/` | engine code to `_shared/kits/kit-proof/`; frames and out to `_archive/` | frame folders are about 1 GB and reproducible |
| `cartoon-short-kit/` (repo root, untracked) | `_shared/kits/cartoon-short-kit/` | decide whether it is tracked in git |
| `studio-work/poc-*`, `spike-*`, `phase0-*` | `_archive/` | early proofs, 2 to 9 MB each |
| `studio-work/RIVET-STYLE-GUIDE.md` | `docs/` | after it is updated to the new style (section 7) |
| `~/Documents/oddly-relatable-{categories,ep5-banner,ep5-stills,moodboard,style-v2-test,spec-prototype}` | `_archive/` or delete | outside the repo; `-categories` is 566 MB; `-spec-prototype` is empty |

The server holds `/srv/stickman/{releases 14 GB, backups 11 GB, repo 1.1 GB}` on a disk that is 95 percent full; that is
deployment housekeeping (`studio-app/docs/MAINTENANCE.md`), separate from this migration.

## 5. Findings that shape the plan

**Legacy:** the Episode 15 style, its nine approved masters (`studio-work/stick-cast/approved/`) and the 20 storyboard
frames below are legacy as of 2026-11-28. They stay on disk until the owner deletes them; nothing has been moved.

- The Episode 15 storyboard (`studio-work/episode-15/storyboard/frames-v1`) has all 20 frames, plus v2 or alt variants
  for F05, F14, F17 and F19. Only F01 came from the paid API (`gpt-image-2`, $0.256); the API then refused F02 for
  lack of credits, and F02 to F20 were drawn through Codex with a ChatGPT sign-in. They are marked "Draft: not for
  publishing; not approved". Codex-drawn art is superseded as a source of art, so treat this set as reference.
- Checked against the masters, the frames keep the heads and colours but drift on bodies: legs and sleeves change
  (F06, F20 show trousers and legged bodies the masters do not have), faces gain details (Ralph's glasses and bruised
  eyes in F06, extra expression lines), and the cast layout changes between frames. That is why art supplies stills only
  and code does the motion.
- The code kit can paint sets, cut a head from a master, draw limbs, hands, props (hammer, tape, plank, pencil, block),
  mouth shapes and expressions, and do camera moves. It cannot yet do side or walking views, true lip-sync from audio
  inside the dashboard, music and SFX on the Mac, or live in the dashboard at all (it runs from scripts).

## 6. Open decisions for the owner

1. **Parent name:** Oddly Relatable (repo, docs) or Rivet AI Studio (the brand rename, PR 106). Both appear today.
2. **Engine shootout:** code kit (free, exact timing, scene code per video) vs Wan 2.2 on rented GPU (about $0.05 per
   clip plus session start) vs Omni Flash (needs Google billing). Run the same 30 s script through each and compare
   quality, drift and real cost. No paid run without the cost shown first.
3. **Sensitive lines in Episode 15:** you flagged sensitive lines in the Episode 15 audio. I have not transcribed or reviewed the audio, so they are not
   listed here; they need a review before any publishing.
4. **Whether to keep the legacy Episode 15 art** (masters, Codex-drawn frames) or delete it.
5. **Do the kit's painted sets suit the new style?** The white head, grey shading and soft ground shadow may clash with
   the dark, richly painted rooms, or may need lighter or flatter sets.
6. **Cut-out route vs whole-frame generation.** Cut-out (cut head, body and shadow from a still, then code animates
   them) needs clean masks for the white body and the grey shadow, which are hard to separate from a light background.
   Whole-frame generation avoids masks but drifts, as the Episode 15 frames did.
7. **Kit characters need rebuilding or replacing.** `stick.js` draws the old look (tapered limbs, code torsos, hands
   from the old masters), so it must be rebuilt for the new style or swapped for art-based layers.

## 7. Files that must follow the new style (not edited yet)

- `studio-work/RIVET-STYLE-GUIDE.md` (section 3 "Look": house characters from the old masters, "clean 3D-style worlds").
- `studio-app/api/oddstudio/house_style.py` (the style text sent to image generation, including "NOT a 3D render").

Both still describe the old look. They need updating to the style in section 1 once the owner approves it; they were
deliberately left untouched in this change.

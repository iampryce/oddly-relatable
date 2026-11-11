# Multi-Platform Architecture

**Status:** the **platforms and formats are APPROVED** (owner, 2026-11-11). The architecture below is a **PROPOSAL** for approval. **Nothing in it is built.** No publishing automation exists and no platform API is connected, by instruction.
**Independence:** this project is independent of Kids Animation Studio.

**Evidence labels:** **[OFFICIAL]** read on the platform's own help page today · **[SECONDARY]** reported by third-party blogs or news, not confirmed on an official page · **[VERIFIED]** checked in this repository's code · **[REASONED]** inferred, not tested · **[ASSUMED]** my estimate or recommendation.

---

## 1. Approved direction

| # | Decision (owner, 2026-11-11) |
|---|---|
| M1 | Stickman Comedy Studio is a **multi-platform brand** for **YouTube, TikTok and Facebook**, not YouTube-only. |
| M2 | **Primary format: 9:16 vertical** for YouTube Shorts, TikTok and Facebook Reels. |
| M3 | **Secondary format: 16:9 landscape** for longer YouTube episodes and suitable Facebook distribution. |
| M4 | **Do not double production work unnecessarily.** Reusable scenes and character assets must adapt to different aspect ratios. |
| M5 | Content: original animated stories for an **international** audience (human behaviour and psychology, relationships and dating, workplace, money and adult life, friendship, everyday frustrations, funny hypotheticals). **African or Nigerian storytelling must not define the identity.** |
| M6 | For each episode plan: a complete original episode; short-form edits; platform-appropriate captions and hooks; titles, descriptions and thumbnails; **safe framing** that survives cropping. |
| M7 | **Do not assume identical uploads, durations or captions are optimal on every platform.** Research current specs and policies before finalising publishing automation. |
| M8 | The pipeline must support reusable characters, reusable backgrounds, portrait and landscape compositions, platform-specific render/export presets and **separate publishing metadata per platform**. |
| M9 | **No publishing automation and no platform API connections yet.** |

## 2. Design principle: author once, render many

```
        ┌──────────────── platform-neutral (authored once) ────────────────┐
        │  Characters (vector puppets)   Environments (superframe plates)  │
        │  Scene graph: shots, poses, camera moves, timing, SFX, captions  │
        └──────────────┬───────────────────────────────┬───────────────────┘
                       │ framing profile 9:16          │ framing profile 16:9
                       ▼                               ▼
              renderer project (portrait)     renderer project (landscape)
                       │                               │
              export presets per platform     export presets per platform
                       │                               │
        Shorts · TikTok · Reels          YouTube long-form · Facebook video
                       │                               │
              publish metadata per platform (separate files, manual upload for now)
```

Everything left of the framing profiles is shared. Only the *framing*, *captions layout*, *export preset* and *publishing metadata* differ by platform. That is where the work is saved.

## 3. Content tiers and which format is the master [PROPOSED]

| Tier | What | Master format | Derived formats |
|---|---|---|---|
| **T1 · Native short** | A complete 30–90 s story | **9:16** | Optional 16:9 reframe for Facebook or a compilation |
| **T2 · Episode** | A complete 2–8 min original story | **16:9** (long-form YouTube, suitable Facebook video) | **Vertical cut-downs** (2–3 per episode, each a recomposed 30–90 s edit) |

Rule: *story length and primary platform choose the master.* Vertical is the **primary** format overall (most uploads are T1 plus T2 cut-downs). The other ratio is **derived by reframing**, not re-authored, wherever the staging allows (§4).

**Platform limits that matter for the master choice:**
- **YouTube Shorts:** up to **3 minutes**, vertical uploads, max 1080p, title ≤ 100 characters, "made for kids" must be answered **[OFFICIAL]**. Third-party guides add that square is also accepted and that a wider video is treated as a normal video **[SECONDARY]**.
- So a vertical T1 of up to 3 minutes can serve Shorts. A longer story belongs in 16:9.

## 4. How assets are reused across aspect ratios [PROPOSED]

### 4.1 Characters
Vector puppets (poses, expressions, flipped copies, shadows) are **ratio-independent**. They are exported once and used in both formats.

### 4.2 Environments: "superframe" plates
Draw each plate as a **square 1:1 master** (about 3840×3840 for zoom headroom; 1920×1920 is the minimum for native-resolution 1080×1920). Both frames are windows on it:

| Window | Size relative to a square plate of side S |
|---|---|
| 9:16 portrait | 0.5625 S wide × S tall |
| 16:9 landscape | S wide × 0.5625 S tall |
| **Overlap = the action-safe square** | **0.5625 S × 0.5625 S, centred** |

**Staging rule:** all essential action (faces, hands, key props, the joke) stays inside the **action-safe square**. Portrait then shows extra floor and ceiling; landscape shows extra wall to the sides. Both still contain the full joke.

### 4.3 The scene graph (platform-neutral)
Each shot is described once, in plate coordinates (0–1): who is where, pose and expression, props, **camera centre and zoom over time**, timing, SFX cues, caption text. A **framing profile** turns it into a renderer `project.json` for one ratio. A shot may carry a **per-ratio override** (a different camera window, or a changed placement) when the safe-square rule cannot work, for example two characters side by side in landscape but stacked in portrait. Overrides reuse the same assets.

### 4.4 Honest limits
- **Many shots will not reframe cleanly** (wide two-shots, close-ups of two faces, text-heavy inserts). Those need an override or a different camera move, which costs review time.
- The depth layers (back, mid, front) must also work in both windows; a foreground prop at the left edge of landscape may fall outside the portrait window.
- **Estimated extra effort for the second ratio: about 10–25% per episode, not 100% [ASSUMED]**, provided staging follows the safe-square rule from the start. This is an estimate, not a measurement.

## 5. Framing profiles [PROPOSED]

| Profile | Output | Use | Notes |
|---|---|---|---|
| **P-916** | 1080×1920, 30 fps | Shorts, TikTok, Reels | Primary |
| **P-169** | 1920×1080, 30 fps | YouTube long-form, Facebook video | Secondary |
| P-11 (optional) | 1080×1080 | Feed placements, if ever wanted | Not planned; decide later |

Each profile defines: the **camera window** on the plate; the **action-safe area**; the **UI-safe margins** (where platform buttons and captions overlay); the **caption zone**; minimum text size; and the **export preset**.

**UI-safe margins:** each platform overlays buttons, titles and captions on vertical video, and the exact safe zones differ. **I have not verified the numbers** and will not invent them. They must be taken from each platform's own safe-zone guidance before the profile is locked; until then use conservative margins (keep essential content away from the top, bottom and right edges) and test with overlay guides.

### What the renderer does with these (verified from its code)
- **Native portrait is supported:** the design plane is 1280 wide and `1280 × height / width` tall, so a 1080×1920 project is 1280×2275.56 design units **[VERIFIED]**. Portrait scenes must be composed explicitly; changing the output size alone does not recompose anything.
- **Captions are a problem for portrait:** the renderer draws its captions at a **fixed position near the bottom** (60 design units from the bottom) and reserves the bottom 110 units **[VERIFIED]**. On Shorts, TikTok and Reels that area is typically covered by platform interface, so portrait captions would be partly hidden. The caption position cannot be changed, and the project file requires non-empty captions.
- **Options, to decide later:** (a) burn captions in **after** rendering with FFmpeg or a subtitle renderer, placed per platform; (b) use the renderer's captions only for landscape; (c) accept the fixed position and move key content upward. I recommend **(a)**. It is outside the renderer, so no renderer change is needed.
- **Other limits that affect all ratios [VERIFIED]:** one audio file per film (mix externally), no mirroring, no desaturation, rotation about the top-left only, images only.

## 6. Platform matrix: what is known and how well

| | **YouTube Shorts** | **YouTube long-form** | **TikTok** | **Facebook Reels / video** |
|---|---|---|---|---|
| Role | Primary short-form | Secondary long-form | Primary short-form | Reels primary; video secondary |
| Aspect | Vertical **[OFFICIAL]**; square also accepted **[SECONDARY]** | 16:9 | 9:16, 1080×1920 standard **[SECONDARY]**; other ratios supported **[SECONDARY]** | Reels 9:16, 1080×1920 recommended **[SECONDARY]** |
| Max length | **Up to 3 min [OFFICIAL]** | Not researched | **Conflicting reports** (about 10 min for many uploads; some say up to 60) **[SECONDARY]** | **Unclear / conflicting** (one report: Facebook folded video into Reels with no length limit, June 2025) **[SECONDARY]** |
| Resolution | Max 1080p **[OFFICIAL, for Shorts]** | Not researched | 1080×1920 **[SECONDARY]** | 1080×1920 (min figures vary) **[SECONDARY]** |
| Title / text limits | Title ≤ 100 chars **[OFFICIAL]** | Not researched | Not researched | Not researched |
| Audience setting | "Made for kids" must be answered **[OFFICIAL]** | Same | Not researched | Not researched |
| Synthetic / AI disclosure | Required for **realistic** AI-generated or altered content; **not** required for non-realistic content such as fully animated video; minor edits (captions, colour, upscaling, audio repair, **cloning your own voice for voiceovers**) exempt **[OFFICIAL]** | Same | Label for realistic AI content, set via a toggle or on-screen text; TikTok can auto-label (C2PA); **scope conflicts between sources** **[SECONDARY]** | "AI Info" label on photorealistic AI content, largely via C2PA metadata **[SECONDARY]** |
| Originality / monetization | "Inauthentic content" (formerly "repetitious", renamed July 2025) targets templated, mass-produced, low-effort uploads; AI use alone is not a violation **[SECONDARY]** | Same | Not researched | March 2026 guidance: reposts and lightly altered content demoted; accounts posting mainly unoriginal content risk reach and monetization loss **[SECONDARY: TechCrunch, Tubefilter, MediaPost]**; sources conflict on some cases |
| Confidence | **High for the starred items; the rest is not yet verified** | Low | **Low** (official page did not render) | **Low** (official URL returned 404) |

### What this means for us [REASONED]
- Our content is **fully animated and non-realistic**, so YouTube's disclosure requirement should not apply to the characters or scenes. **Caution:** a **realistic synthetic voice** is a grey area on every platform and needs a check before we choose voices (decision D8). We will not clone real people's voices.
- All three platforms are tightening against **templated, repetitive, low-effort, unoriginal** content. Our own risk is a formulaic channel posting near-identical cross-posts. Mitigation: distinct scripts and jokes, human editorial control, platform-specific edits (not identical uploads), and a joke ledger.
- **Do not cross-post with another platform's watermark** and **do not assume identical captions, hooks, titles or lengths work everywhere.**

## 7. Per-episode package [PROPOSED]

```
episodes/E001/
  brief.md   script.md   storyboard/
  scene-graph/        platform-neutral shot descriptions (JSON)
  audio/stems/        one file per character, SFX, music, ambience
  audio/mix/          master mix(es)
  captions/           master transcript + per-ratio caption layouts + SRT/VTT
  renders/
    master-169/       T2 master (or derived)
    master-916/       T1 master (or derived)
    cutdowns/         vertical edits from the T2 master
  publish/            one metadata file PER PLATFORM (see §9)
  rights-ledger.md    every voice, music, SFX and font source and licence
  qa-checklist.md
```

## 8. Export presets [PROPOSED, not built]

A preset is a small declarative file, for example:

```json
{
  "id": "shorts-916",
  "profile": "P-916",
  "size": [1080, 1920], "fps": 30,
  "video": "H.264, yuv420p", "audio": "AAC",
  "loudness": "to be set from platform guidance",
  "captions": {"burn_in": true, "zone": "to be set from the safe-zone guide", "sidecar": "srt"},
  "max_seconds": 180,
  "notes": "limits to be re-verified before use"
}
```

Presets exist for: YouTube Shorts, TikTok, Facebook Reels, YouTube long-form, Facebook video. Values marked "to be set" are **deliberately empty** until verified. The renderer already writes H.264 video and AAC audio (CRF 20, 192 kbps) **[VERIFIED]**, so presets mostly re-frame, burn captions and re-encode with FFmpeg, outside the renderer.

## 9. Publishing metadata per platform [PROPOSED, separate files]

`publish/<platform>.json` for each of `youtube-shorts`, `youtube-long`, `tiktok`, `facebook-reels`, `facebook-video`:

| Field | Notes |
|---|---|
| `title` / `caption` | Different lengths and styles per platform; YouTube title ≤ 100 chars **[OFFICIAL]** |
| `description`, `hashtags` | Written for the platform, not copied |
| `opening_hook` | The first 1–3 seconds' text/visual hook, written per platform |
| `thumbnail` / `cover` | Per platform and ratio |
| `captions` | Language, sidecar file, burn-in yes/no |
| `audience` | "Made for kids" answer (YouTube): **no**; other platforms' equivalents to be researched |
| `ai_disclosure` | The answer given and the reasoning (animated, non-realistic; synthetic voice note) |
| `rights` | Links to the rights ledger entries (music, SFX, fonts, voices) |
| `schedule` | Planned time; manual for now |
| `status` | draft → approved → uploaded (**manually**); no API |

## 10. Platform adaptation checklist (per episode) [PROPOSED]
1. Complete original episode (master).
2. Two or three short-form edits recomposed for 9:16 (not crops).
3. A platform-specific **hook** (first 1–3 s) for each platform.
4. Platform-specific **captions** (style, length, placement; burned in per profile).
5. Titles, descriptions, hashtags per platform.
6. Thumbnail (16:9) and **cover** frames (9:16).
7. Safe-framing check with overlay guides.
8. Duration chosen per platform, not copied.
9. Disclosure answers and rights ledger reviewed.

## 11. Safe-framing rules for authors [PROPOSED]
- Stage the joke in the **action-safe square**.
- Faces stay in the middle third of the portrait window; no key action at the edges.
- Text inserts: large, short, inside the safe square.
- Avoid wide two-shots as the only way to see a reaction; always provide a cut-in that works in portrait.
- Backgrounds carry extra context outside the square, never essential information.
- Check every shot with **overlay guides** (action-safe square plus platform UI zones). Guides are to be made later.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Safe-square staging limits composition | Allow per-ratio overrides; review early with guides |
| Fixed renderer caption position | Burn in captions externally (option (a), §5) |
| Platform policy drift (AI labels, originality, monetization) | Re-verify before each publishing decision; keep the rights ledger and disclosure log |
| Cross-posting seen as duplicate or unoriginal | Platform-specific edits, hooks and captions; no identical uploads |
| Music and SFX licences differ by platform and by monetization | Rights ledger; do not assume "free" means cleared everywhere |
| Workload creep from five outputs per episode | Keep presets declarative; automate rendering and packaging first, uploading last |
| Realistic synthetic voices | Choose clearly non-realistic or human voices; never clone real people |

## 13. Research still to do before any publishing automation [TODO]
1. **Official** specs and policies for **TikTok** and **Meta (Facebook/Reels)**: length, ratio, resolution, file size, safe zones, AI labelling, originality, monetization eligibility. (Official pages could not be read in this pass.)
2. YouTube long-form and Shorts monetization requirements for animated, AI-assisted channels; the current "inauthentic content" wording.
3. Per-platform music and sound-effect licensing, including commercial-use and monetization rules.
4. Account and API terms for scheduled or automated posting on each platform (permissions, audits, quotas), **only when automation is approved**.
5. Platform safe-zone templates for 9:16.
6. Thumbnail and cover specifications per platform.

## 14. Decisions requested

| ID | Decision | Recommendation |
|---|---|---|
| **M10** | Adopt "author once, render many" (square superframe plates, scene graph, framing profiles) | Approve |
| **M11** | Master rule: T1 shorts vertical-first; T2 episodes 16:9 with vertical cut-downs | Approve |
| **M12** | Burn captions in externally, per platform (not with the renderer's fixed captions) | Approve in principle |
| **M13** | Whether to support a 1:1 or 4:5 profile | Not now |
| **M14** | Facebook scope: Reels only at first, or Reels plus 16:9 videos | Reels first; add 16:9 once the pipeline is proven |
| **M15** | Per-platform account names and branding consistency | Owner to decide |
| **M16** | Approve the research TODO (§13) as the next research step | Approve |

## Sources used in this pass
- YouTube Help, Shorts: <https://support.google.com/youtube/answer/10059070> **[OFFICIAL]**
- YouTube Help, altered or synthetic content: <https://support.google.com/youtube/answer/14328491> **[OFFICIAL]**
- Secondary (third-party, not confirmed on official pages): [YouTube Shorts length and ratio guides](https://riverside.com/blog/how-long-can-youtube-shorts-be) · [TikTok specs guide](https://www.heyorca.com/blog/tiktok-media-specs-best-practices-2026) · [Facebook Reels specs](https://postiz.com/blog/facebook-reel-size) · [YouTube inauthentic-content coverage](https://ppc.land/youtube-clarifies-inauthentic-content-policy-changes/) · [TikTok AI-label coverage](https://www.echotik.live/blog/tiktok-ai-content-labeling-rules-2026/) · [Meta originality update, TechCrunch, Mar 2026](https://techcrunch.com/2026/03/13/facebook-makes-it-easier-for-creators-to-report-impersonators/) · [Meta originality, MediaPost](https://www.mediapost.com/publications/article/413530/meta-defines-original-content-tests-protection.html)
- Attempted but not retrievable: TikTok's official AI-content help page (did not render) and a Meta transparency page (404).

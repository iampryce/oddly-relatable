# Stickman Comedy Studio — Channel Bible

> ⚠️ **PARTLY SUPERSEDED (owner direction, 2026-11-11):** the channel is for the **world at large**: **no Nigerian/African-specific stories, settings, names or language, and Femi is retired.** The cast, names, locations, language notes and jokes in this document were drafted for a West African setting and are **paused pending a rewrite**. Treat them as archive and templates (roles, structure and technique may carry over), **not as approved content**. See `DECISIONS.md` (AP-16 to AP-18).

> ## 🔒 VISUAL IDENTITY PERMANENTLY LOCKED (owner decision, 2026-11-11; AP-51 to AP-57)
> The channel's identity is **simple, expressive 2D characters + richly illustrated, cinematic 2D environments**, exactly as shown in the canonical reference [`bible/concepts/lookdev-richenv/lookdev-scene-01.png`](concepts/lookdev-richenv/lookdev-scene-01.png) (SHA-256 `36b7c97e…ff016`, read-only). **Do not redesign, replace, reinterpret or propose alternative visual styles. Do not silently alter this decision.** Anything in this document that describes an earlier look (Inkblock, 2.5D Modern Pop, vector puppet kits, "Stickstage" exploration) is **superseded**. Specification and rules: [VISUAL_IDENTITY.md](VISUAL_IDENTITY.md).

**Status:** Phase 1 draft for review · **Version:** 0.1 · **Date:** 2026-11-11
**Owner approval:** pending. Nothing in this bible marked *PROPOSED* is a decision until approved.

This is the master document. It states the channel's purpose, collects the approved requirements, links the detailed bibles, and lists every decision still waiting for approval.

---

## Multi-platform brand (APPROVED by the owner, 2026-11-11)

Stickman Comedy Studio is a **multi-platform animation brand for YouTube, TikTok and Facebook**, not a YouTube-only channel.
- **Primary format: 9:16 vertical** (YouTube Shorts, TikTok, Facebook Reels). **Secondary: 16:9 landscape** (longer YouTube episodes and suitable Facebook distribution).
- **International identity:** original stories about universal experiences (human behaviour and psychology, relationships and dating, workplace, money and adult life, friendship, everyday frustrations, funny hypotheticals). **African or Nigerian storytelling must not define the identity.**
- **Do not double production work:** reusable characters and backgrounds must adapt to portrait and landscape.
- **Per episode:** a complete original episode, short-form edits, platform-appropriate hooks and captions, titles, descriptions and thumbnails, and safe framing that survives cropping. Identical uploads, durations or captions are **not** assumed optimal everywhere.
- **No publishing automation and no platform APIs yet.** Platform specifications and policies must be researched before any automation is finalised.
- Architecture, research findings and open decisions: [MULTI_PLATFORM_ARCHITECTURE.md](MULTI_PLATFORM_ARCHITECTURE.md).

## How to read this bible

Every section uses one of three labels:

| Label | Meaning |
|---|---|
| **[APPROVED]** | A requirement you have already given. Do not change it without your instruction. |
| **[PROPOSED]** | A new creative or production recommendation from this draft. Open to change. |
| **[DECISION Dn]** | A choice that blocks or shapes later work. Listed in full in [Decisions awaiting approval](#decisions-awaiting-approval). |

Statements about the renderer are marked **(verified)** when they were checked in the code of `skills/directing-stickman-videos/scripts/`. All other technical statements are recommendations.

---

## 1. Channel in one paragraph [PROPOSED]

Stickman Comedy Studio is an animated comedy channel about the small disasters of adult life: the text that says *"we need to talk"*, the meeting that should have been an email, the friend whose advice is always wrong, the bill that arrives the day after payday. A recurring cast of expressive stick characters lives in a modern, unnamed West African city that any viewer in the world recognises as "a big, busy city like mine". The humour comes from character, timing and reaction, not from shouting or cruelty.

**Tagline options** (see D1): *"Adulting, but make it stick."* · *"Small drama. Big reactions."* · *"Life is a group chat."*

## 2. Approved requirements [APPROVED]

Collected from the Phase 0–1 instructions:

1. A second channel, completely separate from the Kids Animation Studio. Never use or modify that project.
2. Original visual identity. Do not copy existing YouTube animation channels or the repository's reference styles (A1–A6, B1–B5).
3. Hybrid animation: pose-based and keyframed animation is the default. Full-motion AI video is used only where it materially improves comedy or storytelling.
4. Content: workplace comedy, marriage and relationships, friendship, money and adult life, interesting facts and psychology, funny hypothetical stories.
5. Humour that works internationally. ~~with occasional Nigerian/African situations that international audiences can follow.~~ **Superseded 2026-11-11: African or Nigerian storytelling must not define the identity.**
6. Recurring characters with distinct personalities, relationships, flaws and comedic behaviour.
7. Balanced relationship humour: neither partner is always the villain or the fool.
8. Production should stay lightweight, affordable and locally rendered.
9. First pilot: **"When Your Wife Says We Need to Talk."**
10. Phase 1 is documentation only: no artwork, video, audio, paid API calls, new dependencies, renderer changes or Skill reference changes.
11. **Multi-platform:** YouTube, TikTok and Facebook (2026-11-11).
12. **Primary format 9:16; secondary 16:9** (2026-11-11).
13. **Do not double production work**; reusable assets across aspect ratios (2026-11-11).
14. **No publishing automation or platform API connections yet**; research platform specs and policies first (2026-11-11).
15. **Visual identity permanently locked** to the canonical reference image: simple expressive 2D characters plus richly illustrated cinematic 2D environments (2026-11-11, AP-51).
16. **The character in the canonical image is the master character (Canonical Character 01)**; every future character and environment must belong to the same animated universe (AP-52 to AP-54).

## 3. Audience and tone [PROPOSED]

**Primary audience:** adults aged 18–40 who work, date, are married or are tired, in Nigeria, the wider African diaspora, the UK, North America and anywhere English-language comedy travels.

**Tone pillars**

| Pillar | Means | Does not mean |
|---|---|---|
| Relatable | "This happened to me last week." | Inside jokes that need explaining |
| Warm | Characters like each other underneath the chaos | Mean-spirited roasting |
| Sharp | Tight timing, no padding, trust the audience | Over-explained jokes |
| Specific | Concrete details (the labelled leftovers, the 4% battery) | Generic "relationships be like" |
| Local flavour, global sense | Jollof, danfo-style buses, power cuts, shown so anyone understands | Jokes about tribes, religion or nationality as punchlines |

**Content boundaries** (always apply):
- No humour that punches down at ethnicity, tribe, religion, disability, body size or class.
- No domestic abuse, coercion or infidelity played for laughs.
- No real people, brands or creators as characters. Parody brands must be invented.
- Family-friendly language. Mild exclamations are fine, profanity is not. This keeps advertiser suitability high.
- Gender balance in who is "right" across episodes (tracked; see `CHARACTER_BIBLE.md` §Balance rules).

## 4. Document map

| File | Covers |
|---|---|
| `CHANNEL_BIBLE.md` | This overview, approved requirements, decisions |
| `VISUAL_IDENTITY.md` | **LOCKED visual identity** (canonical image, master character, rules for all future characters and environments). The old Inkblock draft is archived in `_archive-superseded/` |
| `concepts/lookdev-richenv/CANONICAL_REFERENCE.md` | The canonical image, its hash, preserved copies and integrity rules |
| `CHARACTER_BIBLE.md` | The recurring cast, relationships, balance rules, continuity facts |
| `WORLD_BIBLE.md` | The city and its reusable sets |
| `COMEDY_WRITING_GUIDE.md` | The six-beat structure, dialogue, timing, joke ledger rules |
| `ANIMATION_DIRECTION.md` | The hybrid production method, puppet kits, renderer mapping, premium-motion rules |
| `AUDIO_DIRECTION.md` | Voices, music, SFX, stems and mixing |
| `CONTENT_STRATEGY.md` | Six pillars, topics, formats, Shorts, balance, cadence |
| `EPISODE_FORMATS.md` | Shorts, standard episodes and long stories with beat templates |
| `PILOT_TREATMENT.md` | Creative treatment for "When Your Wife Says We Need to Talk" (paused: written for the retired cast) |
| `MULTI_PLATFORM_ARCHITECTURE.md` | YouTube + TikTok + Facebook architecture: formats, reuse across ratios, framing profiles, platform matrix with evidence labels, metadata, research TODO |
| `VISUAL_DIRECTION_COMPARISON.md`, `VISUAL_DIRECTION_RICH_ENVIRONMENTS.md` | Visual-direction investigation (open) |

**Suggested additions later** (not created now): `CONTINUITY_LOG.md` (facts established per episode), `JOKE_LEDGER.md` (every joke used, to prevent repeats), `RIGHTS_LEDGER.md` (every music/SFX/font source and its licence). They become useful once episodes exist.

## 5. Originality safeguards [PROPOSED]

Before any design or script is approved, check it against these:

1. **Not a repository style.** The Inkblock look deliberately avoids the repository's signatures: white round heads with black stick limbs, pure black-on-white line art, hand-drawn crayon props on a grid, warm paper texture, dark retro-TV glow, white gloves, beanie-and-yellow-shirt mascots, amber-and-plum noir, prehistoric hides and the corner presenter layout. See `VISUAL_IDENTITY.md` §12.
2. **Not a creator's look.** No design is described as "in the style of" any channel or artist. No reference images from other creators are used to generate our characters.
3. **Original names, places and brands.** Invented company names (Brightline Logistics, FixAm Phones, Natter messaging app). No real brand logos.
4. **Original audio.** Original or properly licensed music and SFX, recorded in a rights ledger. No soundalikes of famous themes.

## 6. Production principles [PROPOSED]

1. **Reuse first.** Every set, pose and expression is built once and reused. A new episode should need few new assets.
2. **Reaction over motion.** A well-timed face change beats a fully animated movement. Spend effort on expressions and timing.
3. **Character consistency is non-negotiable.** Any shot that makes a character look off-model is cut or redone, however good the motion.
4. **Premium motion is earned.** Full-motion AI clips need a written reason (see `ANIMATION_DIRECTION.md` §8) and stay within the per-episode budget.
5. **Local render, cloud only for generation.** The existing renderer composes the final film offline; cloud services are used only for voice, optional images and optional premium clips, each with cost approval.
6. **Verify before publishing.** Every episode is reviewed in picture and sound, captions included, before upload.

## 7. Glossary

| Term | Meaning |
|---|---|
| Inkblock | The proposed house art style (see `VISUAL_IDENTITY.md`) |
| Puppet kit | One character's reusable set of body poses, heads, eyes, brows, mouths and hands |
| Plate | A reusable background image for a set, at a fixed camera position |
| Doom tint | The signature colour-grade overlay used for dread moments |
| Premium motion | A short full-motion AI video clip used selectively |
| Beat | One story unit in the six-beat structure |
| Stem | One separately mixed audio track (a single character's dialogue, music, SFX, ambience) |

---

## Decisions awaiting approval

Nothing below is final until you approve, change or reject it.

| ID | Decision | Recommendation | Where |
|---|---|---|---|
| D1 | Channel name and tagline | Keep "Stickman Comedy Studio" as the working name; choose a public name before the first upload | §1 |
| D2 | ~~Adopt the Inkblock visual identity~~ **SUPERSEDED: the visual identity is permanently locked to the canonical image (AP-51)** | n/a | `VISUAL_IDENTITY.md` |
| D3 | ~~How character art is made (vector puppet kits)~~ **SUPERSEDED by the locked look.** Reference-conditioned generation was shown to keep the master character strongly on-model; the exact pipeline is still to be decided and must match the canon | Owner to approve the pipeline later | `ANIMATION_DIRECTION.md` |
| D4 | Core cast: names, backgrounds, ages, jobs | Approve the 6 human leads and the cat; trim or rename as you wish | `CHARACTER_BIBLE.md` |
| D5 | Couple status: married 3 years, no children yet | Approve; keeps future storylines open | `CHARACTER_BIBLE.md` |
| D6 | Setting: unnamed modern West African city | Approve; keeps it international while clearly local | `WORLD_BIBLE.md` §1 |
| D7 | Language mix: English with light Nigerian English and occasional Pidgin, captions always on | Approve | `COMEDY_WRITING_GUIDE.md` §3 |
| D8 | Voices: AI text-to-speech or human voice actors | Audition both before the pilot; human actors preferred for the two leads if budget allows | `AUDIO_DIRECTION.md` §2 |
| D9 | Narrator: none in comedy episodes; optional in facts and hypothetical videos | Approve | `AUDIO_DIRECTION.md` §3 |
| D10 | Premium-motion budget: at most 10% of runtime, at most 3 clips per episode, provider chosen later | Approve the limits now; choose the provider at pilot planning | `ANIMATION_DIRECTION.md` §8 |
| D11 | Initial content balance across the six pillars | Approve the starting mix | `CONTENT_STRATEGY.md` §2 |
| D12 | Pilot format: standard episode, about 2:45, plus two Shorts cut from it | Approve | `EPISODE_FORMATS.md` §5 |
| D13 | Pilot twist and closing callback | Approve the "Mummy is coming for three months" reveal and the boss-text ending | `PILOT_TREATMENT.md` |
| D14 | ~~Aspect ratios: 16:9 for episodes; 9:16 recomposed natively for Shorts~~ **Superseded by the approved multi-platform direction: 9:16 primary, 16:9 secondary** (see `MULTI_PLATFORM_ARCHITECTURE.md` and decisions M10–M16) | n/a | `EPISODE_FORMATS.md` |
| D15 | Fonts for titles and captions (free, open-licence fonts) | **Open.** Not part of the locked identity; the old shortlist was in the archived Inkblock draft | n/a |
| D16 | Music direction and sonic logo | Approve the direction; sourcing decided at pilot planning | `AUDIO_DIRECTION.md` §4 |
| D17 | Upload cadence | **Needs re-planning per platform** (YouTube, TikTok, Facebook); the earlier YouTube-oriented proposal is a placeholder | `CONTENT_STRATEGY.md` §5 |
| D18 | Master resolution: 1920×1080 at 30 fps (renderer supports up to 3840 wide, verified) | Approve | `ANIMATION_DIRECTION.md` §5 |
| D19 | Brand colours: Tangerine and Teal | **Open.** Part of the superseded Inkblock draft; **not** part of the locked identity | n/a |
| D20 | Cultural-humour rules, including in-law jokes | Approve the boundaries in §3 and `COMEDY_WRITING_GUIDE.md` §9 | `COMEDY_WRITING_GUIDE.md` |
| D21 | Documentation home: keep in this repository's `bible/`, mirror to Confluence later | Approve; Confluence needs the Atlassian connector authorised | §4 |
| D22 | Renderer strategy: keep the renderer unchanged and supply tooling outside it (B1 style with the grid off, a pre-mixed audio master, overlay PNGs, a camera-move generator); revisit a new style only if the limits bite | Approve; any renderer edit needs separate explicit approval | `ANIMATION_DIRECTION.md` §2, §11 |
| D23 | Whether to publish these documents elsewhere (Confluence internally, public docs site) | Not now; internal only until the bible is approved | §4 |

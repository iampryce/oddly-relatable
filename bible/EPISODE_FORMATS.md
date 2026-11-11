# Episode Formats

> ## 🔒 VISUAL IDENTITY PERMANENTLY LOCKED (owner decision, 2026-11-11; AP-51 to AP-57)
> The channel's identity is **simple, expressive 2D characters + richly illustrated, cinematic 2D environments**, exactly as shown in the canonical reference [`bible/concepts/lookdev-richenv/lookdev-scene-01.png`](concepts/lookdev-richenv/lookdev-scene-01.png) (SHA-256 `36b7c97e…ff016`, read-only). **Do not redesign, replace, reinterpret or propose alternative visual styles. Do not silently alter this decision.** Anything in this document that describes an earlier look (Inkblock, 2.5D Modern Pop, vector puppet kits, "Stickstage" exploration) is **superseded**. Specification and rules: [VISUAL_IDENTITY.md](VISUAL_IDENTITY.md).

### What the locked identity means for formats
All formats (Shorts, standard episodes, long stories, vertical and landscape) use the locked look. The canonical vertical frame suggests a **framing guide** that fits vertical-first distribution: calm space near the **top** for a title, a clear **bottom band** for captions, the character at about **one third of the frame height**, and cropped **foreground objects** at the edges for depth. The 16:9 reframe of the same illustrated plates, the action-safe staging and the per-platform framing remain as described in `MULTI_PLATFORM_ARCHITECTURE.md`.

**Status:** the three length bands (60–90 s Shorts, 2–4 min episodes, 5–8 min stories) are **[APPROVED]** (your list). The templates and the pilot-format recommendation are **[PROPOSED]**; the pilot format is decision **D12**, aspect ratios **D14**.

Word counts use about 130–150 spoken words per minute including pauses (`COMEDY_WRITING_GUIDE.md` §3). Shot counts are estimates for the pose-based default method.

---

## 0. Multi-platform rules (APPROVED 2026-11-11; details PROPOSED)

- **Primary format 9:16 vertical** (YouTube Shorts, TikTok, Facebook Reels). **Secondary 16:9** (longer YouTube episodes, suitable Facebook video).
- **Two tiers.** **T1 native short:** a complete 30–90 s story, mastered in 9:16. **T2 episode:** a complete 2–8 min story, mastered in 16:9, with **2–3 vertical cut-downs** recomposed from it. The other ratio is **derived by reframing, not re-authored**, wherever staging allows.
- **Reuse, not doubling:** characters are ratio-independent vector puppets; backgrounds are square "superframe" plates with 9:16 and 16:9 windows; shots are described once in a platform-neutral scene graph and rendered per framing profile. Essential action stays inside the central **action-safe square**. Estimated extra effort for the second ratio: about 10–25% per episode, not 100% (an assumption).
- **Per platform:** its own hook, captions, title, description, thumbnail or cover, and duration. No identical uploads.
- **Platform limits already confirmed on official pages:** YouTube Shorts up to **3 minutes**, vertical, 1080p maximum. TikTok and Facebook limits are **not yet confirmed officially** and must be researched before finalising (see `MULTI_PLATFORM_ARCHITECTURE.md` §6 and §13).
- **Renderer caption limit:** the renderer's captions sit at a fixed bottom position, which platform interfaces cover in portrait. The plan is to burn captions in externally per platform (M12).

## 1. Format A: Comedy Short (60–90 seconds)

**Purpose:** a single joke or one tiny escalation; discovery and sharing.
**Orientation:** **primary format.** Native **9:16** (1080×1920): authored vertical-first (T1), or recomposed from a 16:9 episode master (T2 cut-down); never a naive crop. Platforms: YouTube Shorts (up to 3 min, official), TikTok, Facebook Reels. [M2]
**Characters:** one or two. **Sets:** one.
**Spoken words:** 100–180.

| Beat | Time (90 s) | Content |
|---|---|---|
| Hook | 0–4 s | A visual or line that explains the premise immediately |
| Setup | 4–15 s | One fact about the situation |
| Escalation | 15–55 s | Two or three escalating exchanges |
| Misdirection and punchline | 55–78 s | The twist and the reveal |
| Closing beat | 78–90 s | A tag: reaction, callback or sting |

**Shot plan:** 15–25 shots, mostly close and medium. Larger text and faces for phone screens.
**Production notes:** captions larger and in the upper-middle safe zone (avoid the bottom interface area); one location; no more than 15 unique poses.
**Premium motion:** none by default.
**Cost level:** lowest.

## 2. Format B: Standard Episode (2–4 minutes)

**Purpose:** the channel's core format. A complete story with a hook, escalation and twist.
**Orientation:** 16:9 (1920×1080) master for YouTube long-form and suitable Facebook video. Two or three vertical cut-downs are recomposed from it (see §0). [M3]
**Characters:** two to four. **Sets:** two to three.
**Spoken words:** 260–560.

| Beat | Share | At 3:00 |
|---|---|---|
| Hook (cold open) | 4% | 0:00–0:08 |
| Setup | 15% | 0:08–0:35 |
| Escalation | 38% | 0:35–1:43 |
| Misdirection | 14% | 1:43–2:08 |
| Punchline | 12% | 2:08–2:30 |
| Closing beat and end card | 17% | 2:30–3:00 |

**Shot plan:** 45–80 shots. About 60% Tier 1, 30% Tier 2, up to 10% Tier 3 premium motion (`ANIMATION_DIRECTION.md` §6).
**Structure options:**
- **The spiral:** one trigger and an escalating chain (the pilot).
- **The two-hander:** two characters trade escalating attempts.
- **The ensemble chaos:** a situation draws in three or four characters.
- **The fact-twist:** a fact is explained, then misapplied.

**Cost level:** medium. The pilot is this format.

## 3. Format C: Long Story (5–8 minutes)

**Purpose:** sagas that deepen characters; watch-time and loyalty. Not before the library exists.
**Orientation:** 16:9.
**Characters:** four to six. **Sets:** three to five.
**Spoken words:** 650–1,100.

| Part | Time (at 7:00) | Content |
|---|---|---|
| Hook | 0:00–0:15 | Cold open with the central problem |
| Act 1: Setup | 0:15–1:30 | Introduce the situation and stakes |
| Act 2a: Escalation | 1:30–3:30 | Complications, new characters, a first false resolution |
| Midpoint twist | 3:30–4:15 | The situation changes |
| Act 2b: Escalation | 4:15–5:45 | Everything goes wrong at once |
| Act 3: Climax | 5:45–6:30 | Punchline and reversal |
| Closing beats | 6:30–7:00 | Warm ending, callback, tag |

**Structure:** a **mini three-act** with at least two mini-punchlines before the final one, so the energy does not sag. Add a recap-free structure: never summarise the plot.
**Shot plan:** 100–170 shots, up to 10% premium motion.
**Cost level:** highest; at least 3× a standard episode. Introduce after the standard format is working.

## 4. Common requirements for all formats

- **Cold open**, then a 2–3 s sonic logo and title card (Shorts skip the title card).
- **End card** (3–5 s) with the next-video prompt and a Pepper stare.
- **Always-on captions.**
- **Thumbnail** with one big face and 2–4 words.
- **Deliverables per episode:** MP4, SRT/VTT, thumbnail, title, description, pinned comment, source notes (facts episodes), balance-log entry, Joke Ledger update, rights ledger update.
- **Review gates:** script approval → storyboard → 20-second preview → full render → final QA.

## 5. Pilot format recommendation [PROPOSED, D12]

**Format B (Standard Episode), about 2:45, plus two Shorts cut from it.**

Why:
- A 2:45 standard episode is long enough to show the cast, the escalation and the twist, and short enough to stay within the render and cost limits proven in Phase 0.
- A Short-only pilot would not demonstrate the characters. A long story would risk cost and sag before the pipeline exists.
- Two Shorts (one vertical recompose of the Worst-Case Theatre, one of the final reveal) test the vertical workflow cheaply.

**Pilot deliverables:** 1 episode (16:9), 2 Shorts (9:16), thumbnail, title and description options, source ledger.

## 6. Aspect ratios and safe zones [PROPOSED; D14 superseded by the approved multi-platform direction]

> The table below is an early draft. The current proposal (framing profiles P-916 and P-169, the action-safe square, per-platform caption zones and export presets) is in [MULTI_PLATFORM_ARCHITECTURE.md](MULTI_PLATFORM_ARCHITECTURE.md) §4–§5. Platform UI safe-zone numbers are **not yet verified**, so none are given here.


| Format | Size | Fps | Caption zone |
|---|---|---|---|
| Episodes | 1920×1080 | 30 | Bottom centre, one line; renderer reserves the bottom band (verified) |
| Shorts | 1080×1920 | 30 | Upper-middle (about 60–70% down the frame to avoid platform overlays) |

The renderer keeps the bottom 110 design units clear for captions and supports portrait natively, but portrait scenes need a hand-made composition (verified). The recompose is a real layout, not an automatic crop.

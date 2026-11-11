# Visual Identity — "Inkblock"

> ⚠️ **PARTLY SUPERSEDED (owner direction, 2026-11-11):** the channel is for the **world at large**: **no Nigerian/African-specific stories, settings, names or language, and Femi is retired.** The cast, names, locations, language notes and jokes in this document were drafted for a West African setting and are **paused pending a rewrite**. Treat them as archive and templates (roles, structure and technique may carry over), **not as approved content**. See `DECISIONS.md` (AP-16 to AP-18).

**Status:** [PROPOSED] in full. Approval is decision **D2**.
**Approved constraint it answers:** original, distinctive, expressive, clean, suitable for repeated animation, recognisable by silhouette, not imitating any creator or the repository's styles. [APPROVED]

---

## 1. The idea in one line

**Stick limbs, solid character.** Each character is a coloured "garment block" body and a uniquely shaped, skin-toned head on simple ink stick limbs, with **floating eyebrows** that do half the acting.

### The five signature marks

These are what make a frame recognisably ours. Every character design and every shot should keep all five.

| # | Mark | What it is | Why |
|---|---|---|---|
| 1 | **Head-shape language** | Each character has a different head geometry (domino, egg, circle, tall oval, soft square, heart) | Silhouette recognition even in black fill |
| 2 | **Floating brows** | Thick, rounded brow strokes that hover just above the face and are never attached to the outline | Big, readable emotion with one sprite swap; brows can "leave the head" in shock |
| 3 | **Garment block** | The torso is one filled, rounded shape in the character's signature colour | Colour identity from across the room; cheap to recolour for outfits |
| 4 | **Indigo ink** | All lines are deep indigo-charcoal (#262A3B), never pure black | Softer, more modern look; separates us from black-line styles |
| 5 | **Mood tints** | Full-screen colour grades for emotional states (Doom Tint, Flashback, Daydream) | Instant emotional read and a recurring visual joke |

---

## 2. Body proportions

Measured in **head units (H)**: the height of that character's head. Reference height is for a 1920×1080 frame with the character in a standard medium-wide shot.

| Part | Rule |
|---|---|
| Overall height | 3.0–3.8 H depending on the character (see §8). Big heads = readable faces. |
| Standard on-screen height | Adults ≈ 540 px tall in a medium-wide shot at 1080p (≈ half the frame) |
| Neck | Short ink stick, 0.15 H. Visible; the head never sits directly on the body. |
| Garment block (torso) | 1.0–1.2 H tall. Rounded trapezoid, corner radius ≈ 18% of its width. Shoulders slightly wider than hips for most adults. |
| Arms | Two segments (upper and forearm), each 0.65 H. Hang to mid-thigh. |
| Legs | Two segments, each 0.6–0.75 H, starting from under the garment block |
| Hands | Lollipop hands: a filled circle 0.18 H in diameter, skin tone, ink outline |
| Feet | Capsule shoes 0.32 H long, signature or accent colour |

**Dresses and long garments:** the garment block extends to knee or ankle (Amara's work dress, Mummy Eze's wrapper). Legs show below.

**Posture rule:** characters lean. Neutral standing has a slight 3–5° tilt or hip shift. Perfectly vertical means "frozen with fear", which is a joke in itself.

## 3. Head and face

### Head construction
- Filled with the character's **skin tone**, with a 6 px indigo outline.
- Each head shape is a smooth geometric primitive (superellipse, egg, circle) so it can be drawn as vector and stays identical every time.
- Hair is a separate solid shape layered on or around the head, in near-black brown (#2B211C) unless stated. Hair is the second silhouette signature after head shape.
- Ears: none by default. Earrings and accessories hang from where ears would be.

### Eyes: "pill eyes"
- Two solid indigo vertical capsules, each 0.18 H tall, with a single small white highlight dot (upper right).
- Spacing: one eye-width apart, placed at 45–50% of head height.
- No white sclera in the neutral state. White rings appear only for shock.

| Eye state | Shape |
|---|---|
| Neutral | Standard capsules |
| Happy / laughing | Upward arcs ("^ ^") |
| Tired / unimpressed | Capsules cut flat on top (half-lidded) |
| Shocked | Small dots inside white circles with indigo rings |
| Panic | Tiny dots, eyes drift apart |
| Suspicious | One capsule normal, one narrowed to a slit |
| Dreamy / in love | Capsules with two highlight dots |
| Crying | Neutral eyes plus two blue tear streams (FX layer) |
| Dead inside | Flat horizontal lines |

### Floating brows (signature)
- Thick, rounded strokes, 0.06 H thick and 0.28 H long, in hair colour.
- Float 0.08 H above the eyes, never touching the head outline.
- Each character's default brow angle is part of their personality (see `CHARACTER_BIBLE.md`).

| Brow state | Use |
|---|---|
| Level | Neutral |
| Raised both | Surprise, interest |
| **One raised** | Scepticism (Amara's signature) |
| Inner ends up | Worry, guilt, pleading (Femi's default under stress) |
| Inner ends down (V) | Anger, determination |
| Flat and low | Deadpan, unimpressed |
| **Lift-off** | Extreme shock: brows rise above the head outline and hover (comedy beat) |
| Wiggle | Flirting, scheming, "I know something" |

### Mouths
- Indigo line, 5 px. When open, filled with deep warm red (#6E2B2B), a white teeth bar for grins, and a pink tongue only for big laughs.

**Expression mouths (12):** neutral line, small smile, big grin, laugh (open), smug (one-sided), frown, worried wobble, tight line (holding it in), shout, "O" shock, grimace (teeth clenched), disgust (side twist).

**Lip-sync visemes (6):** closed (M/B/P), A (open wide), E (wide, teeth), O (round), U/W (small round), F/V (lower lip under teeth). Mouths for L and TH use A and E.

## 4. Limbs, hands and feet

- **Limb line:** 8 px indigo at 1080p, round caps and round joins.
- **Joints:** no visible joint dots. Elbows and knees bend in smooth curves for relaxed poses and sharp angles for comedic tension.
- **Hands:** lollipop circles by default. A small library of **hand shapes** is drawn for gestures that must read clearly:
  open palm, pointing, fist, thumbs up, phone grip, wave, facepalm, counting (1, 2, 3), holding (cup, bag, folder), "OK".
- **Feet:** capsule shoes in the signature or accent colour. For tiptoeing, feet become small circles. For "about to run", heels lift.
- **Arm count rule:** two arms, always. Motion blur and duplicated arms for frantic movement are FX layers, not extra limbs.

## 5. Outline thickness (at 1920×1080)

| Element | Thickness | Colour |
|---|---|---|
| Character outline (head, garment, hair, shoes) | 6 px | Indigo ink #262A3B |
| Limbs | 8 px | Indigo ink |
| Facial features | 5 px (mouth), solid fills (eyes, brows) | Indigo / hair colour |
| Props held by characters | 5 px | Indigo ink |
| Background foreground objects | 4 px | 40% darker than the object's fill |
| Background far objects (walls, windows, distant buildings) | 2–3 px or no outline | 25% darker than fill |

**Rule:** characters always have the heaviest, darkest lines in the frame. Backgrounds never compete.

## 6. Colour palette

### Core

| Name | Hex | Use |
|---|---|---|
| Indigo Ink | #262A3B | All character lines, key text |
| Canvas | #FBF8F2 | Default empty background, title cards |
| **Tangerine** (brand) | #FF7A3C | Brand accent, Amara's signature colour, thumbnails |
| **Teal** (brand) | #17A398 | Brand accent, Femi's signature colour |
| Sunbeam | #FFC845 | Highlights, emphasis marks, idea moments |
| Alarm Red | #E5383B | Danger, warnings, "red flag" jokes |
| Sky | #8FD3F4 | Tears, water, cool emphasis |

The brand pair (Tangerine and Teal) is the couple's pair: the channel's identity is literally the relationship. Approval: **D19**.

### Skin tones (character heads and hands)

| Code | Hex | |
|---|---|---|
| S1 | #4E2F1F | Deep |
| S2 | #6B4026 | Deep warm |
| S3 | #8A5734 | Medium deep |
| S4 | #A9714A | Medium |
| S5 | #D19E74 | Light medium |
| S6 | #EDC9A6 | Light |

Most of the core cast sits in S1–S4. The range exists so the world feels like a real, mixed modern city.

### Character signature colours
Listed per character in `CHARACTER_BIBLE.md`. Rule: no two main characters share a signature hue, and every signature colour must stay distinguishable in greyscale (checked by value, not only hue).

### Environment colours
Backgrounds use **muted mid-tones**: saturation at or below about 35%, lighter in value than the characters. Each set has a dominant hue family (see `WORLD_BIBLE.md`). This keeps characters popping without needing outlines on everything.

## 7. Clothing and accessories

- Clothing is expressed through the **garment block** shape and colour, plus at most two small details (collar, stripe, pocket, buttons, lanyard).
- **Signature outfit:** each character has one default outfit used in 80% of appearances. Outfit changes are deliberate story signals (wedding, gym, interview).
- **Accessories carry personality:** Femi's round glasses, Amara's gold hoops, Tunde's bucket hat, Dez's earbuds, Madam F's glasses chain, Zee's phone on a ring grip, Mummy Eze's gele.
- **Cultural dress** (agbada, gele, ankara prints) appears for occasions and for Mummy Eze. Prints are simplified to 2–3 colour geometric patterns that remain readable when small.
- No real brand logos. Invented logos only.

## 8. Silhouette and recognisability

**Test:** fill every character solid black at thumbnail size (about 120 px tall). Each must still be identifiable.

| Character | Head shape | Silhouette signature | Height |
|---|---|---|---|
| Femi | Domino (tall rounded rectangle) | Round glasses rims stick out slightly; flat low-cut hair | 3.6 H, slim |
| Amara | Egg (wider at top) | Afro puff on top, hoop earrings | 3.3 H |
| Tunde | Circle | Bucket hat brim; wide stance | 3.2 H, stocky |
| Dez | Tall narrow oval | Tall flat-top hair; blazer shoulders | 3.8 H, lanky |
| Madam F | Soft square | Sharp bob, glasses chain loop | 3.2 H, upright |
| Zee | Heart (wide cheeks, narrow chin) | High braided ponytail that swings | 3.4 H |
| Mummy Eze | Round soft square | Tall gele headwrap (often taller than her head) | 3.0 H plus gele |
| Pepper (cat) | Bean | Upright tail with a kink | Small |

## 9. Text and typography

- **On-screen text** (labels, phone messages, time cards) is used sparingly and only when it is part of the joke.
- **Phone UI:** our own invented messaging app, "Natter": rounded bubbles, Teal for the sender and Canvas for the receiver, with typing dots. Never imitate a real messaging app's design.
- **Captions:** always on, one line, bottom-centred. The renderer lets us set our own caption font and size **(verified: `captionFont`, `captionSize` 20–64)**. Caption colours and stroke are fixed by the renderer's base mode (dark text with a light stroke), which suits our light sets.

**Font shortlist** (all free under the SIL Open Font License; download and approval needed later, **D15**):

| Use | Option A | Option B |
|---|---|---|
| Titles, time cards, labels | Baloo 2 (rounded, friendly) | Fredoka |
| Captions | Nunito (very readable) | Atkinson Hyperlegible |
| Phone messages | Nunito | Inter |

## 10. Backgrounds and environments

- **Flat colour-block sets:** walls, floors and furniture as flat shapes with light outlines. No paper texture, no grain, no gradients except soft window light.
- **Stage-set framing:** a consistent floor line at 72% of frame height in medium shots so pose sprites always stand on the same ground.
- **Three depth layers** per plate: back wall, mid furniture, and an optional foreground element (plant, chair back, desk edge) for parallax during pans.
- **Plates are oversized:** 3840×2160 per set angle, so the camera can pan and zoom up to 2× without losing sharpness.
- **Detail budget:** at most 8 meaningful props per plate. Props that are part of running jokes (the labelled leftovers in the fridge, the broken lift sign) are always present.
- Set details per location: see `WORLD_BIBLE.md`.

## 11. Lighting, shadows and effects

- **Lighting is flat by default.** Mood comes from tints, not rendered lighting.
- **Contact shadow:** every standing character has one soft ellipse shadow under the feet (Indigo at 15% opacity). No cast shadows.
- **Window light:** an optional soft diagonal light shape in daytime home sets.

**Mood tints** (full-frame overlays):

| Tint | Look | Use |
|---|---|---|
| **Doom Tint** (signature) | Indigo multiply at about 35% plus heavy vignette, background desaturated | "We need to talk", bills, the boss's "quick question" |
| Spotlight | Everything darkened except a circle on one character | Confession, being singled out |
| Flashback | Warm sepia with rounded-corner frame | Memories |
| Daydream | Soft pink-lavender with a cloud border | Fantasies, best-case imaginings |
| Worst-case | Desaturated grey with a jagged border | Catastrophising (Femi's imagination) |
| Alarm | Red edge pulse, 2 cycles | Panic, deadlines |

**Effect library (FX layers):** sweat drop (3 sizes), shock lines, speed lines, impact star, dust puff, steam from head, heart pop, question marks, exclamation marks, sparkle, tear streams, tiny storm cloud overhead, "!" ping above the head, swirl dizzy stars, and a "brain loading" spinner.

## 12. Differentiation from the repository's styles

| Repository style trait | Inkblock instead |
|---|---|
| White filled round heads with black stick limbs (A4, A5, B4) | Skin-toned heads in six distinct shapes, indigo lines |
| Pure black-on-white minimal line art (A1, B1) | Coloured garment blocks and flat colour sets |
| Crayon props on a faint grid (B1) | Clean vector props, no grid |
| Warm paper texture with ivory caption label (B2) | Flat colour, no texture |
| Dark field with TV bloom and scanlines (B3) | Light, bright sets |
| White gloves and half-shadow suspense (B4) | Lollipop hands, flat light |
| Bottom-right presenter with stage actors (B5) | Full-frame ensemble scenes, no presenter |
| Red beanie and yellow shirt mascot (A2) | No single mascot; a cast |
| Amber-and-plum noir (A6) | Bright daytime palette; tints only for gags |
| Prehistoric hides (A3) | Contemporary urban life |

## 13. Visual comedy techniques

The default toolkit, all achievable with pose swaps and keyframes:

| Technique | How it looks | When |
|---|---|---|
| **Brow lift-off** | Brows fly off and hover above the head, then drop back | Peak shock |
| **Doom Tint drop** | The frame darkens instantly on a line of dialogue | Dread trigger |
| **Freeze label** | Freeze frame plus a handwritten-style tag with an arrow naming the real thought ("Calculating escape routes") | Reveal inner state |
| **Smash cut** | Hard cut from confidence to disaster, with a sound sting | Contrast gags |
| **Reaction cut-in** | Extreme close-up of eyes or brows, 0.5–1 s | Micro-reactions |
| **Pepper cutaway** | Cut to the cat's unimpressed stare | Judgement beat |
| **Background drop** | Set vanishes into a flat colour with speed lines during a realisation | "Oh no" moments |
| **Scale cheat** | An object (bill, phone, text message) grows comically large | Emphasis |
| **Tally counter** | A corner counter tracking something ("Times he said 'fine': 7") | Running gags |
| **Imagination frame** | Daydream or worst-case bubble showing an imagined scene | Overthinking |
| **Hold** | Two characters stare in silence for 1–2 s | The awkward pause |
| **Sweat escalation** | The sweat drop grows each cut | Rising panic |
| **Prop callback** | An object from earlier reappears at the worst time | Payoffs |

## 14. Production art checklist (for future artwork)

When artwork begins (after approval), every character sheet must include:
- Front, three-quarter left, three-quarter right and profile views.
- The full eye, brow and mouth sets (§3), plus 6 visemes.
- Hand-shape library (§4).
- 12 core body poses (see `ANIMATION_DIRECTION.md` §4).
- A greyscale silhouette test at thumbnail size.
- A colour sheet with exact hex values.
- A side-by-side lineup with the rest of the cast at the same scale.

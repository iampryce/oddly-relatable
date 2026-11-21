"""The locked house style (owner decisions 2026-11-17): every character and every set in every episode is drawn in the
same style. Target look (owner's reference, a stickman couple-comedy reel): big round heads with big expressive eyes and
brows, simple flat hats or hair, natural skin tones, plain flat clothes, solid black stick limbs, no textures. Character
01's approved artwork is attached as the line-weight and eye-style reference. Characters are told apart by simple traits
(a hair shape, a hat, a clothing colour), never by extra detail.
"""

# Appended to every character image prompt by the server (owner decision 2026-11-21), whatever the Look says, so a
# drawn character can always be rigged: the acting rig needs both hands and the limbs as clear single lines.
RIG_RULES = ("Rig rules (always): arms and legs are SOLID BLACK single-line limbs; both hands clearly visible and never "
             "hidden; sleeveless clothing on the torso only (no sleeves covering the arms or hands); no pockets, and "
             "the hands are never in pockets.")

CHARACTER_RULES = (
    "HOUSE STYLE (strict): a cartoon stickman with a very large perfectly round head (about one third of the total height) "
    "and small round ears; big round expressive eyes with bold black outlines and black pupils, bold expressive brows, a "
    "simple expressive mouth (a line, a smile, or an open mouth that may show simple teeth); NO nose detail beyond at most "
    "a tiny simple curve, NO stubble, NO freckles, NO lipstick, NO earrings or jewellery; a natural skin tone with flat "
    "colour; hair or a hat drawn as ONE simple flat-coloured shape with a bold outline (no strands, no texture); arms and "
    "legs are SOLID BLACK single stick lines of bold even thickness, NEVER white or hollow outlined tubes and never "
    "skin-coloured; small black rounded mitten hands; ONE plain torso garment in a flat colour with at most a few bold "
    "outline details (no knit texture, no cable pattern, no drawstrings, no logos); simple rounded shoes in one flat colour. "
    "Bold clean black outlines of the same weight everywhere, flat colour fills, light simple shading.")

SET_STYLE = (
    "Background plate for a 2D cartoon comedy animation, vertical 2:3 composition, EMPTY of people and characters. "
    "Match the reference image's art style exactly: warm painted cartoon illustration, soft evening lighting, clean "
    "shapes, rich but gentle colours, cozy detail, slight storybook texture, eye-level camera. The lower third must be "
    "open, flat floor where cartoon characters will stand, with no furniture or objects blocking it. No text, no "
    "people, no animals, no characters.")

# Simplified descriptions for the restyle of the provisional trio: each keeps its recognisable traits only.
# The redraw keeps each character's own traits (taken from their current design) in the house style above.
RESTYLE_DESCRIPTIONS = {
    "leo": "Leo: light skin; messy brown hair drawn as one simple flat shape; a plain flat teal sleeveless vest top; simple "
           "white rounded shoes.",
    "ben": "Ben: light skin; a black baseball cap worn backwards with a few simple light-brown hair tufts; a plain flat "
           "purple hoodie with one front pocket; simple black rounded shoes.",
    "maya": "Maya: warm medium-brown skin; a dark-brown bob haircut drawn as one smooth flat shape; a plain flat "
            "mustard-yellow sleeveless top; simple brown rounded shoes.",
}

# ======================================================================================================================
# House style v2 (owner decision 2026-11-20), selected by Settings > creative.style_version = "v2". v1 above stays
# unchanged as the rollback. Target: minimal ADULT stick-figure comedy (white heads, solid black oval eyes, heavy angled
# brows, thin mouth line, one flat cap or hair shape, tall lanky proportions, black limbs with blob hands and feet) on
# cinematic painted sets with warm/cool light. Never a children's cartoon look.
STYLE_VERSIONS = ("v1", "v2")

_CHARACTER_RULES_V2 = (
    "HOUSE STYLE v2 (strict): an ADULT stick-figure comedy character drawn in a minimal, confident 2D line style for a "
    "grown-up audience. Proportions: tall and lanky with a LARGE head: the head is about 30% of the total height (between "
    "28% and 32%), about as tall as the torso; the torso about 30%; long legs about 40%; narrow shoulders; long arms that "
    "reach mid-thigh. Head: a plain slightly tall circle filled {head_fill} with a heavy black outline; NO ears, NO nose, NO "
    "cheeks, NO shading, NO stubble, NO freckles, NO make-up, NO jewellery. Eyes: two small SOLID BLACK vertical ovals with "
    "NO whites, NO outline and NO highlights, set wide apart at mid-head. Brows: two HEAVY thick black wedges, clearly "
    "angled to show the mood. Mouth: closed, a short thin black line (straight, wavy or slightly off-centre); shocked or "
    "surprised, a clearly OPEN solid black oval (an 'O' about as wide as one eye is tall); laughing or shouting, an open "
    "solid black D or oval shape; never teeth or tongue detail. Hair or headwear: ONE flat colour cap-like shape sitting on "
    "top of the head with a heavy outline (no strands, no texture), never covering the eyes. Torso: a plain {torso_fill} "
    "torso that clearly TAPERS, wider at the shoulders and narrower at the hips (a soft inverted trapezoid with rounded "
    "corners), with a heavy outline; or ONE plain adult garment (shirt, blazer, work polo) of that tapered shape in a single "
    "muted flat colour with no logos, pockets, drawstrings, prints or knit texture. Arms and legs: SOLID BLACK single lines "
    "of one even HEAVY weight, never hollow tubes and never skin-coloured. Hands: CHUNKY solid black rounded blobs (about as "
    "big as the gap between the eyes), with NO fingers drawn at all, never mittens or gloves. Feet: solid black elongated "
    "blobs, NO shoes. Line weight: HEAVY, confident black lines everywhere, about 1.2% of the total height thick (clearly "
    "bolder than a fine-line drawing), the same weight for outlines and limbs. Flat colours only, no gradients, no shading. "
    "Colours: black, {base_colour} and at most ONE muted accent colour (for example brick red, slate blue, olive, charcoal, "
    "camel or deep teal); no pastels, no neon. The look is understated and adult, NOT a children's cartoon: no big round "
    "eyes with whites, no baby proportions, no chubby or rounded body, no cute details.")

SET_STYLE_V2 = (
    "Background plate for an adult 2D animated comedy, vertical 2:3 composition, EMPTY of people and characters. A 2D "
    "PAINTED ILLUSTRATION: a hand-painted digital background for 2D animation, clearly stylised with simplified shapes and "
    "soft painted gradients. NOT photographic, NOT a photo, NOT a 3D render: no realistic reflections, no photo textures, "
    "no lens effects. NO outlines, NO brush or paper texture, NO storybook look. BRIGHT, readable mid-tones: the room is "
    "clearly visible everywhere, never murky, dark or underexposed. Muted, slightly desaturated palette with motivated "
    "lighting: warm interior lamp light against cool blue window or night light, a clear warm/cool contrast. Gentle depth: "
    "simple foreground shapes slightly soft, a clear mid-ground, a softer far background. Sparse, believable adult interior "
    "with only the furniture the setting needs; no clutter, no toys, no cute props, no posters with text. Camera at a "
    "standing adult's eye height with gentle perspective. The lower third must be open, flat floor where characters will "
    "stand, with no furniture or objects blocking it. No text, no people, no animals, no characters.")

RESTYLE_DESCRIPTIONS_V2 = {
    "leo": "Leo: a flat dark-brown short side-parted hair cap shape; plain white torso; no garment.",
    "ben": "Ben: a flat slate-blue flat-cap (newsboy cap) shape; plain white torso under a charcoal open blazer.",
    "maya": "Maya: a flat near-black chin-length bob hair cap shape with a side part; plain white torso under a brick-red "
            "collared shirt.",
}


def character_rules(version: str = "v1", skin_tone: str = "") -> str:
    """The character rules for a style version. v2 heads (and a bare torso) are flat WHITE, or the character's own flat
    skin tone when one is set (owner decision 2026-11-20: white by default, optional per-character skin tone)."""
    if version != "v2":
        return CHARACTER_RULES
    tone = (skin_tone or "").strip()
    if tone:
        fill = f"with a flat {tone} skin colour (no shading, no blush)"
        return _CHARACTER_RULES_V2.format(head_fill=fill, torso_fill=f"{tone} skin-coloured", base_colour=f"white, {tone}")
    return _CHARACTER_RULES_V2.format(head_fill="flat WHITE", torso_fill="WHITE", base_colour="white")


def set_style(version: str = "v1") -> str:
    return SET_STYLE_V2 if version == "v2" else SET_STYLE


def restyle_description(version: str, key: str) -> str | None:
    return (RESTYLE_DESCRIPTIONS_V2 if version == "v2" else RESTYLE_DESCRIPTIONS).get(key)

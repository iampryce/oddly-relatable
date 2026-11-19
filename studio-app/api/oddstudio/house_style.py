"""The locked house style (owner decisions 2026-11-17): every character and every set in every episode is drawn in the
same style. Target look (owner's reference, a stickman couple-comedy reel): big round heads with big expressive eyes and
brows, simple flat hats or hair, natural skin tones, plain flat clothes, solid black stick limbs, no textures. Character
01's approved artwork is attached as the line-weight and eye-style reference. Characters are told apart by simple traits
(a hair shape, a hat, a clothing colour), never by extra detail.
"""

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

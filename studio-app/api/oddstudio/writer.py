"""Prompts for the AI writer. The owner's idea drives every script; the house style (editable in Settings) carries the
channel's comedic direction. Every answer is validated with script_schema before it is saved."""
from __future__ import annotations

import json

from .script_schema import GESTURES, SHOTS, validate_script

SCRIPT_SHAPE = {
    "title": "short title", "logline": "one sentence", "hook": "2-5 word on-screen hook (optional)",
    "twist": "the unexpected turn", "interactive": {"type": "none | viewer-choice | poll", "question": "...", "options": ["A", "B"]},
    "characters": [{"key": "<an available character key, or the key of a new character below>", "role": "their part in this story"}],
    "new_characters": [{"key": "lowercase-key", "name": "Name", "description": "who they are and their comic role",
                        "visual_description": "head shape, hair, face, clothing colours, proportions, posture (distinct from the others)",
                        "bubble_style": "him | her | neutral", "voice_style": "how they sound: age, pace, tone"}],
    "scenes": [{"id": "s1", "heading": "short scene heading", "location": "<an environment id from the list, or empty>",
                "description": "what the scene shows", "action": "what the characters physically do (big, readable reactions)",
                "camera": "camera intent in plain words",
                "lines": [{"speaker": "<character key>", "text": "one short bubble line (max 140 chars)",
                           "expression": "<one word: neutral, happy, shocked, angry, worried, laughing, smug, scared...>",
                           "shot": " | ".join(SHOTS), "duration": 2.0, "delivery": "optional voice direction",
                           "gesture": "one of: " + ", ".join(g for g in GESTURES if g != "none"),
                           "move": {"type": "optional: enter | exit | walk_to | sit | stand | jump", "to": "seat | <character key>"},
                           "look_at": "<character key the speaker looks at>",
                           "reactions": [{"character": "<a listener's key>", "gesture": "...", "expression": "..."}]}]}],
}


def _cast_text(characters: list) -> str:
    rows = []
    for c in characters:
        exps = ", ".join(sorted(c.expressions)) or "(no poses yet: art must be generated before production)"
        rows.append(f'- key "{c.key}": {c.name}. {c.description} Expressions available: {exps}.')
    return "\n".join(rows)


def system_prompt(creative: dict) -> str:
    return ("You are the head writer of 'Oddly Relatable', an original animated stickman comedy channel for YouTube Shorts "
            "and TikTok. House style:\n" + creative["house_style"] + "\nNever use emoji in dialogue (the show's font cannot "
            "draw them; say it in words). You always answer with one JSON object only.")


def script_prompt(idea, characters: list, environments: list[str], instruction: str = "") -> str:
    inter = {"none": "Not interactive.", "viewer-choice": "End on a viewer choice: ask viewers to comment A or B for part 2.",
             "poll": "Include a 'guess what happens next / which one are you' question for viewers before the payoff."}[idea.interactive]
    wanted = ", ".join(idea.characters) if idea.characters else "choose from the available characters"
    return (f"Write an original short comedy script from the owner's idea.\n\nIDEA TITLE: {idea.title}\nIDEA: {idea.premise}\n"
            f"OWNER NOTES: {idea.notes or '(none)'}\nTARGET LENGTH: about {idea.target_seconds} seconds of dialogue and reaction beats. "
            f"A spoken bubble line takes about 3 seconds, so write roughly {max(4, round(idea.target_seconds / 3))} lines in total "
            f"(dialogue plus short reaction lines), developing each beat rather than padding.\n"
            + (f"OWNER INSTRUCTION FOR THIS VERSION: {instruction}\n" if instruction else "") +
            f"INTERACTIVITY: {inter}\nCHARACTERS TO USE: {wanted}\n\nAVAILABLE CHARACTERS:\n{_cast_text(characters)}\n\n"
            f"ENVIRONMENTS (location ids): {', '.join(environments)}\n\n"
            "Rules: 2-6 scenes; every line belongs to one speaker; short punchy bubbles; reaction beats as their own lines; "
            "escalate, then land the twist near the end. " + ACTING_RULES + " CAST: there is no fixed cast. Reuse an available character when they "
            "fit the story; otherwise introduce the characters this story needs in new_characters (at most 3), each visually "
            "distinct, with a clear visual_description and voice_style. Use simple one-word expressions.\n\n"
            "Return JSON shaped like:\n" + json.dumps(SCRIPT_SHAPE, indent=1))


def section_prompt(script: dict, section: str, instruction: str, characters: list) -> str:
    return (f"Here is the current script:\n{json.dumps(script, indent=1)}\n\nRewrite ONLY the section {section!r}"
            f" following this instruction from the owner: {instruction or 'make it funnier and tighter'}.\n"
            f"AVAILABLE CHARACTERS:\n{_cast_text(characters)}\n"
            + ("Return the complete scene object for that scene id, same shape as in the script."
               if section.startswith("scene:") else
               f'Return {{"{section}": <new value>}}.'))


def scene_prompt(script: dict, scene: dict, instruction: str, characters: list) -> str:
    return (f"Script for context:\n{json.dumps(script, indent=1)}\n\nStoryboard scene to revise:\n{json.dumps(scene, indent=1)}\n\n"
            f"Owner's instruction: {instruction or 'improve the comedic timing and reactions'}\n"
            f"AVAILABLE CHARACTERS:\n{_cast_text(characters)}\n"
            "Return the revised scene as JSON with keys heading, location, description, action, camera, lines "
            "(same line shape as the script).")


def apply_section(script: dict, section: str, answer: dict, known: set[str], fmt: str = "short") -> dict:
    new = json.loads(json.dumps(script))
    if section.startswith("scene:"):
        sid = section.split(":", 1)[1]
        scene = answer.get("scene", answer)
        idx = next((i for i, s in enumerate(new["scenes"]) if s["id"] == sid), None)
        if idx is None:
            raise ValueError(f"no scene {sid!r} in the script")
        scene["id"] = sid
        if "act" in new["scenes"][idx]:
            scene["act"] = new["scenes"][idx]["act"]   # a long episode's scene stays in its act
        new["scenes"][idx] = scene
    elif section in ("title", "logline", "hook", "twist", "interactive"):
        if section not in answer:
            raise ValueError(f"the writer did not return {section!r}")
        new[section] = answer[section]
    else:
        raise ValueError("section must be title, logline, hook, twist, interactive, scene:<id> or (long episodes) act:<1-3>")
    return validate_script(new, known, fmt=fmt)


# ------------------------------------------------------------------ long-form (D-L1 to D-L5)
OUTLINE_SHAPE = {
    "title": "...", "logline": "one sentence", "premise": "the situation", "twist": "the turn", "ending": "how it lands",
    "quality_notes": "why this story needs its length: the distinct developments that justify each act",
    "characters": [{"key": "<available key or a new character's key>", "role": "..."}],
    "new_characters": [{"key": "lowercase-key", "name": "...", "description": "...", "visual_description": "...",
                        "bubble_style": "him | her | neutral", "voice_style": "..."}],
    "acts": [{"title": "...", "purpose": "what this act must achieve",
              "scenes": [{"id": "a1s1", "heading": "...", "summary": "what happens", "beats": ["each development or escalation"],
                          "jokes": ["the distinct jokes or comic beats in this scene"], "characters": ["keys on screen (max 4)"],
                          "location": "<environment id or empty>", "est_seconds": 15}]}],
}

ACTING_RULES = (
    "ACTING: the characters are animated actors, not still pictures. Give most lines a body gesture (gesture), and use "
    "movement (move) where the story calls for it: characters enter and exit, walk over to someone, sit down on the seat "
    "and stand up, jump in shock. Give listeners visible reactions (reactions) on the lines that hit them. Choose big, "
    "readable, comic body language; vary it (do not repeat one gesture line after line).")

QUALITY_RULES = (
    "Story quality comes before duration. The target is 5 to 7 minutes, but never pad: no filler scenes, no repeated jokes, "
    "no recap of what the audience has seen, no stalling dialogue. Every scene must change something (a new development, an "
    "escalation, a reveal or a payoff). If the idea honestly supports less than five minutes, write the shorter story and say "
    "so in quality_notes; the owner decides. Never exceed 7 minutes 30 seconds.")


def outline_prompt(idea, characters: list, environments: list[str], continues: dict | None = None) -> str:
    cont = ""
    if continues:
        cont = ("\nTHIS EPISODE CONTINUES A SHORT (D-L5). The Short's script follows; continue its story (for an interactive "
                "Short, the winning choice is given in the owner notes), keep its characters consistent, and make this "
                f"episode stand on its own for new viewers:\n{json.dumps(continues, indent=1)}\n")
    return (f"Write a THREE-ACT OUTLINE (not the dialogue yet) for an original long episode.\n\nIDEA TITLE: {idea.title}\n"
            f"IDEA: {idea.premise}\nOWNER NOTES: {idea.notes or '(none)'}\n{cont}\n"
            f"AVAILABLE CHARACTERS:\n{_cast_text(characters)}\n\nENVIRONMENTS (location ids): {', '.join(environments)}\n\n"
            f"RULES: exactly 3 acts (setup, escalation, payoff with the twist); 15 to 40 scenes in total; scenes are short "
            f"(usually 8 to 20 seconds); at most 4 characters on screen in a scene; est_seconds per scene honestly estimated "
            f"from its beats. {QUALITY_RULES} There is no fixed cast: reuse available characters when they fit, otherwise "
            f"introduce the characters the story needs in new_characters.\n\nReturn JSON shaped like:\n" + json.dumps(OUTLINE_SHAPE, indent=1))


def act_prompt(outline: dict, act: int, written: list[dict], characters: list) -> str:
    """Develop one act's scenes into full dialogue, consistent with the approved outline and the acts already written."""
    plan = outline["acts"][act - 1]
    targets = ", ".join("%s ≈%.0fs" % (s["id"], s["est_seconds"]) for s in plan["scenes"])
    return (f"Here is the APPROVED three-act outline:\n{json.dumps(outline, indent=1)}\n\n"
            + (f"Acts already written (keep characters, running gags and tone consistent; do not repeat their jokes):\n"
               f"{json.dumps(written, indent=1)}\n\n" if written else "")
            + f"Write ACT {act} ({plan['title']}) now: one script scene for each outline scene of this act, with the SAME ids, "
            f"in order. Follow the outline's beats and jokes; dialogue is short (one-sentence bubbles), with reaction beats as "
            f"their own lines. PLAY EVERY BEAT: each outline beat and joke becomes its own exchange on screen (setup, reaction, "
            f"payoff), so a scene runs about its est_seconds (a spoken bubble line takes about 2.5 to 3.5 seconds; scene "
            f"targets: {targets}). Reach that length only by "
            f"developing the planned beats, never by repeating a joke, recapping or stalling; a beat that is done is done. "
            f"{QUALITY_RULES} {ACTING_RULES}\nAVAILABLE CHARACTERS:\n{_cast_text(characters)}\n"
            "Return JSON: {\"scenes\": [{\"id\": \"<outline scene id>\", \"heading\": \"...\", \"location\": \"...\", "
            "\"description\": \"...\", \"action\": \"...\", \"camera\": \"...\", \"lines\": [{\"speaker\": \"<key>\", \"text\": \"...\", "
            "\"expression\": \"<one word>\", \"shot\": \"wide|medium|close\", \"delivery\": \"optional\", "
            "\"gesture\": \"" + "|".join(g for g in GESTURES if g != "none") + "\", "
            "\"move\": {\"type\": \"enter|exit|walk_to|sit|stand|jump\", \"to\": \"seat|<key>\"} (optional), "
            "\"look_at\": \"<key>\", \"reactions\": [{\"character\": \"<key>\", \"gesture\": \"...\", \"expression\": \"...\"}]}]}]}")

"""Prompts for the AI writer. The owner's idea drives every script; the house style (editable in Settings) carries the
channel's comedic direction. Every answer is validated with script_schema before it is saved."""
from __future__ import annotations

import json

from .script_schema import SHOTS, validate_script

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
                           "shot": " | ".join(SHOTS), "duration": 2.0, "delivery": "optional voice direction"}]}],
}


def _cast_text(characters: list) -> str:
    rows = []
    for c in characters:
        exps = ", ".join(sorted(c.expressions)) or "(no poses yet: art must be generated before production)"
        rows.append(f'- key "{c.key}": {c.name}. {c.description} Expressions available: {exps}.')
    return "\n".join(rows)


def system_prompt(creative: dict) -> str:
    return ("You are the head writer of 'Oddly Relatable', an original animated stickman comedy channel for YouTube Shorts "
            "and TikTok. House style:\n" + creative["house_style"] + "\nYou always answer with one JSON object only.")


def script_prompt(idea, characters: list, environments: list[str]) -> str:
    inter = {"none": "Not interactive.", "viewer-choice": "End on a viewer choice: ask viewers to comment A or B for part 2.",
             "poll": "Include a 'guess what happens next / which one are you' question for viewers before the payoff."}[idea.interactive]
    wanted = ", ".join(idea.characters) if idea.characters else "choose from the available characters"
    return (f"Write an original short comedy script from the owner's idea.\n\nIDEA TITLE: {idea.title}\nIDEA: {idea.premise}\n"
            f"OWNER NOTES: {idea.notes or '(none)'}\nTARGET LENGTH: about {idea.target_seconds} seconds of dialogue and reaction beats.\n"
            f"INTERACTIVITY: {inter}\nCHARACTERS TO USE: {wanted}\n\nAVAILABLE CHARACTERS:\n{_cast_text(characters)}\n\n"
            f"ENVIRONMENTS (location ids): {', '.join(environments)}\n\n"
            "Rules: 2-6 scenes; every line belongs to one speaker; short punchy bubbles; reaction beats as their own lines; "
            "escalate, then land the twist near the end. CAST: there is no fixed cast. Reuse an available character when they "
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


def apply_section(script: dict, section: str, answer: dict, known: set[str]) -> dict:
    new = json.loads(json.dumps(script))
    if section.startswith("scene:"):
        sid = section.split(":", 1)[1]
        scene = answer.get("scene", answer)
        idx = next((i for i, s in enumerate(new["scenes"]) if s["id"] == sid), None)
        if idx is None:
            raise ValueError(f"no scene {sid!r} in the script")
        scene["id"] = sid
        new["scenes"][idx] = scene
    elif section in ("title", "logline", "hook", "twist", "interactive"):
        if section not in answer:
            raise ValueError(f"the writer did not return {section!r}")
        new[section] = answer[section]
    else:
        raise ValueError("section must be title, logline, hook, twist, interactive or scene:<id>")
    return validate_script(new, known)

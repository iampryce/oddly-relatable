"""Bible passages for cinematic episodes: public-domain translations only (owner rule 2026-11-27: "never paste a
copyrighted translation").

What is allowed:
  * a passage REFERENCE ("Daniel 3:1-30", "1 Samuel 17") checked against the 66 books of the Protestant canon;
  * the passage TEXT only from a public-domain English translation: KJV (King James Version, 1769 text; public domain
    outside the UK, where a Crown patent applies), ASV (American Standard Version, 1901) or WEB (World English Bible,
    dedicated to the public domain). The studio never fetches scripture itself; the owner pastes the text and names the
    translation.

The guard (check_text) is deliberately strict and only says three things:
  * "refused": the translation named is not one of the public-domain ones, or the text carries a copyright notice or
    the name / abbreviation of a copyrighted translation (NIV, ESV, NLT, NKJV, NASB, CSB, MSG, AMP ...). Nothing is
    saved and nothing is sent to a model.
  * "flagged": the text does not look like the translation named (e.g. called KJV but has none of the KJV's archaic
    forms). It can be used only after the owner confirms where it was copied from (confirm_public_domain=true); the
    confirmation is saved with the episode.
  * "ok": the translation is public domain and nothing suspicious was found.
A heuristic cannot prove where a text came from: the owner's confirmation is the record, the guard catches the common
mistakes (pasting from a site's default NIV/ESV view, or a copyright line copied along with the verses).
"""
from __future__ import annotations

import re

PUBLIC_DOMAIN = {
    "KJV": "King James Version (1769 text; public domain outside the UK)",
    "ASV": "American Standard Version (1901, public domain)",
    "WEB": "World English Bible (public domain)",
}
ALIASES = {"KING JAMES": "KJV", "KING JAMES VERSION": "KJV", "AV": "KJV", "AUTHORIZED VERSION": "KJV",
           "AMERICAN STANDARD VERSION": "ASV", "WORLD ENGLISH BIBLE": "WEB"}

# Copyrighted English translations (names and abbreviations) and copyright wording: any of these refuses the text.
COPYRIGHTED = ("NIV", "NIRV", "TNIV", "ESV", "NLT", "NKJV", "NASB", "NASB1995", "NASB2020", "LSB", "CSB", "HCSB", "MSG",
               "AMP", "AMPC", "NRSV", "NRSVUE", "RSV", "NET", "NCV", "CEV", "GNT", "GNB", "TLB", "TPT", "ERV", "ICB", "NABRE",
               "NAB", "NJB", "JB", "CJB", "ISV", "LEB", "NOG", "EHV", "BSB", "MEV", "GW", "NLV", "VOICE", "PHILLIPS")
COPYRIGHT_WORDS = re.compile(
    r"(©|\(c\)\s*\d{4}|\bcopyright\b|\ball rights reserved\b|\bused by permission\b|\bbiblica\b|\bzondervan\b|"
    r"\bcrossway\b|\btyndale house\b|\blockman\b|\bholman\b|\bthomas nelson\b|\bnavpress\b|\bthe message\b|"
    r"\bnew international version\b|\benglish standard version\b|\bnew living translation\b|\bnew king james\b|"
    r"\bnew american standard\b|\bchristian standard bible\b|\bamplified bible\b|\bnew revised standard\b|"
    r"\brevised standard version\b|\bgood news translation\b|\bpassion translation\b|\bliving bible\b)", re.I)
ABBREV = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted(COPYRIGHTED, key=len, reverse=True)) + r")(?![A-Za-z])")

# forms the KJV uses all the time and modern translations do not (a passage of 25+ words has at least two)
KJV_MARKERS = re.compile(r"\b(thee|thou|thy|thine|ye|hath|hast|doth|dost|saith|unto|shalt|wilt|cometh|goeth|spake|"
                         r"begat|verily|knoweth|maketh|giveth|taketh|sayeth|didst|wast|wherefore|thereof|whosoever)\b", re.I)
MODERN_MARKERS = re.compile(r"\b(you're|don't|won't|can't|isn't|it's|okay|ok|gonna|wanna)\b", re.I)

BOOKS = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges", "Ruth", "1 Samuel", "2 Samuel",
         "1 Kings", "2 Kings", "1 Chronicles", "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
         "Ecclesiastes", "Song of Solomon", "Isaiah", "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel",
         "Amos", "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah", "Haggai", "Zechariah", "Malachi",
         "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians",
         "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy", "Titus", "Philemon",
         "Hebrews", "James", "1 Peter", "2 Peter", "1 John", "2 John", "3 John", "Jude", "Revelation"]
BOOK_ALIASES = {"psalm": "Psalms", "song of songs": "Song of Solomon", "revelations": "Revelation",
                "canticles": "Song of Solomon"}
REF = re.compile(r"^\s*((?:[123]|i{1,3})\s*)?([A-Za-z][A-Za-z ]*?)\s+(\d{1,3})(?::(\d{1,3})(?:\s*[-–]\s*(?:(\d{1,3}):)?(\d{1,3}))?)?\s*$")
MAX_TEXT = 20000


def normalise_translation(name: str | None) -> str:
    n = re.sub(r"\s+", " ", str(name or "")).strip().upper()
    return ALIASES.get(n, n)


def parse_reference(ref: str) -> dict:
    """"Daniel 3:1-30" -> {book, chapter, verse_from, verse_to, chapter_to, text}; ValueError in plain words."""
    m = REF.match(str(ref or ""))
    if not m:
        raise ValueError("write the passage like \"Daniel 3:1-30\" or \"1 Samuel 17\"")
    num, name, ch, v1, ch2, v2 = m.groups()
    num = (num or "").strip().lower()
    num = {"i": "1", "ii": "2", "iii": "3"}.get(num, num)
    key = f"{num} {name.strip()}".strip().lower()
    book = next((b for b in BOOKS if b.lower() == key), None) or BOOK_ALIASES.get(key)
    if book is None:
        raise ValueError(f"\"{(num + ' ' + name).strip()}\" is not a book of the Bible (use its full English name, e.g. 1 Samuel)")
    out = {"book": book, "chapter": int(ch), "verse_from": int(v1) if v1 else None,
           "chapter_to": int(ch2) if ch2 else None, "verse_to": int(v2) if v2 else None}
    if out["chapter"] < 1 or (out["verse_from"] is not None and out["verse_from"] < 1):
        raise ValueError("chapters and verses start at 1")
    if out["chapter_to"] and out["chapter_to"] < out["chapter"]:
        raise ValueError("the passage must end after it starts")
    if out["verse_to"] and not out["chapter_to"] and out["verse_from"] and out["verse_to"] < out["verse_from"]:
        raise ValueError("the passage must end after it starts")
    text = f"{book} {out['chapter']}"
    if out["verse_from"]:
        text += f":{out['verse_from']}"
        if out["verse_to"]:
            text += "-" + (f"{out['chapter_to']}:" if out["chapter_to"] else "") + str(out["verse_to"])
    out["text"] = text
    return out


def check_text(text: str, translation: str) -> dict:
    """{status: ok | flagged | refused, translation, label, reasons: [...]} for pasted scripture text."""
    t = normalise_translation(translation)
    body = str(text or "")
    reasons: list[str] = []
    if t not in PUBLIC_DOMAIN:
        return {"status": "refused", "translation": t, "label": "",
                "reasons": [f"\"{translation}\" is not one of the public-domain translations the studio may use "
                            f"({', '.join(PUBLIC_DOMAIN)}): copyrighted translations are never used"]}
    if len(body) > MAX_TEXT:
        return {"status": "refused", "translation": t, "label": PUBLIC_DOMAIN[t],
                "reasons": [f"the text is longer than {MAX_TEXT} characters: paste only the passage you need"]}
    m = COPYRIGHT_WORDS.search(body)
    if m:
        reasons.append(f"the text contains \"{m.group(0)}\", which belongs to a copyrighted translation or its notice")
    m = ABBREV.search(body)
    if m:
        reasons.append(f"the text names \"{m.group(1)}\", a copyrighted translation")
    if reasons:
        return {"status": "refused", "translation": t, "label": PUBLIC_DOMAIN[t],
                "reasons": reasons + ["paste the passage from a KJV, ASV or WEB source instead"]}
    words = re.findall(r"[A-Za-z']+", body)
    if t == "KJV" and len(words) >= 25:
        archaic = len(KJV_MARKERS.findall(body))
        if archaic < 2 or MODERN_MARKERS.search(body):
            reasons.append("this does not read like the King James Version (no \"thee\", \"thou\", \"hath\", \"unto\" ... "
                           "or modern contractions): it may be a copyrighted modern translation")
    if t in ("WEB", "ASV") and len(words) >= 25 and MODERN_MARKERS.search(body):
        reasons.append(f"this has modern contractions, which the {t} does not use: it may be another translation")
    if reasons:
        return {"status": "flagged", "translation": t, "label": PUBLIC_DOMAIN[t],
                "reasons": reasons + ["confirm that you copied it from a public-domain " + t + " source to use it"]}
    return {"status": "ok", "translation": t, "label": PUBLIC_DOMAIN[t], "reasons": []}

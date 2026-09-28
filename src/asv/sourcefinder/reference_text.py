"""Repair reference strings before they reach a parser — SOURCE_ACQUISITION.md F8.

PDF text extraction drops the spaces at reference field boundaries and mangles
the punctuation. Straight from ``runs/*/text_sources/_manifest.json``::

    Burton EA, Fink DJ, Glorioso JC.Gene delivery using herpes simplex virus
    vectors.DNA Cell Biol2002;21: 915�936.

Both the LLM parser and Crossref's ``query.bibliographic`` receive that. The
title runs into the journal, the journal runs into the year, and the page range
contains a replacement character where an en-dash used to be. Every downstream
match is scored against corrupted input, and ``citation_details.doi`` is null
for all 51 entries in the measured run.

Nothing here is clever. It is a small set of boundary rules applied to a query
string, chosen so that the failure mode is "no change" rather than "different
corruption":

* DOIs and URLs are masked out first, because every rule below would damage one.
* A space is inserted at a lowercase->uppercase boundary only when the lowercase
  run is long enough to be a word — otherwise ``McGraw-Hill`` becomes
  ``Mc Graw-Hill``.
* ``�`` is guessed from its neighbours (apostrophe between letters, dash
  between digits) because the original bytes are already gone; anywhere else it
  is dropped rather than guessed at.
"""

from __future__ import annotations

import re
from typing import List, Tuple

__all__ = ["normalise_reference", "fix_mojibake"]


# Text that was UTF-8, read as cp1252, and re-encoded. Ordered longest-first so
# a three-byte sequence is not half-consumed by a two-byte rule.
_MOJIBAKE = [
    ("â€™", "'"),   # â€™  right single quote
    ("â€˜", "'"),   # â€˜  left single quote
    ("â€\u009c", '"'),   # â€œ  left double quote
    ("â€\u009d", '"'),   # â€  right double quote
    ("â€”", "-"),   # â€"  em dash
    ("â€–", "-"),   # â€"  en dash
    ("â€¦", "..."),  # â€¦  ellipsis
    ("Â ", " "),          # Â    stray nbsp
    ("â€", '"'),
]

# Typographic characters that confuse exact-match APIs.
_TYPOGRAPHIC = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
}

_DOI_OR_URL = re.compile(
    r"(https?://\S+|\b10\.\d{4,}/[^\s,;\]\)]+)", re.IGNORECASE
)

# A lowercase run this long before a capital is a word that lost its space.
# "Mc" (1) and "De" (1) stay intact; "virus" (5) and "Biol" do not.
_MIN_WORD_RUN = 3

_LOWER_UPPER = re.compile(r"([a-z]{%d,})([A-Z])" % _MIN_WORD_RUN)
_LETTER_YEAR = re.compile(r"([A-Za-z])((?:18|19|20)\d{2}\b)")
# "vectors.DNA Cell Biol" needs the all-caps case; two adjacent capitals cannot
# be an author initial, which is always a single letter before its dot. The
# third alternative catches an abbreviated journal that lost its space
# ("replication.J Virol") — splitting an initial that was already spaced
# correctly is harmless, running a journal name into a sentence is not.
_DOT_UPPER = re.compile(r"\.([A-Z][a-z]|[A-Z]{2,}|[A-Z](?=\s))")
_DOT_DIGIT_YEAR = re.compile(r"\.((?:18|19|20)\d{2}\b)")
_MULTISPACE = re.compile(r"[ \t]{2,}")


def fix_mojibake(text: str) -> str:
    """Undo UTF-8-read-as-cp1252 damage and flatten typographic punctuation."""
    if not text:
        return ""
    for bad, good in _MOJIBAKE:
        if bad in text:
            text = text.replace(bad, good)
    for bad, good in _TYPOGRAPHIC.items():
        if bad in text:
            text = text.replace(bad, good)
    return text


def _repair_replacement_chars(text: str) -> str:
    """Guess what a U+FFFD used to be from what surrounds it.

    Only two guesses are safe enough to make: between letters it was almost
    always an apostrophe (``Harrison�s``), and between digits an en-dash in
    a page range (``915�936``). Everywhere else the character is dropped,
    because a wrong guess inside a title is worse for matching than a gap.
    """
    if "�" not in text:
        return text
    text = re.sub(r"(?<=[A-Za-z])�(?=[A-Za-z])", "'", text)
    text = re.sub(r"(?<=\d)�(?=\d)", "-", text)
    return text.replace("�", "")


def _mask_identifiers(text: str) -> Tuple[str, List[str]]:
    """Replace DOIs and URLs with placeholders the spacing rules cannot touch."""
    held: List[str] = []

    def _hold(m: re.Match) -> str:
        held.append(m.group(0))
        return "\x00%d\x00" % (len(held) - 1)

    return _DOI_OR_URL.sub(_hold, text), held


def _unmask_identifiers(text: str, held: List[str]) -> str:
    for i, original in enumerate(held):
        text = text.replace("\x00%d\x00" % i, original)
    return text


def normalise_reference(text: str) -> str:
    """Return *text* with the PDF-extraction damage undone, as far as is safe.

    Idempotent, and a no-op on strings that were extracted cleanly.
    """
    if not text:
        return ""
    text = fix_mojibake(text)
    text = _repair_replacement_chars(text)

    masked, held = _mask_identifiers(text)

    # "vectors.DNA Cell Biol" -> "vectors. DNA Cell Biol"
    masked = _DOT_UPPER.sub(lambda m: ". " + m.group(1), masked)
    # "Medicine.McGraw-Hill, 1980" keeps its capital run, but "...Hill.1980" gains a space.
    masked = _DOT_DIGIT_YEAR.sub(lambda m: ". " + m.group(1), masked)
    # "virusIn:" -> "virus In:"  (but not "McGraw")
    masked = _LOWER_UPPER.sub(lambda m: m.group(1) + " " + m.group(2), masked)
    # "DNA Cell Biol2002" -> "DNA Cell Biol 2002"
    masked = _LETTER_YEAR.sub(lambda m: m.group(1) + " " + m.group(2), masked)

    text = _unmask_identifiers(masked, held)
    return _MULTISPACE.sub(" ", text).strip()

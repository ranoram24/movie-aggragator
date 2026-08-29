"""Title normalisation shared by the matcher and the API.

Deliberately free of third-party imports. The API server needs normalize_title
to group listings onto one card, and importing it from match_movies dragged in
rapidfuzz, requests, dotenv and TMDb token loading -- so the web process could
not start without the whole matching stack installed.

Everything here is pure text handling: strip the decoration the chains bolt
onto a title, and split a multi-language title into its parts.
"""

import re


# Language/format markers that trail a title. The separator varies by chain:
# Cinema City writes "-מדובב", Movieland "(מדובב)", Hot Cinema " מדובב לעברית".
# All three are the same film, so all three have to normalize identically or the
# same movie shows up as several separate cards.
DUB_WORDS = r"(?:מדובב(?:ת)?|אנגלית|דובר(?:ת)?\s+עברית|مدبلج[^\s]*)"
DUB_SUFFIX_RE = re.compile(rf"[\s\-–—]*\(?\s*{DUB_WORDS}(?:\s+ל?\S+)?\s*\)?\s*$")

# Programming strands the cinemas prepend to an ordinary film, e.g.
# "סינמה נוסטלגיה - פלונטר" is just פלונטר shown in a retro season.
STRAND_PREFIX_RE = re.compile(r"^\s*(?:סינמה נוסטלגיה|קלאסיקה|מועדון[^-–]{0,20})\s*[-–]\s*")

# Trailing event blurbs, e.g. "לה לה לנד-חגיגות העשור".
EVENT_SUFFIX_RE = re.compile(r"\s*[-–]\s*(?:חגיגות[^-–]*|הקרנה מיוחדת|שיח יוצרים.*)\s*$")

# A bare language word with no "מדובב" in front, as Hot Cinema sometimes writes
# it: "מפרץ ההרפתקאות: אי הדינוזאורים רוסית".
BARE_LANGUAGE_RE = re.compile(r"\s+(?:רוסית|צרפתית|ספרדית|ערבית)\s*$")

# Format descriptors the chains bolt onto a title. "מואנה לייב אקשן" is the
# same film TMDb simply calls "Moana" -- leaving the words in stops it matching
# and gives the live-action version its own card on every chain that says it.
FORMAT_WORDS_RE = re.compile(
    r"\s*[\(\[]?\s*(?:לייב[\s\-]?אקשן|live[\s\-]?action|גרסת הבמאי|"
    r"director'?s cut|תלת[\s\-]?מימד|3D|IMAX)\s*[\)\]]?\s*",
    re.I,
)

# Which script a chunk of a title is written in. Russian-dubbed screenings are
# listed under a Russian title -- sometimes only a Russian title -- and searching
# TMDb for Cyrillic while asking for Hebrew results finds nothing, which is why
# every Russian version used to become its own card.
SCRIPTS = [
    ("he", re.compile(r"[֐-׿]"), "he-IL"),
    ("ru", re.compile(r"[Ѐ-ӿ]"), "ru-RU"),
    ("ar", re.compile(r"[؀-ۿ]"), "ar-SA"),
    ("en", re.compile(r"[A-Za-z]"), "en-US"),
]


def _strip_decoration(title: str) -> str:
    """Remove trailing dub/format/event markers, repeatedly (they stack)."""
    previous = None
    while previous != title:
        previous = title
        title = DUB_SUFFIX_RE.sub("", title)
        title = EVENT_SUFFIX_RE.sub("", title)
        title = BARE_LANGUAGE_RE.sub("", title)
        title = FORMAT_WORDS_RE.sub(" ", title)
        # A trailing full stop is chain punctuation, not part of the name:
        # Cinema City and Lev write "ההזמנה." while Planet and Hot Cinema write
        # "ההזמנה", which is enough to send them to two different TMDb entries
        # and split one film across two cards. "?" and "!" are left alone --
        # those do belong to titles.
        title = re.sub(r"\s*\.+\s*$", "", title)
        title = " ".join(title.split())
    return title.strip(" -–—:")


def title_segments(title: str) -> list[tuple[str, str]]:
    """Split a title into (text, tmdb_language) parts, one per script.

    Chains often publish several languages in one string, e.g.
    "ספיידרמן: יום חדש מדובב לרוסית - ЧЕЛОВЕК-ПАУК" or
    "ЧЕЛОВЕК-ПАУК: НОВЫЙ ДЕНЬ - Spider-Man". Each part is a usable query in its
    own language, and any one of them matching is enough to merge the listing
    into the right film.
    """
    segments: list[tuple[str, str]] = []
    for chunk in re.split(r"\s+[-–—]\s+", title):
        chunk = chunk.strip(" -–—:")
        if len(chunk) < 2:
            continue
        for _, pattern, tmdb_lang in SCRIPTS:
            if pattern.search(chunk):
                # Drop characters from the other scripts so the query is clean.
                others = [p for name, p, _ in SCRIPTS if p is not pattern]
                text = chunk
                for other in others:
                    text = other.sub("", text)
                text = " ".join(text.split()).strip(" -–—:")
                # Re-run the suffix strippers: a marker that was mid-title is
                # now trailing, e.g. "טורבו מדובב לערבית توربو" -> "טורבו".
                text = _strip_decoration(text)
                if len(text) >= 2:
                    segments.append((text, tmdb_lang))
    # Preserve order, drop duplicates.
    seen, out = set(), []
    for item in segments:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_title(title: str) -> str:
    """Strip chain-specific decoration so the same film matches across all five.

    Applied repeatedly because the markers stack -- Hot Cinema produces titles
    like "סינמה נוסטלגיה - מלך האריות 1994 מדובב לעברית", which needs a prefix
    and a suffix removed before TMDb has any chance of matching it.
    """
    return _strip_decoration(STRAND_PREFIX_RE.sub("", title))


def fold_for_compare(text: str | None) -> str:
    """Case- and punctuation-folded form used only for scoring.

    Applied to the candidate as well as the query: TMDb's 2026 "ההזמנה." keeps
    its full stop, so stripping it from only our side still scored the correct
    film below a same-named 2016 entry.
    """
    if not text:
        return ""
    return re.sub(r"\s*\.+\s*$", "", text.strip()).lower()

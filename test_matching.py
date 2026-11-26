"""Tests for title normalisation and for the stale-match check.

    python test_matching.py

Both halves exist because of two wrong cards that reached production, and the
cases below are those cards:

  * A card titled "טרום בכורה" — the words for "preview screening" — carrying
    three unrelated Lev films and a fourth film's poster.
  * A card titled "ויהי גשם" showing the Hunger Games poster, with four
    chains' Hunger Games listings on it, while the one correctly matched
    Hunger Games listing sat alone on a card of its own.

Neither was a scraping failure. Both were the matcher being confidently wrong
and nothing afterwards being able to disagree with it.
"""

import sys

from match_movies import (
    ADOPTED_MATCH_FLOOR,
    TITLE_MATCH_FLOOR,
    _agreement,
)
from api_movies import overview_rank
from titles import (hebrew_fraction, normalize_title, shares_script,
                    title_segments)

passed = 0
failures: list[str] = []


def check(label: str, condition: bool) -> None:
    global passed
    if condition:
        passed += 1
    else:
        failures.append(label)


def eq(label: str, actual, expected) -> None:
    global passed
    if actual == expected:
        passed += 1
    else:
        failures.append(f"{label}\n    expected {expected!r}\n    actual   {actual!r}")


class FakeMovie:
    def __init__(self, title_he, title_en=None):
        self.title_he = title_he
        self.title_en = title_en


# ---------------------------------------------------------------- prefixes

# Why this matters, and it is not obvious: title_segments splits a title on
# " - " so a bilingual listing can be searched in each language, and the
# matcher queries those segments in order. A leading "טרום בכורה" was
# therefore searched BEFORE the film's own name — and TMDb has an entry
# titled exactly that, so it matched at 100 and the real title was never
# tried. Stripping the prefix means it never becomes a segment at all.
eq("preview prefix with a dash is stripped",
   normalize_title("טרום בכורה - כבשה בקופסה"), "כבשה בקופסה")
eq("preview prefix with a colon is stripped",
   normalize_title("טרום בכורה: הבית על שפת האגם"), "הבית על שפת האגם")
eq("and with an apostrophe in the film name",
   normalize_title("טרום בכורה - הכישרון של גברת הייסמית'"),
   "הכישרון של גברת הייסמית'")
eq("an early-screening prefix too",
   normalize_title("הקרנה מוקדמת - וושינגטון הצעיר"), "וושינגטון הצעיר")
eq("the existing strand prefixes still work",
   normalize_title("סינמה נוסטלגיה - פלונטר"), "פלונטר")

# The guard that matters most: a colon inside a real title is NOT a prefix.
eq("a real title with a colon is left alone",
   normalize_title("משחקי הרעב: זריחה על האסיף"), "משחקי הרעב: זריחה על האסיף")
eq("and another", normalize_title("לוני טונס מציגים: קיוטי נגד אקמי"),
   "לוני טונס מציגים: קיוטי נגד אקמי")

# Once stripped there is one segment, so there is no short label to search.
for raw in ["טרום בכורה - כבשה בקופסה", "טרום בכורה - הבית על שפת האגם"]:
    segments = [q for q, _ in title_segments(normalize_title(raw))]
    eq(f"one segment left for {raw[:24]}", len(segments), 1)
    check(f"and it is not the label for {raw[:24]}",
          segments[0] != "טרום בכורה")


# ---------------------------------------------------------------- stale matches

HUNGER = "משחקי הרעב: זריחה על האסיף"

# (listing title, linked film, was it a title match, should it be unlinked)
CASES = [
    # The two production failures. TMDb is user-edited: entry 1324241 was once
    # labelled as the new Hunger Games and later corrected to "Regnmannen",
    # silently leaving every listing that matched it pointing at a Norwegian
    # film. Nothing re-checked the link, so it was permanent.
    (HUNGER, FakeMovie("ויהי גשם", "Regnmannen"), True, True),
    (HUNGER, FakeMovie("ויהי גשם", "Regnmannen"), False, True),
    ("וושינגטון הצעיר", FakeMovie("טרום בכורה", "טרום בכורה"), True, True),
    ("טרום בכורה - כבשה בקופסה", FakeMovie("טרום בכורה", "טרום בכורה"), True, True),

    # Everything that must survive. These are the reasons the check cannot
    # simply demand that titles be equal.
    (HUNGER, FakeMovie(HUNGER, "The Hunger Games: Sunrise on the Reaping"), True, False),
    # A chain shortens the title; TMDb carries the full one.
    ("קיוטי נגד אקמי", FakeMovie("לוני טונס מציגים: קיוטי נגד אקמי",
                                  "Coyote vs. Acme"), True, False),
    # Hebrew spelling drift, matched locally rather than by TMDb.
    ("אדיוטים", FakeMovie("אידיוטים", "Idiots"), False, False),
    # Same opera, worded differently by two chains, merged by its poster.
    ("לה טראוויאטה - אופרה בקולנוע",
     FakeMovie("אופרה בקולנוע-לה טראוויאטה", None), False, False),
    ("בחזרה מההימלאיה", FakeMovie("בחזרה מההימלאיה", None), False, False),
]

for raw, movie, confident, should_unlink in CASES:
    floor = TITLE_MATCH_FLOOR if confident else ADOPTED_MATCH_FLOOR
    score = _agreement(raw, movie)
    # None means no shared script, so no basis to judge — never an unlink.
    unlinked = score is not None and score < floor
    kind = "title" if confident else "adopted"
    check(
        f"{kind} match {'unlinked' if should_unlink else 'kept'} "
        f"(score {score:.0f} vs floor {floor}): {raw[:30]} -> {movie.title_he}",
        unlinked == should_unlink,
    )

# ---------------------------------------------------------------- scripts

# The regression this guard exists for. The first repair pass fixed the two
# cards above and, in the same run, tore apart several correct ones: a
# Russian-dubbed listing is titled "КЛЭЙФЕЙС" while its film is stored as
# "קלייפייס", and scoring those against each other returns nearly zero purely
# because the alphabets differ. Matching across scripts is a feature here, not
# an accident, so "no shared script" has to mean "no evidence" rather than
# "wrong" — Finnick was split onto an extra card before it did.
CROSS_SCRIPT = [
    ("КЛЭЙФЕЙС", FakeMovie("קלייפייס", "Clayface")),
    ("פיניק: להציל את המפלצות", FakeMovie("Финник 2", "Finnik 2")),
    ("ЧЕЛОВЕК-ПАУК", FakeMovie("ספיידרמן: יום חדש", None)),
]
for raw, movie in CROSS_SCRIPT:
    eq(f"no verdict across scripts: {raw[:22]}", _agreement(raw, movie), None)

check("hebrew and cyrillic share nothing", not shares_script("קלייפייס", "КЛЭЙФЕЙС"))
check("hebrew and hebrew do", shares_script("ויהי גשם", "משחקי הרעב"))
check("latin and latin do", shares_script("Clayface", "Regnmannen"))
# A bilingual film title still gives something to compare against.
check("a mixed title shares with both halves",
      shares_script("ספיידרמן - ЧЕЛОВЕК", "ЧЕЛОВЕК-ПАУК")
      and shares_script("ספיידרמן - ЧЕЛОВЕК", "ספיידרמן"))

# ---------------------------------------------------------------- suffixes

# Lev runs the screening type on after the language with no separator, which
# both defeats the TMDb search and splits the film onto its own card.
eq("a trailing screening note is stripped",
   normalize_title("פיניק 2 - להציל את המפלצות עברית הקרנה רגישה"),
   "פיניק 2 - להציל את המפלצות")
eq("with a dash in front of it too",
   normalize_title("טד החוקר ומנורת הקסמים עברית - הקרנה רגישה"),
   "טד החוקר ומנורת הקסמים")

# The floors must stay apart, and both must sit clear of the cases above. A
# title match keeps a higher bar because it had title evidence to begin with;
# a poster match never did, so only total unrelatedness condemns it.
check("the adopted floor is the looser of the two",
      ADOPTED_MATCH_FLOOR < TITLE_MATCH_FLOOR)
check("the worst kept case clears its floor with room",
      _agreement("לה טראוויאטה - אופרה בקולנוע",
                 FakeMovie("אופרה בקולנוע-לה טראוויאטה", None))
      >= ADOPTED_MATCH_FLOOR + 15)
check("the closest unlinked case misses its floor with room",
      _agreement("טרום בכורה - כבשה בקופסה",
                 FakeMovie("טרום בכורה", "טרום בכורה"))
      <= TITLE_MATCH_FLOOR - 15)


# ---------------------------------------------------------------- synopses

# A film's description used to be the first non-empty one found, which picked
# French. Cinema City lists the French-dubbed showing of "פגוש את הכלה" as a
# separate listing and gave it a French synopsis under the Hebrew heading
# "תקציר בצרפתית" — summary in French. That row came back before the ordinary
# Hebrew one, so the card showed a Hebrew reader a paragraph of French while
# the correct text sat unused on the very next row.
FRENCH_UNDER_HEBREW_LABEL = (
    "תקציר בצרפתית: Un nouveau film de la franchise Mon beau-père et moi. "
    "Le fils de Greg et Pam, Henry, décide de présenter sa fiancée Olivia."
)
REAL_HEBREW = "בנובמבר הקרוב, אייקון הקומדיה בן סטילר וזוכה האוסקר רוברט דה נירו מתאחדים"
ENGLISH = "Henry, son of Greg and Pam Focker, aims to marry Olivia."
RUSSIAN = "Генри, сын Грега и Пэм Факеров, решает жениться на девушке."

# Presence of Hebrew is not enough to judge by: the French text HAS Hebrew in
# it, which is exactly why a contains-Hebrew test would still have shown it.
check("the french text does contain hebrew letters",
      "תקציר" in FRENCH_UNDER_HEBREW_LABEL)
check("but is only a sliver of hebrew by proportion",
      hebrew_fraction(FRENCH_UNDER_HEBREW_LABEL) < 0.25)
check("while a real hebrew synopsis is nearly all hebrew",
      hebrew_fraction(REAL_HEBREW) > 0.9)
eq("empty text is not hebrew", hebrew_fraction(""), 0.0)
eq("nothing is not hebrew", hebrew_fraction(None), 0.0)

eq("hebrew prose wins", overview_rank(REAL_HEBREW), 0)
eq("english is the fallback", overview_rank(ENGLISH), 1)
eq("the hebrew-labelled french loses", overview_rank(FRENCH_UNDER_HEBREW_LABEL), 2)
eq("a russian dub synopsis loses", overview_rank(RUSSIAN), 2)

# The card takes the lowest rank whatever order the rows arrive in, which is
# the actual defect: the French row simply came first.
for candidates in ([FRENCH_UNDER_HEBREW_LABEL, REAL_HEBREW],
                   [REAL_HEBREW, FRENCH_UNDER_HEBREW_LABEL],
                   [RUSSIAN, FRENCH_UNDER_HEBREW_LABEL, REAL_HEBREW, ENGLISH]):
    eq(f"hebrew chosen from {len(candidates)} candidates regardless of order",
       min(candidates, key=overview_rank), REAL_HEBREW)

# With no Hebrew at all, English beats a dub language rather than nothing.
eq("english beats russian when there is no hebrew",
   min([RUSSIAN, ENGLISH], key=overview_rank), ENGLISH)


print(f"\n{passed} passed, {len(failures)} failed")
for failure in failures:
    print(f"  FAIL  {failure}")
sys.exit(1 if failures else 0)

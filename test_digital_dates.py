"""Tests for the digital-release parser.

    python test_digital_dates.py              # offline, uses fixtures below
    python test_digital_dates.py --live       # also reads the real channel

Offline by default and deliberately so: the fixtures are real post HTML copied
from the channel, which means these keep testing the cases that matter even
when the channel has moved on and no longer contains them.

The cases worth having are the ones that were genuinely confusing:

  * An UPDATE NOTE is a reply, and Telegram renders the quoted original inside
    it. Parsed naively, a note that says only "the Digital date was brought
    forward a week" looks like a full film post carrying the original's OLD
    dates -- and would overwrite the corrected value with the very value the
    correction was replacing. This is the bug this file mostly exists for.
  * A date the channel has not fixed yet reads "יפורסם בהמשך". That is a known
    unknown, not a parse failure, and must store as NULL rather than skipping
    the film.
  * Dates are DD/MM/YYYY. Reading them month-first works for the first twelve
    days of any month and then silently produces nonsense.
"""

import argparse
import sys

import digital_dates

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


# ------------------------------------------------------------------ fixtures

# A full film post, trimmed. Real structure, real values (Wildwood, post 2336).
FILM_POST = '''
<div class="tgme_widget_message text_not_supported_wrap js-widget_message"
     data-post="MoviesOnlineDates/2336">
  <div class="tgme_widget_message_text js-message_text" dir="auto">
    \U0001F3AC יער פרא (2026) Wildwood \U0001F3AC<br/><br/>
    ז'אנר: #אנימציה, #הרפתקאות, #פנטזיה<br/>
    בימוי: טראוויס נייט<br/>
    <a href="https://www.youtube.com/watch?v=x">טריילר</a> |
    <a href="https://www.imdb.com/title/tt2056785/">IMDb</a> |
    <a href="https://www.themoviedb.org/movie/791523">TMDb</a><br/><br/>
    תקציר:<br/>הסרט החדש מאולפני לייקה.<br/><br/>
    תאריך יציאה לקולנוע:<br/>
    \U0001F1EE\U0001F1F1 - 12/11/2026<br/>
    \U0001F1FA\U0001F1F8 - 23/10/2026<br/>
    תאריך יציאה לרשת:<br/>
    Digital - 08/12/2026<br/>
    BluRay - יפורסם בהמשך
  </div>
</div>
'''

# An update note. The <a class="tgme_widget_message_reply"> block is the quoted
# original, exactly as Telegram serves it -- note that it carries its own
# \U0001F3AC title line and an OLD Digital date, which is the trap.
UPDATE_POST = '''
<div class="tgme_widget_message text_not_supported_wrap js-widget_message"
     data-post="MoviesOnlineDates/2337">
  <a class="tgme_widget_message_reply" href="https://t.me/MoviesOnlineDates/2300">
    <div class="tgme_widget_message_metatext">בעל בהזמנה</div>
    <div class="tgme_widget_message_text">
      \U0001F3AC בעל בהזמנה (2026) Wicker \U0001F3AC ז'אנר: #קומדיה
      Digital - 01/12/2026
    </div>
  </a>
  <div class="tgme_widget_message_text js-message_text" dir="auto">
    הוקדם תאריך ה-Digital של הסרט "בעל בהזמנה" בשבוע.<br/>
    התאריך עודכן גם בלוח החודש.
  </div>
</div>
'''

# Digital not announced yet. Still a film worth a row: it has a cinema date.
TBA_POST = '''
<div class="tgme_widget_message" data-post="MoviesOnlineDates/2400">
  <div class="tgme_widget_message_text js-message_text">
    \U0001F3AC עלי ג'י (2026) Ali G: Who Iz I? \U0001F3AC<br/>
    <a href="https://www.themoviedb.org/movie/1727734">TMDb</a><br/>
    תאריך יציאה לקולנוע:<br/>
    \U0001F1EE\U0001F1F1 - 25/12/2026<br/>
    תאריך יציאה לרשת:<br/>
    Digital - יפורסם בהמשך<br/>
    BluRay - יפורסם בהמשך
  </div>
</div>
'''

# A film post with no TMDb link. Skipped rather than title-matched: guessing is
# what this whole design avoids.
NO_TMDB_POST = '''
<div class="tgme_widget_message" data-post="MoviesOnlineDates/2401">
  <div class="tgme_widget_message_text js-message_text">
    \U0001F3AC סרט כלשהו (2026) Some Film \U0001F3AC<br/>
    תאריך יציאה לרשת:<br/>Digital - 01/01/2027
  </div>
</div>
'''

# ------------------------------------------------------------------ 1. dates

eq("DD/MM/YYYY is read day-first", digital_dates._iso("08/12/2026"), "2026-12-08")
eq("a day past the 12th still parses", digital_dates._iso("23/10/2026"), "2026-10-23")
eq("an impossible month is rejected, not swapped",
   digital_dates._iso("13/13/2026"), None)
eq("TBA text is not a date", digital_dates._iso("יפורסם בהמשך"), None)
eq("empty is None", digital_dates._iso(""), None)
eq("None is None", digital_dates._iso(None), None)

# ------------------------------------------------------------------ 2. a film post

posts = digital_dates.parse_page(FILM_POST)
eq("one post parsed", len(posts), 1)
eq("post id read", posts[0]["post_id"], 2336)
eq("tmdb id read from the href", posts[0]["tmdb_id"], 791523)

record = digital_dates.extract_release(posts[0])
check("film post yields a record", record is not None)
if record:
    eq("hebrew title", record["title_he"], "יער פרא")
    eq("english title", record["title_en"], "Wildwood")
    eq("digital date", record["digital_date"], "2026-12-08")
    eq("israeli cinema date", record["cinema_il_date"], "2026-11-12")
    eq("bluray TBA stays empty", record["bluray_date"], None)
    eq("attributed to its post", record["source_post_id"], 2336)

# ------------------------------------------------------------------ 3. the trap

posts = digital_dates.parse_page(UPDATE_POST)
eq("update note parsed as one post", len(posts), 1)
if posts:
    text = posts[0]["text"]
    check("quoted original is stripped from the text", "\U0001F3AC" not in text)
    check("the note's own words survive", "הוקדם" in text)
    # The decisive one. If the quote leaks through, this returns a record
    # carrying Wicker's OLD 01/12 date and store() would write it back over
    # the corrected 24/11.
    eq("update note yields NO record",
       digital_dates.extract_release(posts[0]), None)

# ------------------------------------------------------------------ 4. partial data

record = digital_dates.extract_release(digital_dates.parse_page(TBA_POST)[0])
check("a film with no digital date yet is still recorded", record is not None)
if record:
    eq("digital is NULL, not skipped", record["digital_date"], None)
    eq("but the cinema date is kept", record["cinema_il_date"], "2026-12-25")

eq("a post with no tmdb link is skipped",
   digital_dates.extract_release(digital_dates.parse_page(NO_TMDB_POST)[0]), None)

# ------------------------------------------------------------------ 5. store

def test_store() -> None:
    """A correction must overwrite; a blank must not."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base
    import models  # noqa: F401  (registers the tables)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        first = {791523: {"tmdb_id": 791523, "title_he": "יער פרא",
                          "title_en": "Wildwood", "digital_date": "2026-12-08",
                          "bluray_date": None, "cinema_il_date": "2026-11-12",
                          "source_post_id": 2336}}
        result = digital_dates.store(db, first)
        eq("first store adds", (result["added"], result["updated"]), (1, 0))

        result = digital_dates.store(db, first)
        eq("re-storing the same data changes nothing",
           (result["added"], result["updated"]), (0, 0))

        # The channel brings the date forward.
        moved = {791523: {**first[791523], "digital_date": "2026-12-01"}}
        result = digital_dates.store(db, moved)
        eq("a moved date is an update", (result["added"], result["updated"]), (0, 1))
        eq("and the new date is stored",
           db.query(models.DigitalRelease).one().digital_date, "2026-12-01")

        # A scan that failed to read the date must not erase it. This is the
        # fail-open rule: silence is not a retraction.
        blank = {791523: {**first[791523], "digital_date": None,
                          "cinema_il_date": None}}
        digital_dates.store(db, blank)
        row = db.query(models.DigitalRelease).one()
        eq("a missing value never blanks a stored one", row.digital_date, "2026-12-01")
        eq("and neither does a missing cinema date", row.cinema_il_date, "2026-11-12")
    finally:
        db.close()


test_store()

# ------------------------------------------------------------------ 6. live

def test_live() -> None:
    """Read the real channel and sanity-check the shape of what comes back."""
    page = digital_dates.fetch_page()
    posts = digital_dates.parse_page(page)
    check(f"channel returned posts ({len(posts)})", len(posts) > 0)

    records = [r for r in (digital_dates.extract_release(p) for p in posts) if r]
    check(f"at least one film post on the front page ({len(records)})",
          len(records) > 0)
    check("every record carries a tmdb id",
          all(r["tmdb_id"] for r in records))
    check("every date is ISO",
          all(r["digital_date"] is None or len(r["digital_date"]) == 10
              for r in records))
    # Pagination is what makes the rolling window and the backfill possible.
    oldest = min(p["post_id"] for p in posts)
    older = digital_dates.parse_page(digital_dates.fetch_page(before=oldest))
    check("?before= pages further back",
          bool(older) and max(p["post_id"] for p in older) < oldest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="also read the real channel")
    if parser.parse_args().live:
        test_live()

    print(f"\n{passed} passed, {len(failures)} failed")
    for failure in failures:
        print(f"  FAIL  {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

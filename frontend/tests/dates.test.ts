/**
 * Tests for the digital-date wording.
 *
 *     node frontend/tests/dates.test.ts
 *
 * Small, but it guards the rule that decides what gets said at all: an
 * upcoming release carries its date, an already-released one does not. The
 * date answers "how long do I wait", so once a film is out it answers
 * nothing — and it would be actively misleading for older films, where the
 * value comes from TMDb and TMDb logs streaming-platform launches as digital
 * releases (Toy Story reads 2019-11-12 there, which is Disney+ launch week).
 *
 * Dates are built relative to today rather than hardcoded, so these do not
 * start failing in a year.
 */

import { digitalLabel, formatDate } from '../src/api/dates.ts';

let passed = 0;
const failures: string[] = [];

function eq(label: string, actual: unknown, expected: unknown): void {
  if (actual === expected) passed += 1;
  else failures.push(`${label}\n    expected ${expected}\n    actual   ${actual}`);
}

/** An ISO date `days` away from today, negative for the past. */
function offset(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('-');
}

// ---- formatting ----------------------------------------------------------

eq('ISO becomes day-first', formatDate('2026-11-17'), '17/11/2026');
eq('leading zeroes are kept', formatDate('2026-01-05'), '05/01/2026');
eq('a malformed date is passed through', formatDate('nonsense'), 'nonsense');

// ---- nothing to say ------------------------------------------------------

eq('no date, no line', digitalLabel(null), null);
eq('undefined, no line', digitalLabel(undefined), null);
eq('empty string, no line', digitalLabel(''), null);

// ---- upcoming ------------------------------------------------------------

eq('tomorrow is upcoming', digitalLabel(offset(1)), `דיגיטל ${formatDate(offset(1))}`);
eq('next month is upcoming', digitalLabel(offset(30)), `דיגיטל ${formatDate(offset(30))}`);

// ---- already out ---------------------------------------------------------

// Today counts as out. Treating the release day as "not yet" would be wrong
// for the whole of the day the film actually lands.
eq('today reads as out', digitalLabel(offset(0)), 'זמין בדיגיטל');
eq('last week is out, no date', digitalLabel(offset(-7)), 'זמין בדיגיטל');
eq('six months ago is out, no date', digitalLabel(offset(-180)), 'זמין בדיגיטל');

// No date is ever printed for a past release, which is what keeps TMDb's
// unreliable catalogue entries off the screen. These are the real values it
// returns for three films that have been watchable at home for two decades.
eq('Shrek, as TMDb reports it', digitalLabel('2018-02-01'), 'זמין בדיגיטל');
eq('Toy Story’s Disney+ launch date', digitalLabel('2019-11-12'), 'זמין בדיגיטל');
eq('Spirited Away', digitalLabel('2019-12-17'), 'זמין בדיגיטל');

// A value we cannot read says nothing at all. The string comparison that
// decides past-vs-future ranks "not-a-date" above any real date, so without a
// shape check this rendered as "דיגיטל date/a/not" -- and claiming
// availability off an unreadable value would be no better.
eq('an unparseable date says nothing', digitalLabel('not-a-date'), null);
eq('a partial date says nothing', digitalLabel('2026-11'), null);
eq('a timestamp is not an accepted shape', digitalLabel('2026-11-09T12:00'), null);

// ---- report --------------------------------------------------------------

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const failure of failures) console.error(`  FAIL  ${failure}`);
  process.exitCode = 1;
} else {
  console.log('digital date wording ok\n');
}

/**
 * Tests for the .ics a screening turns into.
 *
 *     node frontend/tests/calendar.test.ts
 *
 * iCalendar is a format where small mistakes fail silently and late: a file
 * with an unescaped comma, an unfolded long line or LF endings is accepted by
 * one calendar app and rejected without explanation by another, and the person
 * finds out when the event is not there. None of that is visible in the
 * browser, so it gets asserted here.
 *
 * The cases that matter:
 *
 *   * THE ALARM. It is the entire reason this is a file rather than a link to
 *     Google Calendar, whose prefill URL cannot express a reminder at all.
 *   * ESCAPING. Comma and semicolon are value separators in iCalendar, and
 *     real film titles contain both.
 *   * FOLDING, measured in bytes. Hebrew is two bytes a letter in UTF-8, so a
 *     Hebrew title reaches the 75-octet limit in half the characters an
 *     English one would.
 *   * FLOATING TIME. No Z and no TZID is a deliberate choice, not an omission
 *     — a Z here would silently shift every event by the DST offset.
 */

import {
  REMINDER_HOURS,
  buildIcs,
  durationMinutes,
  googleCalendarUrl,
  icsFilename,
  type ScreeningEvent,
} from '../src/api/calendar.ts';

let passed = 0;
const failures: string[] = [];

function check(label: string, condition: boolean): void {
  if (condition) passed += 1;
  else failures.push(label);
}

function eq(label: string, actual: unknown, expected: unknown): void {
  if (actual === expected) passed += 1;
  else failures.push(`${label}\n    expected ${expected}\n    actual   ${actual}`);
}

const BASE: ScreeningEvent = {
  filmTitle: 'האודיסאה',
  cinema: 'סינמה סיטי נתניה',
  chain: 'Cinema City',
  address: 'המחקר 3, נתניה',
  date: '2026-11-12',
  time: '20:20',
  runtimeMinutes: 150,
  venueType: 'regular',
  ticketUrl: 'https://tickets.cinema-city.co.il/order/849691',
};

const NOW = new Date('2026-11-09T18:30:00Z');
const ics = buildIcs(BASE, NOW);
const lines = ics.split('\r\n');

/** A folded value, reassembled: continuation lines begin with one space. */
function value(prefix: string): string | null {
  const unfolded = ics.replace(/\r\n /g, '');
  const line = unfolded.split('\r\n').find((l) => l.startsWith(prefix));
  return line ? line.slice(prefix.length) : null;
}

// ---- structure -----------------------------------------------------------

eq('opens as a calendar', lines[0], 'BEGIN:VCALENDAR');
eq('closes cleanly', lines[lines.length - 2], 'END:VCALENDAR');
eq('ends with CRLF', ics.endsWith('\r\n'), true);
check('every line break is CRLF, never a bare LF',
  !/[^\r]\n/.test(ics));
check('declares version 2.0', lines.includes('VERSION:2.0'));
check('has exactly one event',
  lines.filter((l) => l === 'BEGIN:VEVENT').length === 1);

// ---- the alarm -----------------------------------------------------------

check('has an alarm at all', lines.includes('BEGIN:VALARM'));
eq(`alarm fires ${REMINDER_HOURS} hours before`,
  lines.includes(`TRIGGER:-PT${REMINDER_HOURS}H`), true);
check('the alarm is displayable', lines.includes('ACTION:DISPLAY'));
check('the alarm is closed', lines.includes('END:VALARM'));

// ---- times ---------------------------------------------------------------

eq('starts at the advertised time', value('DTSTART:'), '20261112T202000');
// 150 min of film + 20 of adverts = 170, so 20:20 -> 23:10.
eq('ends after the film plus the adverts', value('DTEND:'), '20261112T231000');
eq('duration is runtime plus adverts', durationMinutes(150), 170);
eq('an unknown runtime falls back to two hours', durationMinutes(null), 120);
eq('a nonsense runtime falls back too', durationMinutes(0), 120);

// Floating, deliberately. A trailing Z would make these UTC and shift every
// event by Israel's offset; a TZID without a VTIMEZONE block is what strict
// parsers reject.
check('DTSTART carries no zone', !/^DTSTART[;:].*(Z|TZID)/m.test(ics));
check('DTEND carries no zone', !/^DTEND[;:].*(Z|TZID)/m.test(ics));
// DTSTAMP is the exception: it is a real moment and must be absolute.
eq('DTSTAMP is UTC', value('DTSTAMP:'), '20261109T183000Z');

// Crossing midnight must roll the date, not produce hour 25.
// 23:30 + (100 film + 20 adverts) = 01:30 on the 13th.
const lateNight = buildIcs({ ...BASE, time: '23:30', runtimeMinutes: 100 }, NOW);
check('a late screening rolls into the next day',
  lateNight.includes('DTSTART:20261112T233000')
  && lateNight.includes('DTEND:20261113T013000'));

// And across a month boundary, which is the same code path but the case most
// likely to be wrong if the arithmetic were done on the date string.
const monthEnd = buildIcs({ ...BASE, date: '2026-11-30', time: '23:00' }, NOW);
check('a late screening rolls into the next month',
  monthEnd.includes('DTEND:20261201T015000'));

// ---- escaping ------------------------------------------------------------

const awkward = buildIcs({
  ...BASE,
  filmTitle: 'מואנה, הסרט; גרסה מיוחדת\\רגילה',
  cinema: 'קולנוע, תל אביב',
}, NOW);

check('commas are escaped', awkward.includes('\\,'));
check('semicolons are escaped', awkward.includes('\\;'));
check('backslashes are escaped first, not doubled wrongly',
  awkward.includes('\\\\'));
check('no bare comma survives in SUMMARY',
  !/^SUMMARY:[^\r\n]*[^\\],/m.test(awkward));

// ---- folding -------------------------------------------------------------

const longTitle = buildIcs({
  ...BASE,
  // Comfortably past 75 bytes in Hebrew while well under 75 characters.
  filmTitle: 'הרפתקאותיו המופלאות של הילד שרצה להיות גיבור על בממלכה רחוקה מאוד',
}, NOW);

const encoder = new TextEncoder();
check('no content line exceeds 75 octets',
  longTitle.split('\r\n').every((l) => encoder.encode(l).length <= 75));
check('continuation lines are marked with a leading space',
  longTitle.includes('\r\n '));
// The fold has to be reversible, and must not have cut a Hebrew letter in two.
check('the folded title survives unfolding',
  longTitle.replace(/\r\n /g, '').includes('הרפתקאותיו המופלאות'));
check('no replacement characters from a split codepoint',
  !longTitle.includes('�'));

// ---- identity ------------------------------------------------------------

const again = buildIcs(BASE, new Date('2026-11-10T09:00:00Z'));
eq('the same screening keeps the same UID across runs',
  value('UID:'), again.replace(/\r\n /g, '').split('\r\n')
    .find((l) => l.startsWith('UID:'))?.slice(4));
check('a different screening gets a different UID',
  value('UID:') !== buildIcs({ ...BASE, time: '21:40' }, NOW)
    .split('\r\n').find((l) => l.startsWith('UID:'))?.slice(4));

// ---- content -------------------------------------------------------------

check('the summary names the film and the cinema',
  (value('SUMMARY:') ?? '').includes('האודיסאה')
  && (value('SUMMARY:') ?? '').includes('סינמה סיטי נתניה'));
check('the location includes the address',
  (value('LOCATION:') ?? '').includes('המחקר 3'));
check('the description links back to the booking',
  (value('DESCRIPTION:') ?? '').includes('tickets.cinema-city.co.il'));

// A theatre with no address must still produce a usable location, not "null".
const noAddress = buildIcs({ ...BASE, address: null }, NOW);
check('a missing address does not leak "null"',
  !noAddress.includes('null'));

// A non-standard hall is worth recording; "regular" is not.
check('a VIP hall is noted',
  buildIcs({ ...BASE, venueType: 'VIP' }, NOW).includes('VIP'));
check('an ordinary hall is not spelled out',
  !(value('DESCRIPTION:') ?? '').includes('regular'));

// ---- the Google Calendar route -------------------------------------------

const gcal = new URL(googleCalendarUrl(BASE));
const q = gcal.searchParams;

eq('points at Google Calendar', gcal.host, 'calendar.google.com');
eq('asks for a new event', q.get('action'), 'TEMPLATE');
eq('carries the same window as the file', q.get('dates'),
  '20261112T202000/20261112T231000');
check('titles with the film and the cinema',
  (q.get('text') ?? '').includes('האודיסאה')
  && (q.get('text') ?? '').includes('סינמה סיטי נתניה'));
check('carries the address', (q.get('location') ?? '').includes('המחקר 3'));
check('links back to the booking',
  (q.get('details') ?? '').includes('tickets.cinema-city.co.il'));

// Google resolves the offset itself from a zone name, which is the one thing
// this route does BETTER than the file — the .ics has to leave time floating
// because a VTIMEZONE block would be needed to say this properly.
eq('names the timezone rather than guessing an offset',
  q.get('ctz'), 'Asia/Jerusalem');
check('the times are naive, for ctz to interpret',
  !(q.get('dates') ?? '').includes('Z'));

// Hebrew and separators have to survive the query string intact.
check('hebrew round-trips through the URL',
  new URL(googleCalendarUrl({ ...BASE, filmTitle: 'מואנה, הסרט' }))
    .searchParams.get('text')?.includes('מואנה, הסרט') === true);

// The documented gap, asserted so nobody later assumes it was handled.
check('no reminder parameter exists to set',
  !['reminder', 'reminders', 'alarm', 'notification']
    .some((key) => q.has(key)));

// ---- filename ------------------------------------------------------------

check('the filename ends in .ics', icsFilename(BASE).endsWith('.ics'));
check('the filename has no path separators or spaces',
  !/[\\/\s]/.test(icsFilename(BASE)));
eq('a title of pure punctuation still yields a filename',
  icsFilename({ ...BASE, filmTitle: '***', date: '', time: '' }), 'screening.ics');

// ---- report --------------------------------------------------------------

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const failure of failures) console.error(`  FAIL  ${failure}`);
  process.exitCode = 1;
} else {
  console.log('calendar export ok\n');
}

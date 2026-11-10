/**
 * Tests for the client's half of the calendar feature.
 *
 *     node frontend/tests/calendar.test.ts
 *
 * The .ics itself is no longer built here — it is served by the backend so the
 * browser can hand it to a calendar app instead of saving it to Downloads, and
 * its format is asserted in test_calendar_ics.py. What is left on this side is
 * the two links the prompt offers, and one property worth protecting:
 *
 *   THE FILE URL CARRIES IDS, NOT WORDS. The server reads the title, cinema,
 *   address and ticket link from the database, so nothing a caller types can
 *   land inside a calendar entry. If someone later "simplifies" this by
 *   passing the event's text in the query string, these assertions fail.
 *
 * The Google route keeps its own tests because it is the opposite case: there
 * the text IS the interface, and the one thing it cannot express is the alarm.
 */

import {
  durationMinutes,
  googleCalendarUrl,
  screeningIcsUrl,
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
  else failures.push(`${label}
    expected ${expected}
    actual   ${actual}`);
}

const BASE: ScreeningEvent = {
  filmId: 'm1368337',
  theatreId: 7,
  filmTitle: 'האודיסאה',
  cinema: 'סינמה סיטי נתניה',
  chain: 'Cinema City',
  address: 'המחקר 3, נתניה',
  date: '2026-11-12',
  time: '20:20',
  runtimeMinutes: 150,
  venueType: 'regular',
  dubbedLanguage: null,
  ticketUrl: 'https://tickets.cinema-city.co.il/order/849691',
};


// ---- duration, which the prompt states before you commit ------------------

eq('duration is runtime plus adverts', durationMinutes(150), 170);
eq('an unknown runtime falls back to two hours', durationMinutes(null), 120);
eq('a nonsense runtime falls back too', durationMinutes(0), 120);

// ---- the file route is a URL, not a generated download --------------------

const icsUrl = screeningIcsUrl(BASE);
check('points at the server endpoint', icsUrl.startsWith('/api/screening.ics?'));
check('is not a blob or data url',
  !icsUrl.startsWith('blob:') && !icsUrl.startsWith('data:'));

const icsParams = new URL(icsUrl, 'https://x.test').searchParams;
eq('names the film by id', icsParams.get('film'), BASE.filmId);
eq('names the cinema by id', icsParams.get('theatre'), String(BASE.theatreId));
eq('names the screening by its start', icsParams.get('at'), '2026-11-12T20:20:00');
eq('narrows by hall', icsParams.get('venue_type'), 'regular');

// The event's words must never travel in the query string: the server reads
// them from the database, which is what keeps an .ics out of reach of
// anything a caller types.
for (const word of ['האודיסאה', 'סינמה סיטי נתניה', 'Cinema City', 'tickets.cinema-city']) {
  check(`the url carries no event text: ${word}`, !icsUrl.includes(encodeURIComponent(word)));
}
check('no title parameter at all', !icsParams.has('text') && !icsParams.has('title'));

// ---- the Google Calendar route -------------------------------------------

const gcal = new URL(googleCalendarUrl(BASE));
const q = gcal.searchParams;

eq('points at Google Calendar', gcal.host, 'calendar.google.com');
// The editor route, not /render. The Android app intercepts /render and
// handles it by jumping to the date and dropping every other parameter, which
// is what it did on a real phone: the app opened on the screening's day with
// no event at all.
eq('uses the event editor route', gcal.pathname, '/calendar/u/0/r/eventedit');
check('is not the /render route the app swallows',
  !gcal.pathname.includes('/render'));
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

// The filename moved to the server with the file itself — it is a
// Content-Disposition header now, asserted in test_calendar_ics.py.

// ---- report --------------------------------------------------------------

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const failure of failures) console.error(`  FAIL  ${failure}`);
  process.exitCode = 1;
} else {
  console.log('calendar export ok\n');
}

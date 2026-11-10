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
 * The intent route is the opposite case and keeps its own tests: there the
 * text IS the interface, carried as extras in a URI whose own separators are
 * ';' and '=' — characters that appear in real film titles. The one thing it
 * cannot express is the alarm, which is why the file route survives alongside
 * it rather than being replaced by it.
 */

import {
  calendarIntentUrl,
  durationMinutes,
  isAndroid,
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

// ---- the Android intent route --------------------------------------------

const FALLBACK = 'https://on-cinema-now.fly.dev/api/screening.ics?film=m1368337';
const intent = calendarIntentUrl(BASE, FALLBACK);

check('is an intent url', intent.startsWith('intent://'));
check('asks Android to create an event',
  intent.includes('action=android.intent.action.INSERT'));
check('targets the calendar events type',
  intent.includes('type=vnd.android.cursor.dir/event'));
check('is terminated', intent.endsWith(';end'));

/** An extra's value, decoded. */
function extra(key: string): string | null {
  const m = intent.match(new RegExp(`(?:^|;)(?:S|l)\.${key}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

check('titles with the film and the cinema',
  (extra('title') ?? '').includes('האודיסאה')
  && (extra('title') ?? '').includes('סינמה סיטי נתניה'));
check('carries the address', (extra('eventLocation') ?? '').includes('המחקר 3'));
check('links back to the booking',
  (extra('description') ?? '').includes('tickets.cinema-city.co.il'));
eq('falls back to the file if nothing handles it',
  extra('browser_fallback_url'), FALLBACK);

// Real epoch millis, not a wall clock — an intent extra is an instant. The
// window must still be the same length as the file's.
const begin = Number(extra('beginTime'));
const end = Number(extra('endTime'));
check('beginTime is epoch millis', Number.isFinite(begin) && begin > 1e12);
eq('the window matches the duration shown',
  (end - begin) / 60_000, durationMinutes(BASE.runtimeMinutes));
eq('and begins at the advertised local time',
  new Date(begin).getHours() * 60 + new Date(begin).getMinutes(), 20 * 60 + 20);

// ';' and '=' end an extra in this syntax, so an unencoded one in a title
// would truncate the event and silently drop everything after it.
const awkward = calendarIntentUrl(
  { ...BASE, filmTitle: 'מואנה; הסרט=המלא', cinema: 'קולנוע; תל אביב' },
  FALLBACK,
);
check('separators inside values are encoded',
  !awkward.split('S.title=')[1].split(';')[0].includes('='));
check('every extra still present after an awkward title',
  ['S.title=', 'S.eventLocation=', 'S.description=', 'l.beginTime=', 'l.endTime=']
    .every((k) => awkward.includes(k)));
check('and it is still terminated', awkward.endsWith(';end'));

// ---- platform ------------------------------------------------------------

check('android phone is detected',
  isAndroid('Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 Chrome/152'));
check('desktop is not',
  !isAndroid('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152'));
check('iphone is not — intent:// is a Chrome on Android scheme',
  !isAndroid('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Mobile Safari'));

// ---- report --------------------------------------------------------------

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const failure of failures) console.error(`  FAIL  ${failure}`);
  process.exitCode = 1;
} else {
  console.log('calendar export ok\n');
}

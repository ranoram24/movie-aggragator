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
 * There is one route now, not two. Everything ends at the same .ics; the only
 * difference is whether Android is asked to open it (a VIEW intent) or the
 * browser is left to save it. That is what keeps the two-hour reminder on
 * every platform — the previous design's fast route could not carry an alarm
 * at all, so choosing it meant giving one up.
 */

import {
  addToCalendarUrl,
  durationMinutes,
  icsIntentUrl,
  screeningIcsUrl,
  supportsIntentUrls,
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

// ---- the VIEW intent, which is how one route gets both halves ------------

const ORIGIN = 'https://on-cinema-now.fly.dev';
const ABSOLUTE = `${ORIGIN}${screeningIcsUrl(BASE)}`;
const intent = icsIntentUrl(ABSOLUTE);

check('is an intent url', intent.startsWith('intent://'));
check('asks Android to VIEW the file',
  intent.includes('action=android.intent.action.VIEW'));
check('typed as a calendar, so a calendar handles it',
  intent.includes('type=text/calendar'));
check('restores the scheme it replaced', intent.includes(';scheme=https'));
check('is terminated', intent.endsWith(';end'));

// The point of VIEW over INSERT: the handler fetches the real file, so the
// alarm comes with it. INSERT hands over a list of fields and has no extra
// for a reminder at all.
check('carries the host and path of the file',
  intent.includes('on-cinema-now.fly.dev/api/screening.ics'));
check('keeps the query that identifies the screening',
  intent.includes('film=') && intent.includes('theatre=') && intent.includes('at='));

const fb = intent.match(/S\.browser_fallback_url=([^;]*)/);
eq('falls back to the plain file', decodeURIComponent(fb?.[1] ?? ''), ABSOLUTE);

// A '#' would end the intent URI early and swallow the rest of it; the .ics
// URL must never carry a fragment.
check('the ics url has no fragment to break the intent', !ABSOLUTE.includes('#'));

// ---- who may be given an intent url --------------------------------------

const CHROME_ANDROID = 'Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Mobile Safari/537.36';
const FIREFOX_ANDROID = 'Mozilla/5.0 (Android 14; Mobile; rv:132.0) Gecko/132.0 Firefox/132.0';
const SAMSUNG_ANDROID = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36';
const EDGE_ANDROID = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Mobile Safari/537.36 EdgA/152.0.0.0';
const DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36';
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1';

check('chrome on android gets the intent', supportsIntentUrls(CHROME_ANDROID));
check('samsung internet is chromium, so it does too', supportsIntentUrls(SAMSUNG_ANDROID));
check('edge on android too', supportsIntentUrls(EDGE_ANDROID));

// The one that matters. intent:// is a Chromium feature, not an Android one.
// Handing it to Gecko did not harmlessly do nothing — it took the tab to
// about:blank and left the app as a dead document.
check('FIREFOX ON ANDROID DOES NOT', !supportsIntentUrls(FIREFOX_ANDROID));
check('desktop does not', !supportsIntentUrls(DESKTOP));
check('iphone does not', !supportsIntentUrls(IPHONE));

// ---- what each browser is actually handed --------------------------------

check('chrome android is asked to open the file',
  addToCalendarUrl(BASE, CHROME_ANDROID, ORIGIN).startsWith('intent://'));

// Everything else gets the plain relative URL — which downloads, and is the
// honest answer: no web API can open a file in another app without the
// browser's cooperation, and only Chromium offers any.
for (const [name, ua] of [['firefox', FIREFOX_ANDROID], ['desktop', DESKTOP],
                          ['iphone', IPHONE]] as const) {
  const url = addToCalendarUrl(BASE, ua, ORIGIN);
  check(`${name} is never handed an intent it cannot follow`,
    !url.includes('intent://'));
  check(`${name} still gets the file`, url.startsWith('/api/screening.ics?'));
}

// Whatever the browser, the destination is the same file — so the two-hour
// reminder survives on every platform. That is the property the previous
// design lost: its fast route could not carry an alarm at all.
for (const ua of [CHROME_ANDROID, FIREFOX_ANDROID, DESKTOP, IPHONE]) {
  check('every route ends at the .ics',
    addToCalendarUrl(BASE, ua, ORIGIN).includes('/api/screening.ics?'));
}

// ---- report --------------------------------------------------------------

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const failure of failures) console.error(`  FAIL  ${failure}`);
  process.exitCode = 1;
} else {
  console.log('calendar export ok\n');
}

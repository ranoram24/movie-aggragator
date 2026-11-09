/**
 * Tests for the search matcher.
 *
 *     node frontend/tests/search.test.ts
 *
 * Node 24 strips the types itself, so this needs no test runner, no transpile
 * step and no new dependency. It lives outside src/ deliberately: tsconfig.app
 * compiles everything under src/, and a test file in there would be bundled
 * into the shipped app.
 *
 * Three groups, and the third is the point of the file:
 *
 *   1. that the Hebrew folds in search.ts do what their comments claim,
 *   2. that a chain filter and a city query compose the way the UI relies on,
 *   3. that a hostile query is inert.
 *
 * Group 3 is not decoration. The matcher is the only code in the app that
 * touches free text, and the one thing that would make it dangerous is building
 * a pattern or a query string out of that text. The cases below are what
 * failure would look like: a regex metacharacter that matches everything, an
 * unbalanced bracket that throws, a long string that hangs. All three are
 * impossible while matching is String.includes, and these assertions are what
 * will notice if someone later "optimises" it into a RegExp.
 */

import {
  MAX_QUERY_LENGTH,
  filterMovies,
  filterTheatres,
  normalizeForSearch,
  queryTokens,
} from '../src/api/search.ts';

let passed = 0;
const failures: string[] = [];

function check(label: string, condition: boolean): void {
  if (condition) passed += 1;
  else failures.push(label);
}

function eq<T>(label: string, actual: T, expected: T): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) passed += 1;
  else failures.push(`${label}\n    expected ${JSON.stringify(expected)}\n    actual   ${JSON.stringify(actual)}`);
}

// ---------------------------------------------------------------- fixtures

// Real films from the catalogue, including the word-order pair that the title
// matcher never managed to merge into one card.
const MOVIES = [
  { title_he: 'שרק', title_en: 'Shrek' },
  { title_he: 'מלך האריות', title_en: 'The Lion King' },
  { title_he: 'האי הנעלם', title_en: 'Forgotten Island' },
  { title_he: 'אדמה', title_en: null },
  { title_he: 'גרייסי ופדרו', title_en: null },
  { title_he: 'ילד המדבר', title_en: null },
];

// Real theatre rows, copied from the live table. The awkward ones are all here
// on purpose: Hot Cinema's bare city name with no address at all, Movieland's
// Tel Aviv sites that spell it ת"א in the name and תל אביב in the address, and
// Cinema City's hyphen and gershayim.
const THEATRES = [
  { name: 'סינמה סיטי נתניה', address: 'המחקר 3 ,נתניה, מתחם רוגובין', chain: 'Cinema City' },
  { name: 'סינמה סיטי כפר-סבא', address: 'וייצמן 207, מתחם G, כפ”ס', chain: 'Cinema City' },
  { name: 'סינמה סיטי ראשל"צ', address: 'שדרות משה דיין 32, ראשל”צ', chain: 'Cinema City' },
  { name: 'חיפה', address: null, chain: 'Hot Cinema' },
  { name: 'כפר סבא', address: null, chain: 'Hot Cinema' },
  { name: 'נתניה', address: 'גיבורי ישראל 17, מתחם עמי פולג', chain: 'Movieland' },
  { name: 'הצוק ת"א', address: 'מובילנד הצוק תל אביב, יוניצמן 21 תל אביב', chain: 'Movieland' },
  { name: 'פלאנט ראשון לציון', address: 'המאה ועשרים 4, ראשון לציון מערב, ראשון לציון', chain: 'Planet' },
  { name: 'לב תל אביב', address: "דיזינגוף פינת קינג ג'ורג', תל אביב", chain: 'Lev' },
];

const titles = (list: { title_he: string }[]) => list.map((m) => m.title_he);
const names = (list: { name: string }[]) => list.map((t) => t.name);

// ---------------------------------------------------------------- 1. folding

eq('niqqud is stripped', normalizeForSearch('שָׁרֵק'), 'שרק');
eq('final letters fold', normalizeForSearch('אדם'), 'אדמ');
eq('hyphen becomes a space', normalizeForSearch('כפר-סבא'), 'כפר סבא');
eq('gershayim are dropped', normalizeForSearch('ראשל"צ'), 'ראשלצ');
eq('curly gershayim fold the same way', normalizeForSearch('ראשל”צ'), 'ראשלצ');
eq('latin is lowercased', normalizeForSearch('Shrek'), 'shrek');
eq('nullish is empty', normalizeForSearch(null), '');

eq('an empty query has no tokens', queryTokens(''), []);
eq('a punctuation-only query has no tokens', queryTokens('  ,.-  '), []);
// Already folded: the final ך of מלך is normalised to כ, which is the whole
// point -- the token is what gets compared, so it has to be in folded form.
eq('tokens split on whitespace', queryTokens('מלך האריות'), ['מלכ', 'האריות']);
eq('a hebrew abbreviation stays one token', queryTokens('ראשל"צ'), ['ראשלצ']);

// ---------------------------------------------------------------- 2. films

eq('empty query returns everything', filterMovies(MOVIES, '').length, MOVIES.length);
eq('whitespace returns everything', filterMovies(MOVIES, '   ').length, MOVIES.length);

eq('hebrew exact', titles(filterMovies(MOVIES, 'שרק')), ['שרק']);
eq('hebrew prefix, mid-type', titles(filterMovies(MOVIES, 'שר')), ['שרק']);
eq('english title', titles(filterMovies(MOVIES, 'shrek')), ['שרק']);
eq('english is case-insensitive', titles(filterMovies(MOVIES, 'SHREK')), ['שרק']);
eq('english partial', titles(filterMovies(MOVIES, 'lion')), ['מלך האריות']);
eq('word order does not matter', titles(filterMovies(MOVIES, 'אריות מלך')), ['מלך האריות']);
eq('final-form query finds mid-word spelling', titles(filterMovies(MOVIES, 'אדם')), ['אדמה']);
eq('no match is empty, not everything', filterMovies(MOVIES, 'זזזזז').length, 0);

// Each keystroke may only narrow. Anything else makes an as-you-type box feel
// like it is fighting you.
const typing = ['מ', 'מל', 'מלך', 'מלך ה'];
let previous = MOVIES.length;
for (const partial of typing) {
  const count = filterMovies(MOVIES, partial).length;
  check(`typing "${partial}" narrows or holds (${previous} -> ${count})`, count <= previous);
  previous = count;
}

// ---------------------------------------------------------------- 3. cities

eq('city in the name', names(filterTheatres(THEATRES, 'נתניה')), [
  'סינמה סיטי נתניה',
  'נתניה',
]);
eq('bare city name, no address at all', names(filterTheatres(THEATRES, 'חיפה')), ['חיפה']);
eq('hyphen in the stored name', names(filterTheatres(THEATRES, 'כפר סבא')), [
  'סינמה סיטי כפר-סבא',
  'כפר סבא',
]);
eq('found through the address only', names(filterTheatres(THEATRES, 'תל אביב')), [
  'הצוק ת"א',
  'לב תל אביב',
]);
eq('abbreviation expanded: ראשל"צ reachable as ראשון לציון',
  names(filterTheatres(THEATRES, 'ראשון לציון')),
  ['סינמה סיטי ראשל"צ', 'פלאנט ראשון לציון']);
eq('and the abbreviation itself still works',
  names(filterTheatres(THEATRES, 'ראשל"צ')),
  ['סינמה סיטי ראשל"צ']);
eq('theatre name, not a city', names(filterTheatres(THEATRES, 'פלאנט')), [
  'פלאנט ראשון לציון',
]);

// The composition the feature was asked for: chain chips narrow first, so the
// city text can only ever see what they allowed through.
const movielandOnly = THEATRES.filter((t) => t.chain === 'Movieland');
eq('Movieland + נתניה excludes Cinema City Netanya',
  names(filterTheatres(movielandOnly, 'נתניה')),
  ['נתניה']);
eq('Movieland + חיפה is empty rather than falling back to other chains',
  filterTheatres(movielandOnly, 'חיפה').length,
  0);

// ---------------------------------------------------------------- 4. hostile input

const HOSTILE = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
  '"><svg/onload=alert(1)>',
  "javascript:alert(1)",
  "' OR '1'='1",
  "'; DROP TABLE theatres; --",
  '" OR 1=1 --',
  '1; DELETE FROM screenings',
  '{{constructor.constructor("alert(1)")()}}',
  '__proto__',
  '../../etc/passwd',
];

for (const payload of HOSTILE) {
  // Inert: matches nothing, and -- the part that matters -- does not throw.
  // A matcher that compiled the query would throw on several of these.
  let threw = false;
  let count = -1;
  try {
    count = filterTheatres(THEATRES, payload).length + filterMovies(MOVIES, payload).length;
  } catch {
    threw = true;
  }
  check(`hostile query does not throw: ${payload}`, !threw);
  check(`hostile query matches nothing: ${payload}`, count === 0);
}

// __proto__ as a key must not reach through to Object.prototype. The
// abbreviation table is a plain object literal, so a token of "__proto__"
// looks up its inherited value rather than undefined unless the lookup is
// guarded -- the filter(Boolean) is what keeps that out of the haystack.
check('prototype pollution does not corrupt the table',
  filterTheatres(THEATRES, '__proto__').length === 0
  && filterTheatres(THEATRES, 'constructor').length === 0);

// A stray control character is stripped, leaving the query it was hiding
// behind. Listed separately from the payloads above because the correct
// outcome here is a MATCH -- "נתניה" plus a NUL is still someone searching for
// Netanya, and the assertion worth making is that the NUL changes nothing
// rather than that it matches nothing.
eq('a NUL byte is inert, not a modifier',
  names(filterTheatres(THEATRES, 'נתניה\u0000')),
  names(filterTheatres(THEATRES, 'נתניה')));

// Regex metacharacters are literal text. Picking a discriminating case matters
// here: ".*" is a poor test because a RegExp and a no-op filter both return
// everything. A character class is unambiguous -- as a pattern "[שא]רק" matches
// שרק, and as literal text no title contains it.
eq('a character class is text, not a pattern',
  filterMovies(MOVIES, '[שא]רק').length, 0);
eq('an anchored alternation is text', filterMovies(MOVIES, '^(שרק|אדמה)$').length, 0);

// Patterns that throw at compile time. The assertion is simply that nothing
// throws -- a matcher that built a RegExp would die on every one of these, and
// an unhandled error in an onChange handler blanks the screen.
for (const pattern of ['([', '(?:', '\\', '[a-', '*+?', '(?<']) {
  let threw = false;
  try {
    filterMovies(MOVIES, pattern);
    filterTheatres(THEATRES, pattern);
  } catch {
    threw = true;
  }
  check(`does not throw on: ${pattern}`, !threw);
}

// And what a punctuation-only query actually does: nothing. It reduces to zero
// tokens, which every caller reads as "no filter" -- so the list stays whole
// instead of emptying out while you reach for the next key.
eq('a punctuation-only query is no filter, same as empty',
  filterMovies(MOVIES, '([').length, MOVIES.length);

// A query far over the cap must be truncated, not walked. The nested quantifier
// below is the classic ReDoS shape; with String.includes it is just characters.
const huge = 'א'.repeat(50_000);
const redos = `${'a'.repeat(5_000)}!`;
const started = Date.now();
check('over-long query is truncated to the cap',
  queryTokens(huge)[0]?.length === MAX_QUERY_LENGTH);
check('over-long query matches nothing', filterMovies(MOVIES, huge).length === 0);
check('ReDoS-shaped query matches nothing', filterMovies(MOVIES, redos).length === 0);
check(`both complete promptly (${Date.now() - started}ms)`, Date.now() - started < 500);

// A film whose own title contains markup must still be findable -- escaping is
// React's job at render time, not the filter's, and sanitising here would mean
// a legitimately punctuated title could not be searched.
const markupTitled = [{ title_he: 'סרט <מיוחד>', title_en: null }];
eq('markup in the data is matched as text',
  filterMovies(markupTitled, 'מיוחד').length, 1);

// ---------------------------------------------------------------- report

console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  for (const failure of failures) console.error(`  FAIL  ${failure}`);
  // exitCode rather than process.exit(): exit() tears the loop down while
  // stdout is still flushing, which on Windows aborts inside libuv and buries
  // the failure list under a C assertion.
  process.exitCode = 1;
} else {
  console.log('search matcher ok\n');
}

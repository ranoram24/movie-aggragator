/**
 * Text matching for the two search boxes. Pure functions: no DOM, no network,
 * no database.
 *
 * ## Why this runs in the browser
 *
 * Both searches filter data the client already holds. The browse screen fetches
 * every film in one request and the detail screen fetches every theatre showing
 * one film, so narrowing either is a local array filter -- the same reasoning
 * the chain and dub filters already follow. That buys three things:
 *
 *   * results land on the keystroke, with no request and no debounce;
 *   * a chain filter and a search compose by intersecting two arrays, which is
 *     how "only Movieland + נתניה" can never leak a Cinema City row; and
 *   * what the user types never reaches the server, so it never reaches SQL.
 *     The third one is not a side benefit -- it is the whole injection defence,
 *     and it is why there is no new endpoint to attack. See test_search_security.py
 *     for the inputs that DO cross that boundary.
 *
 * ## Why matching is not just `includes()`
 *
 * Hebrew defeats a naive substring match in four distinct ways, all of them
 * present in the live data:
 *
 *   1. FINAL LETTER FORMS. Five letters change shape at the end of a word
 *      (כ->ך, מ->ם, נ->ן, פ->ף, צ->ץ). Someone typing their way into a word
 *      types the final form -- "אדם" -- while the title spells it mid-word,
 *      "אדמה". Raw substring fails on a word the user has typed correctly.
 *   2. PUNCTUATION. The chains disagree about it constantly: "כפר-סבא" with a
 *      hyphen from Cinema City, "כפר סבא" with a space from Hot Cinema, and
 *      gershayim that are sometimes ASCII ("ראשל\"צ") and sometimes curly
 *      ("ראשל”צ") in two fields of the same row.
 *   3. ABBREVIATION. Cinema City files its Rishon branch as ראשל"צ while Planet
 *      writes ראשון לציון; Movieland writes ת"א where its own address says
 *      תל אביב. Nobody searching for a city types the abbreviation.
 *   4. WORD ORDER. "מלך האריות" should be reachable by "אריות מלך", and the
 *      catalogue genuinely carries one film as both "גרייסי ופדרו" and
 *      "פדרו וגרייסי".
 *
 * So: normalise both sides, then require every token of the query to appear
 * somewhere in the haystack. Tokens rather than one substring is what fixes (4),
 * and it keeps as-you-type honest -- each character typed can only ever narrow
 * the result set, never reshuffle it.
 */

/** Hebrew niqqud and cantillation, stripped so a pointed title still matches. */
const NIQQUD_RE = /[֑-ׇ]/g;

/** Final letter forms -> their ordinary form. See (1) above. */
const FINAL_FORMS: Record<string, string> = {
  ך: 'כ',
  ם: 'מ',
  ן: 'נ',
  ף: 'פ',
  ץ: 'צ',
};

const FINAL_FORMS_RE = /[ךםןףץ]/g;

/**
 * Apostrophes, quotes, and the Hebrew geresh and gershayim: DELETED rather than
 * turned into a space, because in Hebrew they sit inside a word rather than
 * between two. ראשל"צ, ת"א and כפ”ס are each one word, and spacing the mark
 * would split them into two tokens -- which is exactly what broke the
 * abbreviation table on the first run of the tests: "ראשל"צ" became
 * "ראשל" + "צ", so the lookup for "ראשלצ" never fired and Cinema City's Rishon
 * branch stayed unreachable by its real name.
 *
 * Both ASCII and curly forms, because the same row of the same table carries
 * both: the name uses ASCII " and the address uses a curly ”.
 *
 * The full stop is deliberately NOT in here. It is intra-word in a Hebrew
 * abbreviation like ת.א. but between words in an English title, and deleting
 * it would quietly make "Mr. Nobody" unfindable as "mr nobody". No row in the
 * catalogue writes its abbreviation with stops, so the English case wins.
 */
const MARKS_RE = /['"‘’“”׳״]/g;

/**
 * Everything else that is not a letter or a digit becomes a space. Deliberately
 * broader than a punctuation list: it folds the hyphen in "כפר-סבא", the comma
 * in every address and the full stop, all with one rule. \p{L} keeps Hebrew,
 * Cyrillic and Arabic letters, which the catalogue all contains.
 */
const NON_WORD_RE = /[^\p{L}\p{N}]+/gu;

/**
 * Longest query accepted. Not a security boundary -- the value is never
 * interpolated into anything -- but an input with no ceiling is a free way to
 * make the filter do pointless work on every keystroke, and no real title or
 * city is close to this.
 */
export const MAX_QUERY_LENGTH = 80;

/**
 * City abbreviations the chains actually publish, expanded so that searching
 * the full name finds them.
 *
 * Applied to the stored text, not to the query, which covers both directions at
 * once: expanding the haystack's "ראשלצ" to also contain "ראשון לציון" means a
 * user typing either one matches, with a single rule.
 *
 * Matched per token rather than as a substring, so a short abbreviation cannot
 * fire from the middle of an unrelated word -- "תא" is also an ordinary Hebrew
 * word, and substring-matching it would expand any name containing those two
 * letters into "תל אביב".
 *
 * A Map rather than an object literal, because the keys are derived from stored
 * text and an object would answer a lookup for "__proto__" or "constructor"
 * with something inherited and truthy from Object.prototype. A Map has no
 * prototype chain to walk into, so an unknown token is simply undefined.
 */
const CITY_ABBREVIATIONS = new Map<string, string>([
  ['תא', 'תל אביב'],
  ['ראשלצ', 'ראשון לציון'],
  ['רלצ', 'ראשון לציון'],
  ['כפס', 'כפר סבא'],
  ['פת', 'פתח תקוה פתח תקווה'],
  ['בש', 'באר שבע'],
  ['רג', 'רמת גן'],
  ['קמוצקין', 'קרית מוצקין'],
]);

/**
 * Fold a string to its comparable form: no niqqud, no final letter forms, no
 * punctuation, single-spaced, lowercase.
 *
 * Applied to BOTH the query and the stored text, which is the only way the
 * folds above can help -- normalising one side only would make "אדם" stop
 * matching the thing it used to match.
 */
export function normalizeForSearch(value: string | null | undefined): string {
  if (!value) return '';
  return value
    .normalize('NFKD')
    .replace(NIQQUD_RE, '')
    .replace(FINAL_FORMS_RE, (letter) => FINAL_FORMS[letter] ?? letter)
    // Marks close up, separators open out. Order matters: doing it the other
    // way round would have already split ראשל"צ before the deletion could run.
    .replace(MARKS_RE, '')
    .replace(NON_WORD_RE, ' ')
    .trim()
    .toLowerCase();
}

/**
 * Split a raw query into the tokens that must all be present.
 *
 * Returns [] for a query that is empty or pure punctuation, and every caller
 * reads that as "no filter" rather than "match nothing" -- typing a lone space
 * or a lone comma should show the full list, not an empty screen.
 */
export function queryTokens(raw: string): string[] {
  return normalizeForSearch(raw.slice(0, MAX_QUERY_LENGTH))
    .split(' ')
    .filter(Boolean);
}

/** Whether every token appears in an already-normalised haystack. */
export function matchesTokens(tokens: string[], haystack: string): boolean {
  if (tokens.length === 0) return true;
  return tokens.every((token) => haystack.includes(token));
}

/** Searchable text for a film: both titles, so Hebrew or English works. */
export function movieHaystack(movie: {
  title_he: string;
  title_en?: string | null;
}): string {
  return `${normalizeForSearch(movie.title_he)} ${normalizeForSearch(movie.title_en)}`;
}

/**
 * Searchable text for a theatre: its name, its address, and the expansion of
 * any abbreviation in either.
 *
 * Both fields are needed and neither is sufficient. Hot Cinema names its venues
 * after the bare city ("חיפה") and publishes an address for one of eleven, so
 * the name is the only handle there. Movieland does the reverse for its Tel Aviv
 * sites -- "הצוק ת\"א" is only findable as "תל אביב" through the address, or
 * through the abbreviation table.
 */
export function theatreHaystack(theatre: {
  name: string;
  address?: string | null;
}): string {
  const base = `${normalizeForSearch(theatre.name)} ${normalizeForSearch(theatre.address)}`;
  const expansions = base
    .split(' ')
    .map((token) => CITY_ABBREVIATIONS.get(token))
    // Normalised on the way in, not stored pre-folded. The table is written in
    // ordinary Hebrew so it stays editable, but appending it raw would put
    // unfolded text into an otherwise folded haystack -- and every expansion
    // ending in a final letter would then never match. ראשון לציון and רמת גן
    // both end in ן, so that is most of the table: the query folds to
    // "ראשונ לציונ" while the haystack still said "ראשון לציון".
    .map((expansion) => (expansion === undefined ? '' : normalizeForSearch(expansion)))
    .filter(Boolean);
  return expansions.length > 0 ? `${base} ${expansions.join(' ')}` : base;
}

/** Films whose Hebrew or English title matches. Unfiltered for an empty query. */
export function filterMovies<T extends { title_he: string; title_en?: string | null }>(
  movies: T[],
  query: string,
): T[] {
  const tokens = queryTokens(query);
  if (tokens.length === 0) return movies;
  return movies.filter((movie) => matchesTokens(tokens, movieHaystack(movie)));
}

/** Theatres whose name or address matches. Unfiltered for an empty query. */
export function filterTheatres<T extends { name: string; address?: string | null }>(
  theatres: T[],
  query: string,
): T[] {
  const tokens = queryTokens(query);
  if (tokens.length === 0) return theatres;
  return theatres.filter((theatre) => matchesTokens(tokens, theatreHaystack(theatre)));
}

/**
 * Rendering the digital release date.
 *
 * The app states the fact and nothing else. It does not say "last chance", it
 * does not count down, and it does not suggest waiting — whether two days is
 * worth waiting for depends on who is asking, and that is not a judgment a
 * showtimes listing is entitled to make.
 *
 * ## Why only upcoming dates carry a date
 *
 * The date answers exactly one question: how long until I can watch this at
 * home. For a film that is already out there is nothing to wait for, so the
 * date answers nothing — knowing Shrek reached digital on some particular
 * Tuesday changes no decision anyone is making tonight. It is available. That
 * is the whole of the useful content.
 *
 *     upcoming      דיגיטל 17/11/2026
 *     already out   זמין בדיגיטל
 *
 * This also disposes of a real accuracy problem rather than papering over it.
 * Dates for older films come from TMDb rather than the curated release
 * channel, and TMDb logs every digital release including the day a film
 * arrived on a new streaming service years later: Toy Story (1995) reports
 * 2019-11-12, which is Disney+ launch week; Spirited Away (2001) reports
 * 2019-12-17; Shrek (2001) reports 2018-02-01, a French platform entry. Every
 * one is a real digital release and not one is when the film became available
 * at home. Since no past date is ever printed, none of them can mislead — the
 * only claim made about an old film is that it is available, which is exactly
 * what those records do establish.
 */

/** ISO (YYYY-MM-DD) -> DD/MM/YYYY, which is how dates are written in Israel. */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-');
  if (!year || !month || !day) return iso;
  return `${day}/${month}/${year}`;
}

/** Today in the viewer's own timezone, as YYYY-MM-DD. */
function localToday(): string {
  const now = new Date();
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
  ].join('-');
}

/**
 * The digital line for a film, or null when there is nothing to say.
 *
 * Compared as whole days against the viewer's local date, not as timestamps:
 * a release date is a day, and treating it as midnight would call a film
 * released today "not out yet" for the whole of the day it actually lands.
 */
export function digitalLabel(iso: string | null | undefined): string | null {
  // Shape-checked first, because the comparison below is a STRING comparison.
  // "not-a-date" > "2026-11-09" is true — 'n' sorts after '2' — so an
  // unchecked malformed value sails through as a future release and renders
  // as "דיגיטל date/a/not". Saying nothing is the only honest answer to a
  // value we cannot read: it is no more evidence of availability than it is
  // of a release date.
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;

  return iso > localToday()
    ? `דיגיטל ${formatDate(iso)}`
    : 'זמין בדיגיטל';
}

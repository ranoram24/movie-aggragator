/**
 * Turning a screening into a calendar event.
 *
 * Two routes out, and the file is built by the server rather than here —
 * see screeningIcsUrl for why that is the difference between "opens your
 * calendar" and "appears in your Downloads folder".
 *
 * ## Two routes, and why neither alone is enough
 *
 * AN INTENT opens the phone's own calendar on a filled-in composer, which is
 * what people mean by "add it to my calendar". It cannot carry a reminder.
 * A FILE can carry the reminder and nothing else can, but on Android it
 * arrives as a download rather than opening anything.
 *
 * A Google Calendar prefill link was tried as a third option and removed. It
 * has the intent route's limitation — no parameter for an alarm — without its
 * advantage, since it reaches one particular calendar rather than whichever
 * one the person uses, and the Android app intercepted the link and showed an
 * empty day instead of a composer.
 *
 * ## Floating local time, deliberately
 *
 * Showtimes are naive local Israeli times, and these events are written the
 * same way: no Z suffix, no TZID, which iCalendar calls a floating time and
 * every client reads in the viewer's own timezone. For a cinema ticket in
 * Israel held by a phone set to Israeli time — essentially the whole audience —
 * that is exactly right, and it avoids both alternatives being worse:
 *
 *   * Converting to UTC bakes in a DST offset that we would have to compute
 *     for the screening's date, not today's, and Israel switches in late March
 *     and late October, right across a nine-day booking window.
 *   * TZID=Asia/Jerusalem is the technically correct answer but RFC 5545 wants
 *     an accompanying VTIMEZONE block spelling out the DST rules, and clients
 *     that enforce that would reject the file.
 *
 * The cost is that someone who adds the event and then flies abroad sees it at
 * the local clock time there. They have also missed the film.
 */

/** Everything the prompt shows, and what the two routes are built from. */
export interface ScreeningEvent {
  /** The card's id, as /api/movies returns it — the server resolves the rest. */
  filmId: string;
  theatreId: number;
  filmTitle: string;
  cinema: string;
  chain: string;
  address: string | null;
  /** ISO, "2026-11-12". */
  date: string;
  /** "20:20". */
  time: string;
  runtimeMinutes: number | null;
  venueType: string;
  /** Narrows the server lookup when a cinema runs two versions at one minute. */
  dubbedLanguage: string | null;
  ticketUrl: string;
}

/** Hours before the screening that the reminder fires. Mirrors calendar_ics.py. */
export const REMINDER_HOURS = 2;

/** Minutes of trailers before the feature. Mirrors calendar_ics.py. */
const ADVERTS_MINUTES = 20;

/** Used when the chain never published a runtime. */
const FALLBACK_MINUTES = 120;

/** How long the event blocks out. Shown in the prompt before you commit. */
export function durationMinutes(runtimeMinutes: number | null): number {
  return runtimeMinutes && runtimeMinutes > 0
    ? runtimeMinutes + ADVERTS_MINUTES
    : FALLBACK_MINUTES;
}

/** "2026-11-12" + "20:20" -> "2026-11-12T20:20:00", as the API stores it. */
function showtimeIso(date: string, time: string): string {
  return `${date}T${time}:00`;
}

/**
 * The URL of this screening's calendar file.
 *
 * A link, not a download. The file used to be assembled here and handed over
 * as a Blob with a download attribute, and a blob + download is ALWAYS a file
 * save: on a phone it lands in Downloads and has to be found, tapped and
 * opened with something before a calendar ever sees it. Served from this URL
 * as text/calendar with an inline disposition, the browser treats it as a
 * document and hands it to whatever app claims the type — on Android, the
 * calendar's own import screen.
 *
 * Only ids go in the query string. The event's text — title, cinema, address,
 * runtime, ticket link — is read from the database by the endpoint, so nothing
 * typed into a URL can end up inside a calendar entry. See api_calendar.py.
 */
export function screeningIcsUrl(event: ScreeningEvent): string {
  const params = new URLSearchParams({
    film: event.filmId,
    theatre: String(event.theatreId),
    at: showtimeIso(event.date, event.time),
    venue_type: event.venueType,
  });
  if (event.dubbedLanguage) params.set('dub', event.dubbedLanguage);
  return `/api/screening.ics?${params.toString()}`;
}

/**
 * Whether `intent://` will work: Android AND a Chromium-based browser.
 *
 * Both halves are load-bearing, and the second was missing once. intent:// is
 * a CHROMIUM feature, not an Android one — Gecko never implemented it.
 * Offering the link to Firefox for Android did not quietly do nothing, which
 * is what a dead scheme ought to do; following it took the tab to about:blank
 * and left the app as a stale document with no script running.
 *
 * Chrome, Samsung Internet and Edge on Android are all Chromium and all
 * support it. Firefox is excluded explicitly as well as by the Chrome test,
 * because the cost of being wrong here is a destroyed page rather than a
 * missing button.
 */
export function supportsIntentUrls(userAgent: string): boolean {
  if (!/android/i.test(userAgent)) return false;
  if (/firefox|fxios/i.test(userAgent)) return false;
  return /chrome\/|samsungbrowser|edga/i.test(userAgent);
}

/**
 * The same .ics URL, wrapped as an Android VIEW intent.
 *
 * This is the one route that gets both halves at once, and it took three
 * attempts to find. The problem is that the two things wanted — the calendar
 * app opening, and the two-hour reminder — kept living in different places:
 *
 *   * A download carries the alarm and opens nothing. Chrome saves the file
 *     whatever Content-Disposition says, because it cannot render the type.
 *   * ACTION_INSERT opens the calendar composer and cannot carry an alarm;
 *     there is no reminder extra on that intent.
 *   * A Google Calendar prefill link has the same gap, and reaches one
 *     particular calendar rather than the device's.
 *
 * ACTION_VIEW on the URL, typed as text/calendar, asks Android to open the
 * file with whatever handles calendars — so the handler fetches the .ics
 * itself, VALARM and all. The alarm survives because the app is reading the
 * real file rather than being handed a list of fields.
 *
 * browser_fallback_url is the same URL unwrapped, so a device with nothing
 * registered for text/calendar gets today's behaviour — a download — instead
 * of a dead link. This is strictly an improvement or a no-op, never worse.
 */
export function icsIntentUrl(absoluteIcsUrl: string): string {
  const url = new URL(absoluteIcsUrl);
  // intent:// replaces the scheme in the URI, so it is restored as a field.
  // Everything after it up to the '#' is the data URI the intent carries.
  const withoutScheme = `${url.host}${url.pathname}${url.search}`;
  return (
    `intent://${withoutScheme}` +
    `#Intent;scheme=${url.protocol.replace(':', '')}` +
    ';action=android.intent.action.VIEW' +
    ';type=text/calendar' +
    `;S.browser_fallback_url=${encodeURIComponent(absoluteIcsUrl)}` +
    ';end'
  );
}

/**
 * Where the single "add to calendar" button points.
 *
 * One button, because every route ends at the same .ics — the only difference
 * is whether Android is asked to open it or the browser is left to save it,
 * and that is not a choice worth putting in front of someone.
 */
export function addToCalendarUrl(
  event: ScreeningEvent,
  userAgent: string,
  origin: string,
): string {
  const relative = screeningIcsUrl(event);
  if (!supportsIntentUrls(userAgent)) return relative;
  return icsIntentUrl(new URL(relative, origin).toString());
}

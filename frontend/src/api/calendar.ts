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
 * An Android intent that opens the device's own calendar on a new event,
 * already filled in.
 *
 * ## Why this exists, after two attempts that did not work
 *
 * The goal is the phone's calendar opening on a composer, not a file arriving
 * somewhere. Two routes were tried and both fail on Android:
 *
 *   1. A Blob with a download attribute. A blob + download is BY DEFINITION a
 *      file save; the browser is never given the option to hand it anywhere.
 *   2. The same bytes served over HTTP as text/calendar with
 *      Content-Disposition: inline. This is the documented way to say "display
 *      this, do not save it" — and Chrome on Android downloads it anyway,
 *      because it cannot render the type. Observed on a real device: a
 *      "one file downloaded" bar with an Open button, which is precisely the
 *      step this was meant to remove.
 *
 * An intent URI is not a document at all. It is a request to Android to start
 * an activity, so there is nothing for the browser to download: ACTION_INSERT
 * against the events MIME type is the standard "create an event" intent, and
 * whatever the user has set as their calendar handles it.
 *
 * ## What it cannot carry
 *
 * The reminder. ACTION_INSERT takes a title, a location, a description and a
 * time range, and there is no extra for an alarm — the event gets whatever
 * default the calendar applies. That is the same limit the Google prefill
 * screen has, and it is why the .ics route stays: it is the only one of the
 * three that can express TRIGGER:-PT2H, at the cost of being a file.
 *
 * ## Times
 *
 * Real epoch milliseconds, unlike the floating times in the .ics, because an
 * intent extra is an instant rather than a wall clock. Built with the local
 * Date constructor, so it resolves against the device's timezone — correct for
 * a cinema ticket in Israel held by a phone set to Israeli time, and the same
 * assumption the floating .ics makes.
 */
export function calendarIntentUrl(event: ScreeningEvent, fallbackUrl: string): string {
  const [year, month, day] = event.date.split('-').map(Number);
  const [hour, minute] = event.time.split(':').map(Number);
  const begin = new Date(year, month - 1, day, hour, minute).getTime();
  const end = begin + durationMinutes(event.runtimeMinutes) * 60_000;

  const description = [
    event.chain,
    event.venueType !== 'regular' ? event.venueType : null,
    event.ticketUrl,
  ]
    .filter(Boolean)
    .join('\n');

  // Every value is percent-encoded: ';' and '=' are the intent URI's own
  // separators, so an unencoded one in a film title would end the extras list
  // early and silently drop the rest of the event.
  const extras = [
    `S.title=${encodeURIComponent(`${event.filmTitle} — ${event.cinema}`)}`,
    `S.eventLocation=${encodeURIComponent(
      event.address ? `${event.cinema}, ${event.address}` : event.cinema,
    )}`,
    `S.description=${encodeURIComponent(description)}`,
    `l.beginTime=${begin}`,
    `l.endTime=${end}`,
    // If nothing on the device handles the intent, Chrome goes here instead of
    // failing silently — so the worst case is the file route, not nothing.
    `S.browser_fallback_url=${encodeURIComponent(fallbackUrl)}`,
  ].join(';');

  return `intent://#Intent;action=android.intent.action.INSERT;type=vnd.android.cursor.dir/event;${extras};end`;
}

/**
 * Whether to use the intent route. Android only — `intent://` is a Chrome on
 * Android scheme and does nothing anywhere else, so this is one of the few
 * places where sniffing the agent is the correct test rather than a shortcut.
 * Takes the string explicitly so it can be tested without a browser.
 */
export function isAndroid(userAgent: string): boolean {
  return /android/i.test(userAgent);
}

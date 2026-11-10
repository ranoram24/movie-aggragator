/**
 * Turning a screening into a calendar event.
 *
 * Two routes out, and the file is built by the server rather than here —
 * see screeningIcsUrl for why that is the difference between "opens your
 * calendar" and "appears in your Downloads folder".
 *
 * ## Why an .ics file and not a Google Calendar link
 *
 * The obvious implementation is a link to calendar.google.com/calendar/render,
 * which prefills a new event and needs no file handling at all. It cannot be
 * used here: that URL accepts a title, a time, a location and a description,
 * and has no parameter for a reminder. The reminder is the point of the
 * feature — an event with no alarm is a note, not a prompt to leave the house —
 * so the only option that carries one is a real iCalendar file with a VALARM.
 *
 * It is also better in every other way for this case: no account, no network,
 * no third party, and it works with whatever calendar the person actually uses.
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
 * A Google Calendar "new event" page, prefilled.
 *
 * The fast route: two taps and the event is in the Google account, synced to
 * every device, with no file to find in a downloads folder.
 *
 * WHAT IT CANNOT DO IS THE REMINDER. This prefill interface accepts a title,
 * a time range, a location, a description, a timezone, guests and a recurrence
 * rule — and has no parameter for an alarm of any kind. An event created this
 * way gets whatever default notification the account is configured with,
 * typically ten or thirty minutes. That is why the file route exists beside
 * this: it is the only one of the two that can carry TRIGGER:-PT2H.
 *
 * The timezone IS handled properly here, better than in the file. Passing
 * naive times plus ctz=Asia/Jerusalem makes Google resolve the offset for the
 * screening's own date, DST included, which is exactly what the .ics has to
 * leave floating.
 *
 * ## /r/eventedit rather than /render
 *
 * Both are prefill entry points and /render is the one usually quoted. On a
 * phone it is the wrong one: the Google Calendar Android app registers itself
 * for calendar.google.com links, intercepts /render, and handles it by jumping
 * the grid to the date and discarding every other parameter. Reported from a
 * real device — the app opened on the screening's day with no event and no
 * composer, which looks exactly like the feature being broken.
 *
 * /r/eventedit is the editor's own route and is the one the app understands as
 * "open a new event with these fields". It is still a Google interface we do
 * not control, which is the honest reason the file route stays and is listed
 * first: that one does not depend on how somebody else's app routes a link.
 */
export function googleCalendarUrl(event: ScreeningEvent): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  const stamp = (date: string, time: string, addMinutes = 0) => {
    const [year, month, day] = date.split('-').map(Number);
    const [hour, minute] = time.split(':').map(Number);
    // Through Date.UTC on purpose: these are naive times that Google will
    // resolve with ctz, and doing the sum in the running device's own timezone
    // would let ITS dst transition shift a result that has nothing to do
    // with it.
    const m = new Date(Date.UTC(year, month - 1, day, hour, minute) + addMinutes * 60_000);
    return (
      `${m.getUTCFullYear()}${pad(m.getUTCMonth() + 1)}${pad(m.getUTCDate())}` +
      `T${pad(m.getUTCHours())}${pad(m.getUTCMinutes())}00`
    );
  };

  const start = stamp(event.date, event.time);
  const end = stamp(event.date, event.time, durationMinutes(event.runtimeMinutes));

  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: `${event.filmTitle} — ${event.cinema}`,
    dates: `${start}/${end}`,
    location: event.address ? `${event.cinema}, ${event.address}` : event.cinema,
    details: [
      event.chain,
      event.venueType !== 'regular' ? event.venueType : null,
      event.ticketUrl,
    ]
      .filter(Boolean)
      .join('\n'),
    ctz: 'Asia/Jerusalem',
  });

  return `https://calendar.google.com/calendar/u/0/r/eventedit?${params.toString()}`;
}

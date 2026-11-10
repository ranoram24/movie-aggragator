/**
 * Turning a screening into a calendar event.
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

/** Everything an event needs, gathered from the three components that know it. */
export interface ScreeningEvent {
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
  ticketUrl: string;
}

/** Hours before the screening that the reminder fires. */
export const REMINDER_HOURS = 2;

/**
 * Minutes of trailers and advertising before the feature starts.
 *
 * The listed time is when the session begins, not when the film does, and
 * Israeli cinemas run roughly this long before it. It is added to the runtime
 * rather than the start so the event covers the time you are actually in the
 * building — the question a calendar block answers is "when am I free again".
 */
const ADVERTS_MINUTES = 20;

/** Used when the chain never published a runtime. */
const FALLBACK_MINUTES = 120;

/**
 * Escape a TEXT value. Backslash first, or the escapes we add get escaped.
 * Film titles genuinely contain commas and semicolons, both of which are
 * value separators in iCalendar.
 */
function escapeText(value: string): string {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n');
}

/**
 * Fold a content line to 75 octets, per RFC 5545.
 *
 * Measured in BYTES, not characters, which is why this cannot be a simple
 * slice: Hebrew is two bytes per letter in UTF-8, so a title in Hebrew reaches
 * the limit in half the characters an English one would, and splitting by
 * character count would either fold too late or cut a letter in half. Iterating
 * by code point and measuring each one keeps multi-byte characters whole.
 */
function fold(line: string): string {
  const encoder = new TextEncoder();
  if (encoder.encode(line).length <= 75) return line;

  const parts: string[] = [];
  let current = '';
  let bytes = 0;
  for (const char of line) {
    const size = encoder.encode(char).length;
    // A continuation line begins with a space, which counts toward its 75.
    const limit = parts.length === 0 ? 75 : 74;
    if (bytes + size > limit) {
      parts.push(current);
      current = '';
      bytes = 0;
    }
    current += char;
    bytes += size;
  }
  if (current) parts.push(current);
  return parts.join('\r\n ');
}

/** "2026-11-12" + "20:20" -> "20261112T202000" (floating, see the header). */
function localStamp(date: string, time: string): string {
  return `${date.replace(/-/g, '')}T${time.replace(':', '')}00`;
}

/**
 * Add minutes to a local date/time, returning the same floating format.
 *
 * Arithmetic goes through Date.UTC on purpose. These are floating times with
 * no zone, and doing the sum with a local-timezone Date would let the running
 * device's own DST transition shift a result that has nothing to do with it.
 */
function addMinutes(date: string, time: string, minutes: number): string {
  const [year, month, day] = date.split('-').map(Number);
  const [hour, minute] = time.split(':').map(Number);
  const moment = new Date(Date.UTC(year, month - 1, day, hour, minute) + minutes * 60_000);

  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${moment.getUTCFullYear()}${pad(moment.getUTCMonth() + 1)}${pad(moment.getUTCDate())}` +
    `T${pad(moment.getUTCHours())}${pad(moment.getUTCMinutes())}00`
  );
}

/** FNV-1a, for a short stable id. Not security; just needs to not collide. */
function hash(value: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < value.length; i += 1) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

/** UTC timestamp for DTSTAMP, which must be absolute. */
function utcStamp(at: Date): string {
  return `${at.toISOString().replace(/[-:]/g, '').split('.')[0]}Z`;
}

/** How long to block out: the feature plus the adverts in front of it. */
export function durationMinutes(runtimeMinutes: number | null): number {
  return runtimeMinutes && runtimeMinutes > 0
    ? runtimeMinutes + ADVERTS_MINUTES
    : FALLBACK_MINUTES;
}

/**
 * The whole .ics document for one screening.
 *
 * Pure, so it is testable without a DOM — see frontend/tests/calendar.test.ts.
 * `now` is injectable for the same reason.
 */
export function buildIcs(event: ScreeningEvent, now: Date = new Date()): string {
  const start = localStamp(event.date, event.time);
  const end = addMinutes(event.date, event.time, durationMinutes(event.runtimeMinutes));

  const summary = `${event.filmTitle} — ${event.cinema}`;
  const location = event.address ? `${event.cinema}, ${event.address}` : event.cinema;

  const description = [
    event.chain,
    event.venueType !== 'regular' ? event.venueType : null,
    event.ticketUrl,
  ]
    .filter(Boolean)
    .join('\n');

  // Deterministic, so re-adding the same screening updates the existing event
  // in clients that honour UID rather than creating a second one.
  const uid = `${start}-${hash(event.ticketUrl)}@on-cinema-now.fly.dev`;

  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//On Cinema//Screenings//HE',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    `UID:${uid}`,
    `DTSTAMP:${utcStamp(now)}`,
    `DTSTART:${start}`,
    `DTEND:${end}`,
    `SUMMARY:${escapeText(summary)}`,
    `LOCATION:${escapeText(location)}`,
    `DESCRIPTION:${escapeText(description)}`,
    'BEGIN:VALARM',
    // The reason this is a file and not a Google Calendar link.
    `TRIGGER:-PT${REMINDER_HOURS}H`,
    'ACTION:DISPLAY',
    `DESCRIPTION:${escapeText(summary)}`,
    'END:VALARM',
    'END:VEVENT',
    'END:VCALENDAR',
  ];

  // CRLF is required by the spec, and some clients genuinely reject LF-only.
  return `${lines.map(fold).join('\r\n')}\r\n`;
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
 * typically ten or thirty minutes. That is why downloadIcs still exists beside
 * this: the file is the only one of the two that can carry TRIGGER:-PT2H.
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
  const start = localStamp(event.date, event.time);
  const end = addMinutes(event.date, event.time, durationMinutes(event.runtimeMinutes));

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

/** A filename that will not upset a filesystem, derived from the film. */
export function icsFilename(event: ScreeningEvent): string {
  const slug = `${event.filmTitle}-${event.date}-${event.time}`
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-|-$/g, '');
  return `${slug || 'screening'}.ics`;
}

/**
 * Hand the file to the browser.
 *
 * A Blob and a synthetic click, which is what makes the phone offer to open it
 * in the calendar app. The object URL is revoked on a timer rather than
 * immediately: Safari reads it asynchronously after the click returns, and
 * revoking straight away produces a silently empty download.
 */
export function downloadIcs(event: ScreeningEvent): void {
  const blob = new Blob([buildIcs(event)], {
    type: 'text/calendar;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = url;
  link.download = icsFilename(event);
  link.rel = 'noopener';
  document.body.appendChild(link);
  link.click();
  link.remove();

  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

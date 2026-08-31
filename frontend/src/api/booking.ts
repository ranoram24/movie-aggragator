/**
 * A note for chains whose showtime link does not open that screening's
 * checkout directly.
 *
 * Everywhere else a time is a deep link: tap 19:20 and the chain's checkout
 * opens on 19:20, already selected. Planet is the exception -- its per-screening
 * booking links lead to a host that refuses every request, so its times open
 * the film's own page with the cinema and date preselected, and the time has to
 * be chosen once more there.
 *
 * Worth saying out loud on the card. Someone who taps a time and lands on a
 * list of times has no way to tell whether the app sent them to the wrong place
 * or the site simply works that way, and that doubt is what makes a booking
 * feel unsafe to complete.
 *
 * Keyed by the chain's display name, the same identity ChainFilter and
 * CHAIN_IN_HEBREW already use.
 */

const INDIRECT_BOOKING: Record<string, string> = {
  Planet: 'בפלאנט הקישור נפתח בעמוד הסרט — בוחרים שם את השעה',
};

export function bookingNote(chain: string): string | null {
  return INDIRECT_BOOKING[chain] ?? null;
}

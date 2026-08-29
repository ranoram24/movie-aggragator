/**
 * Builds a Google Maps directions link for a theatre.
 *
 * The destination is the cinema's NAME, not its address. A cinema is a place
 * Maps already knows, so "סינמה סיטי נתניה" lands on the venue itself, whereas
 * a street address only gets you to the right building and our own geocoded
 * coordinates are sometimes only a town-centre approximation.
 *
 * The catch is that not every chain names its venues usefully. Cinema City,
 * Planet and Lev all include the chain ("סינמה סיטי נתניה"), but Hot Cinema and
 * Movieland name theirs after the city alone — a bare "חיפה" would navigate to
 * Haifa rather than to a cinema in it. Those get the chain prefixed, in Hebrew,
 * since that is how the venues are actually listed on Maps here.
 *
 * The origin is passed when we know it and omitted otherwise, in which case
 * Maps uses the device's own current location — usually fresher than whatever
 * we captured.
 */

import type { Coords, Theatre } from './types';

/** Chain key/display name -> how the chain is written on Maps in Israel. */
const CHAIN_IN_HEBREW: Record<string, string> = {
  'Cinema City': 'סינמה סיטי',
  Movieland: 'מובילנד',
  Planet: 'פלאנט',
  'Hot Cinema': 'הוט סינמה',
  'Lev Cinema': 'לב',
};

function destinationFor(theatre: Theatre): string {
  const chain = CHAIN_IN_HEBREW[theatre.chain] ?? theatre.chain;
  const name = theatre.name.trim();

  // Already says which chain it is — searching "סינמה סיטי סינמה סיטי נתניה"
  // would only confuse the match.
  const alreadyQualified = name.includes(chain);
  return alreadyQualified ? name : `${chain} ${name}`;
}

export function directionsUrl(theatre: Theatre, from: Coords | null): string {
  const params = new URLSearchParams({ api: '1', travelmode: 'driving' });
  params.set('destination', destinationFor(theatre));

  if (from) {
    params.set('origin', `${from.lat},${from.lon}`);
  }

  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

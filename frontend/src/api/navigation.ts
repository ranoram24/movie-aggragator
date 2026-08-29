/**
 * Builds a Google Maps directions link for a theatre.
 *
 * Which destination to use is not obvious, because the chains give us
 * different things and the best answer differs:
 *
 *   - An address, where we have one, beats our own coordinates. Google's
 *     geocoder handles Israeli addresses far better than the one we geocode
 *     with, and some of our coordinates are a town-centre fallback rather than
 *     the building — navigating to those would drop you in the wrong place.
 *   - Coordinates, where there is no address. Hot Cinema publishes almost no
 *     addresses but embeds an exact pin on each venue page, so for those the
 *     coordinate IS the building.
 *   - The name as a last resort, qualified with the chain and country so it
 *     reads as a searchable place rather than a bare word like "חיפה".
 *
 * The origin is passed when we know it and omitted otherwise, in which case
 * Maps uses the device's own current location — which is usually fresher than
 * whatever we captured anyway.
 */

import type { Coords, Theatre } from './types';

export function directionsUrl(theatre: Theatre, from: Coords | null): string {
  const params = new URLSearchParams({ api: '1', travelmode: 'driving' });

  if (theatre.address) {
    // Lead with the venue name so Maps can match the actual cinema rather
    // than just the street.
    params.set('destination', `${theatre.name} ${theatre.address}`);
  } else if (theatre.latitude !== null && theatre.longitude !== null) {
    params.set('destination', `${theatre.latitude},${theatre.longitude}`);
  } else {
    params.set('destination', `${theatre.chain} ${theatre.name}, ישראל`);
  }

  if (from) {
    params.set('origin', `${from.lat},${from.lon}`);
  }

  return `https://www.google.com/maps/dir/?${params.toString()}`;
}

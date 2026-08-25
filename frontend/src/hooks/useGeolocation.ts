/**
 * Location permission, with every failure path treated as normal.
 *
 * The important property here is that the app NEVER waits on this. The browse
 * screen renders immediately in 'prompt' state and fetches without coords;
 * if permission is granted later, the coords arrive and the list re-sorts.
 * Denial, an insecure origin, a timeout, or a browser with no geolocation at
 * all all land in the same place: status settles, coords stay null, and the
 * caller falls back to non-distance sorting.
 */

import { useCallback, useEffect, useState } from 'react';
import type { Coords } from '../api/types';

export type GeoStatus =
  | 'prompt'        // asking, or about to
  | 'granted'       // coords available
  | 'denied'        // user said no
  | 'unavailable';  // no geolocation API, insecure origin, timeout, or error

export interface GeolocationState {
  coords: Coords | null;
  status: GeoStatus;
  /** Re-ask. Only meaningful after 'denied'/'unavailable'; browsers may ignore it. */
  retry: () => void;
}

const GEO_OPTIONS: PositionOptions = {
  enableHighAccuracy: false, // city-level is plenty for "which cinema is near me"
  timeout: 10_000,
  maximumAge: 5 * 60 * 1000, // a 5-minute-old fix is fine; avoids a cold GPS wait
};

export function useGeolocation(): GeolocationState {
  const [coords, setCoords] = useState<Coords | null>(null);
  const [status, setStatus] = useState<GeoStatus>('prompt');

  const request = useCallback(() => {
    // navigator.geolocation is undefined on insecure origins in some browsers.
    if (!('geolocation' in navigator)) {
      setStatus('unavailable');
      return;
    }

    setStatus('prompt');
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
        });
        setStatus('granted');
      },
      (error) => {
        // Distinguish "said no" from "couldn't", because only the first is
        // worth a re-ask affordance.
        setStatus(error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable');
      },
      GEO_OPTIONS,
    );
  }, []);

  useEffect(() => {
    request();
  }, [request]);

  return { coords, status, retry: request };
}

/** One film's detail, including every theatre showing it. */

import { useCallback, useEffect, useState } from 'react';
import { fetchMovie } from '../api/client';
import type { Coords, MovieDetail } from '../api/types';

interface UseMovieResult {
  movie: MovieDetail | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useMovie(
  id: string | undefined,
  coords: Coords | null,
  chains: string[] = [],
): UseMovieResult {
  const [movie, setMovie] = useState<MovieDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const lat = coords?.lat ?? null;
  const lon = coords?.lon ?? null;
  const chainKey = chains.slice().sort().join(',');

  const load = useCallback(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchMovie(
      id,
      lat !== null && lon !== null ? { lat, lon } : null,
      chainKey ? chainKey.split(',') : [],
    )
      .then((data) => {
        if (!cancelled) setMovie(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id, lat, lon, chainKey]);

  useEffect(() => load(), [load]);

  return { movie, loading, error, reload: load };
}

/**
 * Films for the browse screen.
 *
 * Deliberately does NOT wait for the location permission prompt to resolve:
 * it fetches immediately with whatever coords exist (usually none on first
 * paint), then refetches once coords arrive so the list re-sorts by distance.
 * Waiting would leave the screen blank behind a permission dialog.
 */

import { useCallback, useEffect, useState } from 'react';
import { fetchMovies } from '../api/client';
import type { Coords, MovieSummary } from '../api/types';

interface UseMoviesResult {
  movies: MovieSummary[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useMovies(coords: Coords | null, chains: string[] = []): UseMoviesResult {
  const [movies, setMovies] = useState<MovieSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Depend on the primitive values, not the object: a new {lat,lon} identity
  // with identical numbers would otherwise refetch on every render.
  const lat = coords?.lat ?? null;
  const lon = coords?.lon ?? null;
  // Same reason as lat/lon: depend on a stable primitive, not the array's
  // identity, or every render would refetch.
  const chainKey = chains.slice().sort().join(',');

  const load = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchMovies(
      lat !== null && lon !== null ? { lat, lon } : null,
      chainKey ? chainKey.split(',') : [],
    )
      .then((data) => {
        if (!cancelled) setMovies(data);
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
  }, [lat, lon, chainKey]);

  useEffect(() => load(), [load]);

  return { movies, loading, error, reload: load };
}

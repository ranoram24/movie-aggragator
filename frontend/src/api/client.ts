/**
 * The only place in the app that knows the backend exists.
 *
 * Everything else goes through the hooks in src/hooks, which call these
 * functions. No component should ever call fetch() directly -- keeping it in
 * one file means a change to the API shape has exactly one place to touch.
 */

import type { Coords, MovieDetail, MovieSummary } from './types';

// In development .env points this at the separate backend on 8010 (not 8000 --
// that port is reserved). In production the API is served from the same origin
// as this page, so an empty value means "talk to wherever I'm hosted" and the
// deployed URL never has to be baked into the bundle.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || window.location.origin;

export class ApiError extends Error {
  // Declared as a normal field rather than a constructor parameter property:
  // this project builds with erasableSyntaxOnly, which rejects the shorthand
  // because it emits real code instead of being purely type-level.
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function getJson<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(path, BASE_URL);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  }

  let response: Response;
  try {
    response = await fetch(url.toString());
  } catch {
    // fetch() only rejects on network-level failure, so this is the
    // "backend isn't running" case -- worth its own message, since during
    // development it is by far the most likely cause.
    throw new ApiError(
      `Can't reach the server at ${BASE_URL}. Is the backend running?`,
    );
  }

  if (!response.ok) {
    throw new ApiError(
      response.status === 404
        ? 'Not found.'
        : `Server returned ${response.status}.`,
      response.status,
    );
  }

  return (await response.json()) as T;
}

/** Films currently playing. Pass coords to sort by distance. */
export function fetchMovies(coords: Coords | null, limit = 100): Promise<MovieSummary[]> {
  return getJson<MovieSummary[]>('/api/movies', {
    lat: coords?.lat,
    lon: coords?.lon,
    limit,
  });
}

/** One film, with every theatre showing it, from every chain.
 *  Narrowing to a chain happens in the UI -- the response already holds them
 *  all, so filtering there is instant and costs no request. */
export function fetchMovie(id: string, coords: Coords | null): Promise<MovieDetail> {
  return getJson<MovieDetail>(`/api/movies/${encodeURIComponent(id)}`, {
    lat: coords?.lat,
    lon: coords?.lon,
  });
}

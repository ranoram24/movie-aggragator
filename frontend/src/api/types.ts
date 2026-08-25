/**
 * Mirrors the FastAPI response models in api_movies.py.
 *
 * Keep these in sync with the backend by hand -- if a field goes null-able
 * there, it must become optional here, or the UI will render "undefined".
 *
 * The nullable fields are not arbitrary: a film that TMDb could not match has
 * no English title and no synopsis, and a theatre that could not be geocoded
 * has no distance. Both cases are normal and must render, not crash.
 */

/** "m123" for a TMDb-matched film (merged across chains), "l456" for an unmatched listing. */
export type FilmId = string;

export interface MovieSummary {
  id: FilmId;
  title_he: string;
  title_en: string | null;
  poster_url: string | null;
  theatre_count: number;
  /** null when location is unavailable, or when no showing theatre is geocoded. */
  nearest_km: number | null;
  chains: string[];
}

export interface Showtime {
  /** "20:20" */
  time: string;
  /** "regular" | "VIP" | "IMAX" | "4DX" | "SCREENX" */
  venue_type: string;
  /** Deep link to this exact screening's checkout. Never null. */
  ticket_url: string;

  /** ISO-639-1. null when the film plays in its original audio. */
  dubbed_language: string | null;
  original_language: string | null;
  subtitled_language: string | null;
  /** What the audience hears: the dub if there is one, else the original. */
  spoken_language: string | null;
}

export interface Chain {
  key: string;
  name: string;
}

export interface DateGroup {
  /** "2026-08-25" */
  date: string;
  /** Server-computed: "Today" | "Tomorrow" | "Thu 27 Aug" */
  label: string;
  showtimes: Showtime[];
}

export interface Theatre {
  id: number;
  name: string;
  chain: string;
  address: string | null;
  distance_km: number | null;
  dates: DateGroup[];
}

export interface MovieDetail {
  id: FilmId;
  title_he: string;
  title_en: string | null;
  poster_url: string | null;
  /** Only present for TMDb-matched films. */
  overview: string | null;
  genre: string | null;
  runtime_minutes: number | null;
  age_rating: string | null;
  theatres: Theatre[];
}

export interface Coords {
  lat: number;
  lon: number;
}

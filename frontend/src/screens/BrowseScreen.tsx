/**
 * "On Cinema" — the app's only tab in v1.
 *
 * Deliberately unfiltered: one card per film, merging every chain that shows
 * it. Splitting the grid by chain made the same movie appear several times and
 * buried the thing you actually want to know, which is "what's on near me".
 * Choosing a chain belongs on the detail screen, once you've picked a film.
 *
 * Renders immediately and fetches without coordinates, then refetches once
 * location resolves — the screen must never sit blank behind a permission
 * dialog, and must look identical-but-unsorted if permission is refused.
 */

import { useGeolocation } from '../hooks/useGeolocation';
import { useMovies } from '../hooks/useMovies';
import { MovieGrid } from '../components/MovieGrid';
import { MovieGridSkeleton } from '../components/Skeleton';
import { EmptyState, ErrorState } from '../components/ErrorState';
import './BrowseScreen.css';

export function BrowseScreen() {
  const { coords, status, retry } = useGeolocation();
  const { movies, loading, error, reload } = useMovies(coords);

  const sortedByDistance = status === 'granted' && Boolean(coords);
  const sortLabel = sortedByDistance ? 'לפי קרבה אליך' : 'לפי מספר בתי הקולנוע';

  return (
    <div className="browse">
      <header className="browse__header">
        <h1 className="browse__title">On Cinema</h1>
        <p className="browse__subtitle">
          מה מוקרן עכשיו
          <span className="browse__sep"> · </span>
          <span className="browse__sort">{sortLabel}</span>
          {/* Distances are haversine, not driving routes -- roughly 1.2x
              shorter than the road. Said once here rather than on every chip,
              and only when distances are actually on screen. */}
          {sortedByDistance && (
            <span className="browse__note"> · מרחקים בקו אווירי</span>
          )}
        </p>
      </header>

      {/* Only nudge when location would actually change the ordering, and never
          block the content behind it. */}
      {(status === 'denied' || status === 'unavailable') && !loading && (
        <button className="browse__locnudge pressable" onClick={retry}>
          <span className="browse__locnudge-icon">📍</span>
          <span>
            {status === 'denied'
              ? 'אפשר מיקום כדי לראות קולנוע קרוב אליך'
              : 'המיקום אינו זמין — מוצג לפי פופולריות'}
          </span>
        </button>
      )}

      {loading && <MovieGridSkeleton count={8} />}
      {!loading && error && <ErrorState message={error} onRetry={reload} />}
      {!loading && !error && movies.length === 0 && (
        <EmptyState message="אין הקרנות זמינות כרגע." />
      )}
      {!loading && !error && movies.length > 0 && <MovieGrid movies={movies} />}
    </div>
  );
}

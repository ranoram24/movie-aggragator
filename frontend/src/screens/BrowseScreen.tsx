/**
 * "On Cinema" — the app's only tab in v1.
 *
 * Renders immediately and fetches without coordinates, then refetches once
 * location resolves. The screen must never sit blank behind a permission
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

  const sortLabel =
    status === 'granted' && coords
      ? 'לפי קרבה אליך'
      : 'לפי מספר בתי הקולנוע';

  return (
    <div className="browse">
      <header className="browse__header">
        <h1 className="browse__title">On Cinema</h1>
        <p className="browse__subtitle">
          מה מוקרן עכשיו
          <span className="browse__sep"> · </span>
          <span className="browse__sort">{sortLabel}</span>
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

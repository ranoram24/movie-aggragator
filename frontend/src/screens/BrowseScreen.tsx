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
 *
 * The search box filters the films already in hand rather than asking the
 * server, which is why results land on the keystroke with no debounce. That
 * only holds while the whole catalogue is in hand — see the limit in client.ts.
 */

import { useMemo, useState } from 'react';
import { useGeolocation } from '../hooks/useGeolocation';
import { useMovies } from '../hooks/useMovies';
import { filterMovies } from '../api/search';
import { MovieGrid } from '../components/MovieGrid';
import { SearchBar } from '../components/SearchBar';
import { MovieGridSkeleton } from '../components/Skeleton';
import { EmptyState, ErrorState } from '../components/ErrorState';
import './BrowseScreen.css';

export function BrowseScreen() {
  const { coords, status, retry } = useGeolocation();
  const { movies, loading, error, reload } = useMovies(coords);
  const [query, setQuery] = useState('');

  const visible = useMemo(() => filterMovies(movies, query), [movies, query]);

  const searching = query.trim().length > 0;

  // Proximity still orders the list; the kilometres themselves are not shown.
  const sortLabel =
    status === 'granted' && coords ? 'לפי קרבה אליך' : 'לפי מספר בתי הקולנוע';

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

      {/* Rendered during loading too, so the grid appearing underneath doesn't
          shove it down the page. */}
      <SearchBar
        value={query}
        onChange={setQuery}
        placeholder="חיפוש סרט — בעברית או באנגלית"
        label="חיפוש סרט"
        resultCount={loading || error ? undefined : visible.length}
        resultNoun={visible.length === 1 ? 'סרט' : 'סרטים'}
      />

      {/* Only nudge when location would actually change the ordering, and never
          block the content behind it. Pointless mid-search, where the ordering
          is not what you are looking at. */}
      {(status === 'denied' || status === 'unavailable') && !loading && !searching && (
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

      {/* Three different nothings, which want three different messages: no
          films at all, versus a search that matched none of them. Telling
          someone "there are no screenings" when they have simply mistyped a
          title is the kind of dead end that makes a search box feel broken. */}
      {!loading && !error && movies.length === 0 && (
        <EmptyState message="אין הקרנות זמינות כרגע." />
      )}
      {!loading && !error && movies.length > 0 && visible.length === 0 && (
        <EmptyState message={`לא נמצא סרט שתואם "${query.trim()}".`} />
      )}
      {!loading && !error && visible.length > 0 && <MovieGrid movies={visible} />}
    </div>
  );
}

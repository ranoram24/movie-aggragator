/**
 * One film: what it is, and every way to go see it tonight.
 *
 * The poster doubles as a blurred backdrop so the screen feels cinematic
 * without needing a separate backdrop image the API doesn't have.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useGeolocation } from '../hooks/useGeolocation';
import { useMovie } from '../hooks/useMovie';
import { ChainFilter } from '../components/ChainFilter';
import { TheaterList } from '../components/TheaterList';
import { DetailSkeleton } from '../components/Skeleton';
import { EmptyState, ErrorState } from '../components/ErrorState';
import './MovieDetailScreen.css';

export function MovieDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const { coords } = useGeolocation();
  const { movie, loading, error, reload } = useMovie(id, coords);
  const [scrolled, setScrolled] = useState(false);
  const [chains, setChains] = useState<string[]>([]);

  // Filtering happens here rather than server-side: the response already holds
  // every theatre, so narrowing is instant and costs no request.
  const availableChains = useMemo(() => {
    const seen = new Map<string, number>();
    for (const theatre of movie?.theatres ?? []) {
      seen.set(theatre.chain, (seen.get(theatre.chain) ?? 0) + 1);
    }
    return seen;
  }, [movie]);

  const visibleTheatres = useMemo(() => {
    const all = movie?.theatres ?? [];
    return chains.length ? all.filter((t) => chains.includes(t.chain)) : all;
  }, [movie, chains]);

  const toggleChain = (chain: string) =>
    setChains((current) =>
      current.includes(chain)
        ? current.filter((c) => c !== chain)
        : [...current, chain],
    );

  // Reveal the title in the sticky bar once the big one scrolls away.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 150);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Coming from the grid, the page would otherwise keep the previous scroll,
  // and a chain chosen for the last film would silently apply to this one.
  useEffect(() => {
    window.scrollTo(0, 0);
    setChains([]);
  }, [id]);

  const facts = movie
    ? [
        movie.genre,
        movie.runtime_minutes ? `${movie.runtime_minutes} דק'` : null,
        movie.age_rating,
      ].filter((f): f is string => Boolean(f))
    : [];

  return (
    <div className="detail">
      <div className={`detail__bar${scrolled ? ' detail__bar--scrolled' : ''}`}>
        <Link to="/" className="detail__back pressable" aria-label="חזרה">
          ←
        </Link>
        <span
          className={`detail__bartitle${scrolled ? ' detail__bartitle--visible' : ''}`}
        >
          {movie?.title_he ?? ''}
        </span>
      </div>

      {loading && <DetailSkeleton />}
      {!loading && error && <ErrorState message={error} onRetry={reload} />}
      {!loading && !error && !movie && (
        <EmptyState message="הסרט לא נמצא." />
      )}

      {!loading && !error && movie && (
        <>
          <div className="detail__hero">
            {movie.poster_url && (
              <div className="detail__herobg">
                <img src={movie.poster_url} alt="" aria-hidden="true" />
              </div>
            )}
            <div className="detail__heroscrim" />

            <div className="detail__heroinner">
              <div className="detail__poster">
                {movie.poster_url && (
                  <img src={movie.poster_url} alt={movie.title_he} />
                )}
              </div>

              <div className="detail__headings">
                <h1 className="detail__title">{movie.title_he}</h1>
                {movie.title_en && (
                  <p className="detail__titleen">{movie.title_en}</p>
                )}
                {facts.length > 0 && (
                  <div className="detail__facts">
                    {facts.map((fact) => (
                      <span key={fact} className="detail__fact">
                        {fact}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Absent for films TMDb couldn't match — omitted entirely rather
              than rendering an empty block. */}
          {movie.overview && <p className="detail__overview">{movie.overview}</p>}

          <ChainFilter
            chains={[...availableChains.keys()]}
            selected={chains}
            onToggle={toggleChain}
            onClear={() => setChains([])}
            counts={Object.fromEntries(availableChains)}
          />

          {visibleTheatres.length > 0 ? (
            <TheaterList theatres={visibleTheatres} />
          ) : (
            <EmptyState
              message={
                movie.theatres.length
                  ? 'אין הקרנות ברשתות שנבחרו.'
                  : 'אין הקרנות קרובות לסרט הזה.'
              }
            />
          )}
        </>
      )}
    </div>
  );
}

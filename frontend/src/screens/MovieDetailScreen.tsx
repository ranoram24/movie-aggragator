/**
 * One film: what it is, and every way to go see it tonight.
 *
 * The poster doubles as a blurred backdrop so the screen feels cinematic
 * without needing a separate backdrop image the API doesn't have.
 */

import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useGeolocation } from '../hooks/useGeolocation';
import { useMovie } from '../hooks/useMovie';
import { TheaterList } from '../components/TheaterList';
import { DetailSkeleton } from '../components/Skeleton';
import { EmptyState, ErrorState } from '../components/ErrorState';
import './MovieDetailScreen.css';

export function MovieDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const { coords } = useGeolocation();
  const { movie, loading, error, reload } = useMovie(id, coords);
  const [scrolled, setScrolled] = useState(false);

  // Reveal the title in the sticky bar once the big one scrolls away.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 150);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Coming from the grid, the page would otherwise keep the previous scroll.
  useEffect(() => window.scrollTo(0, 0), [id]);

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

          {movie.theatres.length > 0 ? (
            <TheaterList theatres={movie.theatres} />
          ) : (
            <EmptyState message="אין הקרנות קרובות לסרט הזה." />
          )}
        </>
      )}
    </div>
  );
}

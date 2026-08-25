/** One poster in the browse grid.
 *
 *  The poster IS the card — title and theatre count sit on a gradient scrim
 *  over the bottom of the image rather than in a separate row beneath it, so
 *  posters stay the dominant element and the grid stays dense on a phone. */

import { Link } from 'react-router-dom';
import type { MovieSummary } from '../api/types';
import { formatDistance } from '../api/format';
import './MovieCard.css';

interface Props {
  movie: MovieSummary;
}

export function MovieCard({ movie }: Props) {
  const distance = formatDistance(movie.nearest_km);

  return (
    <Link to={`/movie/${movie.id}`} className="movie-card pressable">
      <div className="movie-card__poster">
        {movie.poster_url ? (
          <img
            src={movie.poster_url}
            alt={movie.title_he}
            loading="lazy"
            decoding="async"
          />
        ) : (
          // No poster is common for local/event listings, so it gets a real
          // fallback rather than a broken-image icon.
          <div className="movie-card__noposter">
            <span>{movie.title_he.slice(0, 2)}</span>
          </div>
        )}

        <div className="movie-card__scrim" />

        <div className="movie-card__meta">
          <h3 className="movie-card__title">{movie.title_he}</h3>
          {movie.title_en && (
            <p className="movie-card__subtitle">{movie.title_en}</p>
          )}
          <p className="movie-card__cinemas">
            {movie.theatre_count} בתי קולנוע
            {distance && <span className="movie-card__dot"> · </span>}
            {distance && <span className="movie-card__distance">{distance}</span>}
          </p>
        </div>
      </div>
    </Link>
  );
}

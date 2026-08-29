/** One poster in the browse grid.
 *
 *  The poster IS the card — title and theatre count sit on a gradient scrim
 *  over the bottom of the image rather than in a separate row beneath it, so
 *  posters stay the dominant element and the grid stays dense on a phone. */

import { Link } from 'react-router-dom';
import type { MovieSummary } from '../api/types';
import { PosterImage } from './PosterImage';
import './MovieCard.css';

interface Props {
  movie: MovieSummary;
}

export function MovieCard({ movie }: Props) {
  return (
    <Link to={`/movie/${movie.id}`} className="movie-card pressable">
      <div className="movie-card__poster">
        <PosterImage
          src={movie.poster_url}
          alt={movie.title_he}
          fallbackText={movie.title_he}
        />

        <div className="movie-card__scrim" />

        <div className="movie-card__meta">
          <h3 className="movie-card__title">{movie.title_he}</h3>
          {movie.title_en && (
            <p className="movie-card__subtitle">{movie.title_en}</p>
          )}
          {/* Distance is deliberately not shown. It is haversine, so it
              disagrees with a driving route by roughly a fifth, and the number
              invited comparison with Maps without adding much. Proximity still
              decides the ordering -- it just is not spelled out. */}
          <p className="movie-card__cinemas">{movie.theatre_count} בתי קולנוע</p>
        </div>
      </div>
    </Link>
  );
}

/** One poster in the browse grid.
 *
 *  The poster IS the card — title and theatre count sit on a gradient scrim
 *  over the bottom of the image rather than in a separate row beneath it, so
 *  posters stay the dominant element and the grid stays dense on a phone. */

import { Link } from 'react-router-dom';
import type { MovieSummary } from '../api/types';
import { digitalLabel } from '../api/dates';
import { PosterImage } from './PosterImage';
import './MovieCard.css';

interface Props {
  movie: MovieSummary;
}

export function MovieCard({ movie }: Props) {
  const digital = digitalLabel(movie.digital_date);

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
          {/* Only when another card looks like the same film. Naming the
              chains on both is what lets you see at a glance that one film has
              been split -- the two cards will cover different chains. Hidden
              otherwise, since on a correctly merged card it is just noise. */}
          {movie.possible_duplicate && movie.chains.length > 0 && (
            <p className="movie-card__chains">{movie.chains.join(' · ')}</p>
          )}
          {/* Stated, not argued. It sits in the same quiet register as the
              cinema count rather than in a badge, because a coloured flag
              would be the app having an opinion about whether to wait — and
              the whole point is that the reader draws their own conclusion
              from the date. */}
          {digital && <p className="movie-card__digital">{digital}</p>}
        </div>
      </div>
    </Link>
  );
}

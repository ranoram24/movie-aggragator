/** Two-up poster grid. */

import type { MovieSummary } from '../api/types';
import { MovieCard } from './MovieCard';
import './MovieGrid.css';

export function MovieGrid({ movies }: { movies: MovieSummary[] }) {
  return (
    <div className="movie-grid">
      {movies.map((movie) => (
        <MovieCard key={movie.id} movie={movie} />
      ))}
    </div>
  );
}

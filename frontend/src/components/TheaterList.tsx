/** Every theatre showing this film, already distance-sorted by the API. */

import type { Theatre } from '../api/types';
import { TheaterCard } from './TheaterCard';
import './TheaterList.css';

export function TheaterList({ theatres }: { theatres: Theatre[] }) {
  return (
    <div className="theater-list">
      <h2 className="theater-list__heading">
        בתי קולנוע
        <span className="theater-list__count">{theatres.length}</span>
      </h2>
      {theatres.map((theatre) => (
        <TheaterCard key={theatre.id} theatre={theatre} />
      ))}
    </div>
  );
}

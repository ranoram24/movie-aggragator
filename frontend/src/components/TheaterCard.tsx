/** One theatre on the detail screen: where it is, how far, and when it plays. */

import type { Theatre } from '../api/types';
import { formatDistance } from '../api/format';
import { ShowtimeList } from './ShowtimeList';
import './TheaterCard.css';

export function TheaterCard({ theatre }: { theatre: Theatre }) {
  return (
    <section className="theater-card">
      <header className="theater-card__head">
        <div className="theater-card__id">
          <h3 className="theater-card__name">{theatre.name}</h3>
          <p className="theater-card__chain">{theatre.chain}</p>
        </div>
        {theatre.distance_km !== null && (
          <span className="theater-card__distance">
            {formatDistance(theatre.distance_km)}
          </span>
        )}
      </header>

      {theatre.address && <p className="theater-card__address">{theatre.address}</p>}

      {theatre.dates.map((group) => (
        <ShowtimeList key={group.date} group={group} />
      ))}
    </section>
  );
}

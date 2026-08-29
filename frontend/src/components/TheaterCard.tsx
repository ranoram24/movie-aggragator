/** One theatre on the detail screen: where it is and when it plays.
 *
 *  Distance is not shown — the list is still ordered nearest-first, the
 *  kilometres are just not spelled out. */

import type { Theatre } from '../api/types';
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
      </header>

      {theatre.address && <p className="theater-card__address">{theatre.address}</p>}

      {theatre.dates.map((group) => (
        <ShowtimeList key={group.date} group={group} />
      ))}
    </section>
  );
}

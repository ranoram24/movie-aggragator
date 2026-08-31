/** One theatre on the detail screen: where it is and when it plays.
 *
 *  Distance is not shown — the list is still ordered nearest-first, the
 *  kilometres are just not spelled out. */

import type { Coords, Theatre } from '../api/types';
import { bookingNote } from '../api/booking';
import { directionsUrl } from '../api/navigation';
import { ShowtimeList } from './ShowtimeList';
import './TheaterCard.css';

interface Props {
  theatre: Theatre;
  /** Where to route from. Null lets Maps use the device's own location. */
  from: Coords | null;
}

export function TheaterCard({ theatre, from }: Props) {
  const note = bookingNote(theatre.chain);

  return (
    <section className="theater-card">
      <header className="theater-card__head">
        <div className="theater-card__id">
          <h3 className="theater-card__name">{theatre.name}</h3>
          <p className="theater-card__chain">{theatre.chain}</p>
        </div>
      </header>

      {theatre.address && <p className="theater-card__address">{theatre.address}</p>}

      {/* Secondary to the showtimes, which are what people came for -- so it
          sits with the address rather than competing with the time pills. */}
      <a
        className="theater-card__nav pressable"
        href={directionsUrl(theatre, from)}
        target="_blank"
        rel="noopener noreferrer"
      >
        <span aria-hidden="true">🧭</span>
        <span>נווט לקולנוע</span>
      </a>

      {/* Sits above the times, not below: it only helps if it is read before
          the tap that it explains. */}
      {note && (
        <p className="theater-card__note">
          <span aria-hidden="true">ℹ️</span> {note}
        </p>
      )}

      {theatre.dates.map((group) => (
        <ShowtimeList key={group.date} group={group} />
      ))}
    </section>
  );
}

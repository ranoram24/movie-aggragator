/** The showtimes for one theatre on one date.
 *
 *  Each pill is an external link straight to that screening's checkout, so it
 *  is the single most important tap target in the app — sized generously and
 *  marked as leaving the app. */

import type { DateGroup } from '../api/types';
import './ShowtimeList.css';

interface Props {
  group: DateGroup;
}

export function ShowtimeList({ group }: Props) {
  return (
    <div className="showtime-group">
      <h4 className="showtime-group__label">{group.label}</h4>
      <div className="showtime-group__pills">
        {group.showtimes.map((showtime, index) => (
          <a
            key={`${showtime.time}-${showtime.venue_type}-${index}`}
            className="showtime-pill pressable"
            href={showtime.ticket_url}
            target="_blank"
            // noopener/noreferrer: these are third-party ticketing sites and
            // must not get a handle on this window.
            rel="noopener noreferrer"
          >
            <span className="showtime-pill__time">{showtime.time}</span>
            {showtime.venue_type !== 'regular' && (
              <span className="showtime-pill__format">{showtime.venue_type}</span>
            )}
          </a>
        ))}
      </div>
    </div>
  );
}

/** The showtimes for one theatre on one date.
 *
 *  Each pill is an external link straight to that screening's checkout, so it
 *  is the single most important tap target in the app — sized generously and
 *  marked as leaving the app.
 *
 *  Each pill states the language the audience will HEAR. That matters because
 *  a cinema commonly runs the Hebrew dub and the original audio of the same
 *  film an hour apart — sometimes at the same minute in different halls — and
 *  they are separate tickets. Whether that audio is a dub or the original is
 *  not the useful distinction at this moment; the language is. */

import type { DateGroup } from '../api/types';
import { audioLabel, audioLanguageLabel } from '../api/language';
import './ShowtimeList.css';

export function ShowtimeList({ group }: { group: DateGroup }) {
  return (
    <div className="showtime-group">
      <h4 className="showtime-group__label">{group.label}</h4>
      <div className="showtime-group__pills">
        {group.showtimes.map((showtime, index) => {
          const spoken = audioLanguageLabel(showtime.spoken_language);
          const audio = audioLabel(
            showtime.dubbed_language,
            showtime.original_language,
            showtime.subtitled_language,
          );
          return (
            <a
              key={`${showtime.time}-${showtime.venue_type}-${showtime.spoken_language}-${index}`}
              className="showtime-pill pressable"
              href={showtime.ticket_url}
              target="_blank"
              // noopener/noreferrer: these are third-party ticketing sites and
              // must not get a handle on this window.
              rel="noopener noreferrer"
              title={audio ?? undefined}
              aria-label={audio ? `${showtime.time} — ${audio}` : showtime.time}
            >
              <span className="showtime-pill__time">{showtime.time}</span>
              {spoken && <span className="showtime-pill__audio">{spoken}</span>}
              {showtime.venue_type !== 'regular' && (
                <span className="showtime-pill__format">{showtime.venue_type}</span>
              )}
            </a>
          );
        })}
      </div>
    </div>
  );
}

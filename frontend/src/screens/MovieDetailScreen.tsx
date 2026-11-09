/**
 * One film: what it is, and every way to go see it tonight.
 *
 * The poster doubles as a blurred backdrop so the screen feels cinematic
 * without needing a separate backdrop image the API doesn't have.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useGeolocation } from '../hooks/useGeolocation';
import { useMovie } from '../hooks/useMovie';
import { ChainFilter } from '../components/ChainFilter';
import { DubFilter, audioKey, type AudioOption } from '../components/DubFilter';
import { SearchBar } from '../components/SearchBar';
import { filterTheatres } from '../api/search';
import { languageName } from '../api/language';
import { PosterImage } from '../components/PosterImage';
import { TheaterList } from '../components/TheaterList';
import { DetailSkeleton } from '../components/Skeleton';
import { EmptyState, ErrorState } from '../components/ErrorState';
import './MovieDetailScreen.css';

export function MovieDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const { coords } = useGeolocation();
  const { movie, loading, error, reload } = useMovie(id, coords);
  const [scrolled, setScrolled] = useState(false);
  const [chains, setChains] = useState<string[]>([]);
  const [audio, setAudio] = useState<string[]>([]);
  const [city, setCity] = useState('');

  // Filtering happens here rather than server-side: the response already holds
  // every theatre, so narrowing is instant and costs no request.
  const availableChains = useMemo(() => {
    const seen = new Map<string, number>();
    for (const theatre of movie?.theatres ?? []) {
      seen.set(theatre.chain, (seen.get(theatre.chain) ?? 0) + 1);
    }
    return seen;
  }, [movie]);

  // Which spoken-language versions this film actually has, and how many
  // screenings of each. Derived from the loaded data so a chip can never lead
  // to an empty list.
  const audioOptions = useMemo<AudioOption[]>(() => {
    const tally = new Map<string, AudioOption>();
    for (const theatre of movie?.theatres ?? []) {
      for (const group of theatre.dates) {
        for (const showtime of group.showtimes) {
          const dubbed = showtime.dubbed_language;
          const key = audioKey(dubbed);
          const existing = tally.get(key);
          if (existing) existing.count += 1;
          else tally.set(key, { dubbed, count: 1 });
        }
      }
    }
    // Most screenings first, so the common version leads.
    return [...tally.values()].sort((a, b) => b.count - a.count);
  }, [movie]);

  // All three filters apply together, and the last two prune empty containers
  // as they go: a date with no matching showtimes, or a theatre with no
  // matching dates, should disappear rather than render as an empty heading.
  //
  // The order is the important part. Chain narrows the set FIRST, so the city
  // text only ever sees theatres the chain filter already allowed -- that is
  // what makes "only Movieland" + "נתניה" structurally incapable of returning
  // Cinema City Netanya, rather than relying on the two filters agreeing.
  const visibleTheatres = useMemo(() => {
    let theatres = movie?.theatres ?? [];
    if (chains.length) {
      theatres = theatres.filter((t) => chains.includes(t.chain));
    }
    theatres = filterTheatres(theatres, city);
    if (!audio.length) return theatres;

    return theatres
      .map((theatre) => ({
        ...theatre,
        dates: theatre.dates
          .map((group) => ({
            ...group,
            showtimes: group.showtimes.filter((s) =>
              audio.includes(audioKey(s.dubbed_language)),
            ),
          }))
          .filter((group) => group.showtimes.length > 0),
      }))
      .filter((theatre) => theatre.dates.length > 0);
  }, [movie, chains, audio, city]);

  const toggleChain = (chain: string) =>
    setChains((current) =>
      current.includes(chain)
        ? current.filter((c) => c !== chain)
        : [...current, chain],
    );

  const toggleAudio = (key: string) =>
    setAudio((current) =>
      current.includes(key)
        ? current.filter((a) => a !== key)
        : [...current, key],
    );

  // Reveal the title in the sticky bar once the big one scrolls away.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 150);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  // Coming from the grid, the page would otherwise keep the previous scroll,
  // and a chain chosen for the last film would silently apply to this one.
  useEffect(() => {
    window.scrollTo(0, 0);
    setChains([]);
    setAudio([]);
    setCity('');
  }, [id]);

  const facts = movie
    ? [
        movie.genre,
        movie.runtime_minutes ? `${movie.runtime_minutes} דק'` : null,
        movie.age_rating,
        // The film's own language, distinct from any screening's dub.
        movie.original_language
          ? `שפת מקור: ${languageName(movie.original_language)}`
          : null,
      ].filter((f): f is string => Boolean(f))
    : [];

  return (
    <div className="detail">
      <div className={`detail__bar${scrolled ? ' detail__bar--scrolled' : ''}`}>
        <Link to="/" className="detail__back pressable" aria-label="חזרה">
          ←
        </Link>
        <span
          className={`detail__bartitle${scrolled ? ' detail__bartitle--visible' : ''}`}
        >
          {movie?.title_he ?? ''}
        </span>
      </div>

      {loading && <DetailSkeleton />}
      {!loading && error && <ErrorState message={error} onRetry={reload} />}
      {!loading && !error && !movie && (
        <EmptyState message="הסרט לא נמצא." />
      )}

      {!loading && !error && movie && (
        <>
          <div className="detail__hero">
            {movie.poster_url && (
              <div className="detail__herobg">
                <img src={movie.poster_url} alt="" aria-hidden="true" />
              </div>
            )}
            <div className="detail__heroscrim" />

            <div className="detail__heroinner">
              <div className="detail__poster">
                <PosterImage
                  src={movie.poster_url}
                  alt={movie.title_he}
                  fallbackText={movie.title_he}
                />
              </div>

              <div className="detail__headings">
                <h1 className="detail__title">{movie.title_he}</h1>
                {movie.title_en && (
                  <p className="detail__titleen">{movie.title_en}</p>
                )}
                {facts.length > 0 && (
                  <div className="detail__facts">
                    {facts.map((fact) => (
                      <span key={fact} className="detail__fact">
                        {fact}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Two columns once there is room for them: what the film IS stays
              put on one side while the screenings scroll on the other, so the
              filters remain reachable 30 theatres down instead of being
              stranded at the top of a very long page. On a phone the grid
              never engages and this is a plain stack, exactly as before. */}
          <div className="detail__body">
            <aside className="detail__rail">
              {/* Absent for films TMDb couldn't match — omitted entirely rather
                  than rendering an empty block. */}
              {movie.overview && (
                <p className="detail__overview">{movie.overview}</p>
              )}

              {/* Hidden for a film at one or two cinemas: both fit on screen
                  at once, so a box to narrow them down is pure furniture. The
                  chain and dub chips hide themselves on the same reasoning. */}
              {movie.theatres.length >= 3 && (
                <SearchBar
                  value={city}
                  onChange={setCity}
                  placeholder="חיפוש עיר או בית קולנוע"
                  label="חיפוש לפי עיר"
                  resultCount={visibleTheatres.length}
                  resultNoun={
                    visibleTheatres.length === 1 ? 'בית קולנוע' : 'בתי קולנוע'
                  }
                />
              )}

              <DubFilter
                options={audioOptions}
                selected={audio}
                onToggle={toggleAudio}
                onClear={() => setAudio([])}
              />

              <ChainFilter
                chains={[...availableChains.keys()]}
                selected={chains}
                onToggle={toggleChain}
                onClear={() => setChains([])}
                counts={Object.fromEntries(availableChains)}
              />
            </aside>

            <div className="detail__main">
              {visibleTheatres.length > 0 ? (
                <TheaterList theatres={visibleTheatres} from={coords} />
              ) : (
                <EmptyState
                  message={
                    !movie.theatres.length
                      ? 'אין הקרנות קרובות לסרט הזה.'
                      : city.trim()
                        // Says the quiet part out loud: with a chain chip on,
                        // an empty city result usually means the city is fine
                        // and the chain is the reason, which is impossible to
                        // guess from "no matching screenings".
                        ? `אין הקרנות ב"${city.trim()}"${
                            chains.length ? ' ברשתות שנבחרו' : ''
                          }.`
                        : 'אין הקרנות מתאימות לסינון שנבחר.'
                  }
                />
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

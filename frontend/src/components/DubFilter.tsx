/** Chip row for narrowing a film's screenings by audio.
 *
 *  A film often plays dubbed into Hebrew, dubbed into Russian, and in its
 *  original audio, all at the same cinema on the same day — three different
 *  tickets. Those used to be three separate cards; now they are one card, so
 *  this is how you get back to the version you actually want.
 *
 *  Grouped by dub language, with everything undubbed collapsed into a single
 *  "original" chip. That is deliberate: most chains annotate only the dubbed
 *  screenings and say nothing about the rest, so the absence of a marker means
 *  "original audio", not "unknown". Bucketing those as unknown would put ~60%
 *  of all screenings behind a meaningless chip.
 *
 *  Built from the languages this film actually has, so a chip is never a dead
 *  end, and hidden entirely when there is only one. */

import { languageName } from '../api/language';
import './DubFilter.css';

export interface AudioOption {
  /** ISO code of the dub, or null for original audio. */
  dubbed: string | null;
  count: number;
}

/** Stable key for an option. */
export function audioKey(dubbed: string | null | undefined): string {
  return dubbed ? `dub:${dubbed}` : 'original';
}

interface Props {
  options: AudioOption[];
  selected: string[];
  onToggle: (key: string) => void;
  onClear: () => void;
}

export function DubFilter({ options, selected, onToggle, onClear }: Props) {
  if (options.length < 2) return null;
  const all = selected.length === 0;

  return (
    <div className="dubfilter" role="group" aria-label="סינון לפי שפת הסרט">
      <div className="dubfilter__scroll">
        <button
          className={`dubfilter__chip pressable${all ? ' dubfilter__chip--on' : ''}`}
          onClick={onClear}
          aria-pressed={all}
        >
          הכל
        </button>
        {options.map((option) => {
          const key = audioKey(option.dubbed);
          const on = selected.includes(key);
          return (
            <button
              key={key}
              className={`dubfilter__chip pressable${on ? ' dubfilter__chip--on' : ''}`}
              onClick={() => onToggle(key)}
              aria-pressed={on}
            >
              <span>
                {option.dubbed ? `מדובב ל${languageName(option.dubbed)}` : 'שפת מקור'}
              </span>
              <span className="dubfilter__count">{option.count}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

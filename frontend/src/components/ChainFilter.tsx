/** Chip row for narrowing a film's screenings to one or more chains.
 *
 *  Lives on the detail screen only. The chips are built from the chains that
 *  actually show THIS film, so there is never a chip that leads to an empty
 *  list — which is what made the old browse-screen version frustrating.
 *
 *  Scrolls sideways rather than wrapping, so it never pushes the showtimes
 *  below the fold. "הכל" is a real chip rather than a cleared state, so getting
 *  back to everything is always one tap. */

import './ChainFilter.css';

interface Props {
  chains: string[];
  selected: string[];
  onToggle: (chain: string) => void;
  onClear: () => void;
  counts?: Record<string, number>;
}

export function ChainFilter({ chains, selected, onToggle, onClear, counts }: Props) {
  // One chain means there is nothing to choose between.
  if (chains.length < 2) return null;
  const all = selected.length === 0;

  return (
    <div className="chainfilter" role="group" aria-label="סינון לפי רשת">
      <div className="chainfilter__scroll">
        <button
          className={`chainfilter__chip pressable${all ? ' chainfilter__chip--on' : ''}`}
          onClick={onClear}
          aria-pressed={all}
        >
          הכל
        </button>
        {chains.map((chain) => {
          const on = selected.includes(chain);
          return (
            <button
              key={chain}
              className={`chainfilter__chip pressable${on ? ' chainfilter__chip--on' : ''}`}
              onClick={() => onToggle(chain)}
              aria-pressed={on}
            >
              {chain}
              {counts?.[chain] !== undefined && (
                <span className="chainfilter__count">{counts[chain]}</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

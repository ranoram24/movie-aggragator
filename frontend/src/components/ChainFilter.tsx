/** Horizontal chip row for filtering by cinema chain.
 *
 *  Scrolls sideways rather than wrapping, so it never pushes the poster grid
 *  below the fold on a small screen. "הכל" is a real chip rather than a
 *  cleared state, so getting back to everything is always one tap. */

import type { Chain } from '../api/types';
import './ChainFilter.css';

interface Props {
  chains: Chain[];
  selected: string[];
  onToggle: (key: string) => void;
  onClear: () => void;
}

export function ChainFilter({ chains, selected, onToggle, onClear }: Props) {
  if (chains.length === 0) return null;
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
          const on = selected.includes(chain.key);
          return (
            <button
              key={chain.key}
              className={`chainfilter__chip pressable${on ? ' chainfilter__chip--on' : ''}`}
              onClick={() => onToggle(chain.key)}
              aria-pressed={on}
            >
              {chain.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

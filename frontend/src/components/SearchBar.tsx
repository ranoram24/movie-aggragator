/** The app's only text input, used by both screens.
 *
 *  Shared rather than written twice because the risky parts are identical: the
 *  length cap, the fact that the value is only ever rendered as text, and the
 *  keyboard behaviour. One component means one place to audit.
 *
 *  ## Security
 *
 *  `value` is interpolated into JSX in exactly two places -- the input's own
 *  value and the optional count line -- and React escapes both. There is no
 *  `dangerouslySetInnerHTML` here or anywhere in the app, the query is never put
 *  into an href, a src or a style, and it is never sent to the server, so a
 *  query of `<img onerror=...>` is just eight characters that match no film.
 *  The one thing that would break this is "helpfully" highlighting the match by
 *  assembling an HTML string -- if that is ever wanted, build React nodes.
 *
 *  ## Input behaviour
 *
 *  Not a <form>: there is nothing to submit, since results update per keystroke.
 *  enterKeyHint still asks for a search key on the phone keyboard so Enter
 *  dismisses it rather than looking broken, and Escape clears -- the shortcut
 *  anyone who uses search expects, and the fastest way back to the full list.
 */

import { MAX_QUERY_LENGTH } from '../api/search';
import './SearchBar.css';

interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  /** Accessible name. The visible label is the placeholder, which screen
   *  readers do not reliably announce. */
  label: string;
  /** Rendered as "N <noun>" under the field while a query is active. Omitted
   *  entirely when there is no query, so the layout does not jump on focus. */
  resultCount?: number;
  resultNoun?: string;
}

export function SearchBar({
  value,
  onChange,
  placeholder,
  label,
  resultCount,
  resultNoun,
}: Props) {
  const active = value.trim().length > 0;

  return (
    <div className="searchbar">
      <div className="searchbar__field">
        <span className="searchbar__icon" aria-hidden="true">
          🔍
        </span>

        <input
          className="searchbar__input"
          // type="search" gives the phone keyboard a search key and marks the
          // field up correctly; the browser's own clear widget is suppressed in
          // CSS in favour of the button below, which is reachable by keyboard.
          type="search"
          inputMode="search"
          enterKeyHint="search"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') onChange('');
          }}
          placeholder={placeholder}
          aria-label={label}
          // Film titles and Hebrew city names are not dictionary words; a red
          // underline under every one of them is noise.
          spellCheck={false}
          autoComplete="off"
          autoCorrect="off"
          // Defence in depth. The filter already truncates, but capping the
          // field means an over-long value never exists in the first place.
          maxLength={MAX_QUERY_LENGTH}
        />

        {active && (
          <button
            type="button"
            className="searchbar__clear pressable"
            onClick={() => onChange('')}
            aria-label="נקה חיפוש"
          >
            ✕
          </button>
        )}
      </div>

      {/* Announced politely so a screen reader hears the new count after
          typing stops, instead of on every keystroke. */}
      {active && resultCount !== undefined && (
        <p className="searchbar__count" aria-live="polite">
          {resultCount} {resultNoun}
        </p>
      )}
    </div>
  );
}

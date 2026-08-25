/**
 * The selected chain filter, persisted to localStorage.
 *
 * Persisted deliberately: tapping into a film and back is the core loop of the
 * app, and losing the filter every time would make it useless. It also survives
 * a reload, which is what someone expects from a filter they set on purpose.
 */

import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'oncinema.chains';

function read(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === 'string') : [];
  } catch {
    // Private-mode Safari throws on localStorage; an unfiltered list is a fine
    // fallback and much better than a crash.
    return [];
  }
}

export function useChainSelection() {
  const [selected, setSelected] = useState<string[]>(read);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(selected));
    } catch {
      /* not fatal — the filter just won't persist */
    }
  }, [selected]);

  const toggle = useCallback((key: string) => {
    setSelected((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    );
  }, []);

  const clear = useCallback(() => setSelected([]), []);

  return { selected, toggle, clear };
}

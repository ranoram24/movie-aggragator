/** The list of cinema chains, for the filter chips. */

import { useEffect, useState } from 'react';
import { fetchChains } from '../api/client';
import type { Chain } from '../api/types';

export function useChains(): Chain[] {
  const [chains, setChains] = useState<Chain[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchChains()
      // A failure here is not worth surfacing: the filter simply doesn't
      // render, and the unfiltered list still works.
      .then((data) => !cancelled && setChains(data))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return chains;
}

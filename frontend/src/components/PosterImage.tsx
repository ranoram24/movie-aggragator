/** A poster that always renders something.
 *
 *  Two ways a card ends up without artwork, and both used to look broken:
 *  the chain publishes no poster at all (live events, one-off screenings), or
 *  it publishes a URL that 404s. The second is worse -- the browser draws its
 *  own broken-image icon with the alt text spilling out.
 *
 *  So a failed load is caught and swapped for the same placeholder used when
 *  there was never a URL, making both cases look deliberate. */

import { useEffect, useState } from 'react';
import './PosterImage.css';

interface Props {
  src: string | null;
  alt: string;
  /** Shown in the placeholder — first characters of the title. */
  fallbackText: string;
  className?: string;
}

export function PosterImage({ src, alt, fallbackText, className }: Props) {
  const [failed, setFailed] = useState(false);

  // A card can be reused for a different film as the list re-sorts, so a
  // previous failure must not stick to the new poster.
  useEffect(() => setFailed(false), [src]);

  if (!src || failed) {
    return (
      <div className={`poster-fallback ${className ?? ''}`} role="img" aria-label={alt}>
        <span className="poster-fallback__mark" aria-hidden="true">
          {fallbackText.slice(0, 2)}
        </span>
        <span className="poster-fallback__reel" aria-hidden="true">🎞</span>
      </div>
    );
  }

  return (
    <img
      className={className}
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
    />
  );
}

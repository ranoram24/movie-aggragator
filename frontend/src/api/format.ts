/** Small display helpers shared by the cards. */

/**
 * Distance for a Hebrew UI.
 *
 * The API rounds to one decimal, so a cinema in the same block comes back as
 * 0.0 and would render as a bare "0 ק״מ" — which reads like missing data
 * rather than "very close". Sub-100m gets words instead of a number.
 */
export function formatDistance(km: number | null): string | null {
  if (km === null) return null;
  if (km < 0.1) return 'ממש כאן';
  if (km < 1) return `${Math.round(km * 1000)} מ׳`;
  return `${km.toFixed(1)} ק״מ`;
}

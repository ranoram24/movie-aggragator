/**
 * Language presentation for showtimes.
 *
 * A parent picking a kids' film needs to know at a glance whether a given
 * showing is dubbed into Hebrew or plays in its original audio — the two are
 * often at the same cinema an hour apart, and they are separate tickets.
 */

/** ISO-639-1 -> flag emoji. Flags are drawn from regional indicator pairs. */
const FLAGS: Record<string, string> = {
  he: '🇮🇱',
  en: '🇬🇧',
  fr: '🇫🇷',
  ru: '🇷🇺',
  es: '🇪🇸',
  ar: '🇸🇦',
  it: '🇮🇹',
  de: '🇩🇪',
};

const NAMES: Record<string, string> = {
  he: 'עברית',
  en: 'אנגלית',
  fr: 'צרפתית',
  ru: 'רוסית',
  es: 'ספרדית',
  ar: 'ערבית',
  it: 'איטלקית',
  de: 'גרמנית',
};

export function flagFor(code: string | null | undefined): string | null {
  if (!code) return null;
  return FLAGS[code] ?? null;
}

export function languageName(code: string | null | undefined): string | null {
  if (!code) return null;
  return NAMES[code] ?? code.toUpperCase();
}

/**
 * A short human label for a screening's audio, used as the accessible name and
 * the tooltip. Dubbed and original read differently on purpose: "מדובב" is the
 * decision-relevant word, so it leads.
 */
export function audioLabel(
  dubbed: string | null,
  original: string | null,
  subtitles: string | null,
): string | null {
  const parts: string[] = [];
  if (dubbed) {
    parts.push(`מדובב ל${languageName(dubbed)}`);
  } else if (original) {
    parts.push(`${languageName(original)} (שפת מקור)`);
  }
  if (subtitles) parts.push(`כתוביות ב${languageName(subtitles)}`);
  return parts.length ? parts.join(' · ') : null;
}

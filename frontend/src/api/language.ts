/**
 * Language presentation for showtimes.
 *
 * A parent picking a kids' film needs to know at a glance whether a given
 * showing is dubbed into Hebrew or plays in its original audio — the two are
 * often at the same cinema an hour apart, and they are separate tickets.
 */

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

export function languageName(code: string | null | undefined): string | null {
  if (!code) return null;
  return NAMES[code] ?? code.toUpperCase();
}

/**
 * The dubbed audio language, as a plain label.
 *
 * Only ever called for dubbed screenings. An unmarked showing is the film in
 * its original language, which is the default and needs no label -- the same
 * convention the cinemas use on their own listings.
 */
export function audioLanguageLabel(spoken: string | null | undefined): string | null {
  if (!spoken) return null;
  return `שפת שמע: ${languageName(spoken)}`;
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

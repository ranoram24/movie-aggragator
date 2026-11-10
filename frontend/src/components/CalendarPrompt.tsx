/** Offers to put a screening in your calendar, after you have gone to book it.
 *
 *  ## When it appears
 *
 *  Tapping a showtime opens the chain's checkout in a new tab, which means
 *  this tab is left sitting there doing nothing — and it is the only moment
 *  when the app knows exactly which screening you are committing to. So the
 *  question is asked here, right then, rather than needing a second button
 *  nobody would press.
 *
 *  Nothing is blocked by it. The booking tab opens either way; this is a
 *  question waiting behind it when you come back, and dismissing it costs one
 *  tap or the Escape key.
 *
 *  ## Why <dialog>
 *
 *  The native element, not a hand-rolled overlay. It gives focus trapping,
 *  Escape-to-close, inertness of the page behind it and a ::backdrop for free
 *  — all things a div would have to reimplement, and all things that are
 *  quietly broken in most hand-rolled modals. showModal() has to be called
 *  imperatively, which is the one piece of ceremony it costs.
 */

import { useEffect, useRef } from 'react';
import {
  REMINDER_HOURS,
  durationMinutes,
  googleCalendarUrl,
  type ScreeningEvent,
} from '../api/calendar';
import './CalendarPrompt.css';

interface Props {
  /** The screening to offer, or null when there is nothing to ask about. */
  event: ScreeningEvent | null;
  /** Downloads the .ics — the route that carries the reminder. */
  onSave: () => void;
  onDismiss: () => void;
}

/** "2026-11-12" + "20:20" -> "12/11/2026 · 20:20" */
function whenLabel(date: string, time: string): string {
  const [year, month, day] = date.split('-');
  return `${day}/${month}/${year} · ${time}`;
}

export function CalendarPrompt({ event, onSave, onDismiss }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const saveRef = useRef<HTMLButtonElement>(null);

  // Open and close follow `event`, which is the single source of truth. The
  // dialog's own `close` event is deliberately NOT part of this.
  //
  // The first version routed every dismissal through that event, on the
  // reasoning that Escape, the backdrop and the button would then converge on
  // one path. Testing showed `close` never arriving — not for this dialog, and
  // not for a bare <dialog> created and closed in the same console. Whether
  // that is this Chromium build or the automation around it was never settled,
  // and it does not matter: a dismissal that silently fails to clear the
  // parent's state leaves a stale screening behind and an invisible dialog in
  // the DOM, and that is too quiet a failure to hang the feature on. So every
  // route out calls onDismiss directly, and this effect only mirrors state
  // onto the element.
  useEffect(() => {
    const dialog = ref.current;
    // Null whenever `event` is null, since the component renders nothing then.
    if (!dialog) return;

    // Where the reader was. Restored on close — see below for why.
    const scrollTop = window.scrollY;

    if (!dialog.open) {
      try {
        dialog.showModal();
      } catch {
        // showModal throws if the dialog is already open, and on anything
        // that does not support the top layer. Falling back to a non-modal
        // open at least shows the panel instead of silently swallowing the
        // prompt.
        dialog.open = true;
      }
    }

    // Focused here rather than with autoFocus, and with preventScroll.
    // React's autoFocus calls focus() plainly, and a plain focus() scrolls
    // the focused element into view — which is harmless while the dialog
    // sits in the top layer, and is a jump to the very end of a seventeen
    // thousand pixel page the moment it does not, since this element is the
    // last child of the screen. preventScroll removes that failure mode
    // rather than relying on the top layer always working.
    saveRef.current?.focus({ preventScroll: true });

    return () => {
      if (dialog.open) dialog.close();
      // Closing a modal returns focus to whatever opened it — the showtime
      // link, far up the page — and the browser scrolls that back into view.
      // Combined with a list that may have re-sorted while the booking tab
      // was in front, that is how dismissing the prompt could leave someone
      // reading a different cinema than the one they tapped. Putting the
      // scroll position back makes the prompt a no-op for the page behind it.
      window.scrollTo({ top: scrollTop, behavior: 'instant' });
    };
  }, [event]);

  if (!event) return null;

  const minutes = durationMinutes(event.runtimeMinutes);

  return (
    <dialog
      className="calprompt"
      ref={ref}
      aria-labelledby="calprompt-title"
      // A click landing on the dialog element itself is a click on the
      // backdrop: the content sits in the inner div, which stops propagation
      // by simply being the target instead.
      onClick={(e) => {
        if (e.target === ref.current) onDismiss();
      }}
      // Escape closes a modal dialog natively whatever we do, so this does not
      // preventDefault — it just makes sure the parent hears about it. keydown
      // fires before the default action, and unlike `close` it is ordinary and
      // reliable.
      onKeyDown={(e) => {
        if (e.key === 'Escape') onDismiss();
      }}
    >
      <div className="calprompt__panel">
        <h2 className="calprompt__title" id="calprompt-title">
          להוסיף ליומן?
        </h2>

        <dl className="calprompt__facts">
          <div className="calprompt__row">
            <dt>סרט</dt>
            <dd>{event.filmTitle}</dd>
          </div>
          <div className="calprompt__row">
            <dt>קולנוע</dt>
            <dd>
              {event.cinema}
              <span className="calprompt__chain"> · {event.chain}</span>
            </dd>
          </div>
          <div className="calprompt__row">
            <dt>מתי</dt>
            <dd>{whenLabel(event.date, event.time)}</dd>
          </div>
        </dl>

        {/* An assumption the event encodes that is invisible once it is in
            the calendar, so it is stated before you commit to it. */}
        <p className="calprompt__note">
          משך האירוע {minutes} דק׳ כולל פרסומות
        </p>

        <div className="calprompt__actions">
          <button
            type="button"
            className="calprompt__save pressable"
            onClick={onSave}
            ref={saveRef}
          >
            קובץ · תזכורת {REMINDER_HOURS} שעות
          </button>
          {/* Second, because it is the one that depends on how someone
              else's app chooses to route a link — and on Android that has
              already gone wrong once. */}
          <a
            className="calprompt__google pressable"
            href={googleCalendarUrl(event)}
            target="_blank"
            rel="noopener noreferrer"
            onClick={onDismiss}
          >
            Google Calendar
          </a>
        </div>

        {/* The difference between the two, in one line, because it is not
            guessable and it is the only reason to pick the slower one.
            Google's prefill interface has no parameter for an alarm, so an
            event made that way gets the account's default notification. */}
        <p className="calprompt__hint">
          ב-Google התזכורת היא ברירת המחדל שלך · בקובץ היא {REMINDER_HOURS} שעות
        </p>

        <button
          type="button"
          className="calprompt__skip pressable"
          onClick={onDismiss}
        >
          לא עכשיו
        </button>
      </div>
    </dialog>
  );
}

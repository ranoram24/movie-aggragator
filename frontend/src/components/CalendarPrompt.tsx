/** Offers to put a screening in your calendar, after you have gone to book it.
 *
 *  ## When it appears
 *
 *  Tapping a showtime opens the chain's checkout in a new tab, which leaves
 *  this tab doing nothing — and it is the only moment when the app knows
 *  exactly which screening you are committing to. So the question is asked
 *  then, rather than needing a second button nobody would press. Nothing is
 *  blocked by it: the booking tab opens either way.
 *
 *  ## The dialog element is never unmounted
 *
 *  It is rendered always and only its CONTENTS are conditional. That is the
 *  important structural detail here, and it was wrong at first.
 *
 *  The obvious shape — `if (!event) return null` — unmounts an OPEN modal
 *  dialog, and a modal dialog is not an ordinary element: it lives in the top
 *  layer, and the document behind it is inert while it is there. useEffect
 *  cleanup is a PASSIVE effect, so it runs after React has already detached
 *  the node, which means close() is called on an element the browser no longer
 *  has and the top layer is left to be cleaned up implicitly. That is
 *  invisible on a desktop and was reported from a real phone as the page going
 *  dead after dismissing — stale content, nothing responding, a long blank
 *  stretch where the rest of the list should be.
 *
 *  Keeping the element mounted means the browser owns open and close on a
 *  stable node, which is the thing it is designed for.
 *
 *  ## Dismissal does not use the `close` event
 *
 *  Every route out — the button, Escape, the backdrop — calls onDismiss
 *  directly. The dialog's own `close` event was tried as a single funnel and
 *  never observed firing, in this app or for a bare dialog created and closed
 *  in a console. Whether that was the browser or the harness around it was
 *  never settled, and it does not matter: a dismissal that silently fails to
 *  clear the parent's state is too quiet a failure to build on.
 */

import { useEffect, useRef } from 'react';
import {
  REMINDER_HOURS,
  addToCalendarUrl,
  durationMinutes,
  type ScreeningEvent,
} from '../api/calendar';
import './CalendarPrompt.css';

interface Props {
  /** The screening to offer, or null when there is nothing to ask about. */
  event: ScreeningEvent | null;
  /** Called once the calendar link has been followed, to close the prompt. */
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
  const saveRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;

    if (!event) {
      // Closed rather than unmounted. See the note at the top.
      if (dialog.open) dialog.close();
      return;
    }

    const scrollTop = window.scrollY;

    if (!dialog.open) {
      try {
        dialog.showModal();
      } catch {
        // Thrown if it is somehow already open, or where the top layer is not
        // supported. A non-modal open still shows the panel rather than
        // swallowing the prompt entirely.
        dialog.open = true;
      }
    }

    // Focused here rather than with autoFocus, and with preventScroll.
    // React's autoFocus calls focus() plainly, and a plain focus() scrolls the
    // element into view — harmless while the dialog is in the top layer, and a
    // jump to the end of a twenty-five thousand pixel page the moment it is
    // not, since this is the last element on the screen.
    saveRef.current?.focus({ preventScroll: true });

    return () => {
      // Closing a modal returns focus to whatever opened it — the showtime
      // link, far up the page — and the browser scrolls that back into view.
      // Putting the position back makes the prompt a no-op for the page behind
      // it. Smooth scrolling is suppressed for the restore: the page sets
      // scroll-behavior: smooth globally, and animating twenty thousand pixels
      // is both slow and interruptible halfway.
      const root = document.documentElement;
      const previous = root.style.scrollBehavior;
      root.style.scrollBehavior = 'auto';
      window.scrollTo(0, scrollTop);
      root.style.scrollBehavior = previous;
    };
  }, [event]);

  return (
    <dialog
      className="calprompt"
      ref={ref}
      aria-labelledby="calprompt-title"
      // A click landing on the dialog element itself is a click on the
      // backdrop: the content sits in the inner div, which is the target
      // instead for anything inside it.
      onClick={(e) => {
        if (e.target === ref.current) onDismiss();
      }}
      // Escape closes a modal natively whatever we do, so this does not
      // preventDefault — it just makes sure the parent hears about it. keydown
      // is ordinary and reliable, unlike `close`.
      onKeyDown={(e) => {
        if (e.key === 'Escape') onDismiss();
      }}
    >
      {event && (
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

          {/* Both are assumptions the event encodes and neither is visible
              once it is in the calendar, so they are stated beforehand. */}
          <p className="calprompt__note">
            תזכורת {REMINDER_HOURS} שעות לפני · משך האירוע{' '}
            {durationMinutes(event.runtimeMinutes)} דק׳ כולל פרסומות
          </p>

          {/* One button. Every route ends at the same file — the only
              difference is whether Android is asked to open it or the browser
              is left to save it, and that is not a choice worth presenting. */}
          <a
            className="calprompt__save pressable"
            href={addToCalendarUrl(event, navigator.userAgent, window.location.origin)}
            onClick={onSave}
            ref={saveRef}
          >
            הוספה ליומן
          </a>

          <button
            type="button"
            className="calprompt__skip pressable"
            onClick={onDismiss}
          >
            לא עכשיו
          </button>
        </div>
      )}
    </dialog>
  );
}

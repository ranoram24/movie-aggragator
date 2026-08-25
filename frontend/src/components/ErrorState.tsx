/** Shown when a fetch fails. Always offers a way out — a dead end with no
 *  retry is the worst possible mobile experience. */

import './ErrorState.css';

interface Props {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: Props) {
  return (
    <div className="error-state" role="alert">
      <div className="error-icon">⚠</div>
      <p className="error-message">{message}</p>
      {onRetry && (
        <button className="error-retry pressable" onClick={onRetry}>
          נסה שוב
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="error-state">
      <div className="error-icon">🎬</div>
      <p className="error-message">{message}</p>
    </div>
  );
}

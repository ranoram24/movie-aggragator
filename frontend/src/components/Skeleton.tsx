/** Placeholder cards shown while the grid loads.
 *  Skeletons rather than a spinner so the layout doesn't jump when posters land. */

import './Skeleton.css';

export function MovieGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="skeleton-grid" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton-card shimmer" />
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="skeleton-detail" aria-hidden="true">
      <div className="skeleton-hero shimmer" />
      <div className="skeleton-line shimmer" style={{ width: '60%' }} />
      <div className="skeleton-line shimmer" style={{ width: '40%' }} />
      <div className="skeleton-line shimmer" style={{ width: '90%' }} />
    </div>
  );
}

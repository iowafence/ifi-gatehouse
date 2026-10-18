// Decorative, CSS-only Evolus mascot (adapted from the supplied EvolusMascot component: the class is scoped under .bd-launch / .bid-desk in evolus-mascot.css).
// No images, fonts or network requests. The surrounding button or header carries the accessible name.
import type { CSSProperties } from 'react';
import './evolus-mascot.css';

export function EvolusMascot({ size = 31.2344 }: { size?: number }) {
  const style = { fontSize: `${size}px` } as CSSProperties;
  return <span className="evolusMascot" style={style} aria-hidden="true" />;
}

import { Link } from "react-router-dom";

/** Word mark. The only place where "モーラ" appears outside the mode tabs. */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" className={compact ? "brand brand--compact" : "brand"} aria-label="Mora モーラ — 返回曲库">
      <span className="brand-mark" aria-hidden="true">
        <span className="brand-petal" />
        <span className="brand-ring" />
      </span>
      <span className="brand-word">モーラ</span>
      {!compact && <span className="brand-latin">MORA</span>}
    </Link>
  );
}

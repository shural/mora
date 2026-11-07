/** Minimal boot/splash mark used while loading. */
export function Boot({ text = "正在打开…" }: { text?: string }) {
  return (
    <div className="boot">
      <span className="boot-mark" aria-hidden="true">
        <span className="brand-petal" />
        <span className="brand-ring" />
      </span>
      <p className="boot-text">{text}</p>
    </div>
  );
}

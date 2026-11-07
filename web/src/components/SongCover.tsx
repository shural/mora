/** Generated cover placeholder from SongSummary.thumbHue — no artwork needed. */
export function SongCover({
  title,
  hue,
  size = "md",
}: {
  title: string;
  hue: number;
  size?: "sm" | "md" | "lg";
}) {
  const glyph = Array.from(title)[0] ?? "♪";
  return (
    <div
      className={`cover cover--${size}`}
      aria-hidden="true"
      style={{
        backgroundImage: `linear-gradient(148deg, hsl(${hue} 52% 30%), hsl(${(hue + 46) % 360} 40% 13%) 72%)`,
      }}
    >
      <span className="cover-glyph">{glyph}</span>
      <span className="cover-shine" />
    </div>
  );
}

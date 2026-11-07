import type { RubySegment } from "../types";

/** <ruby> rendering. rt is 0.42em and muted — see the design tokens. */
export function RubyText({
  segments,
  showFurigana,
}: {
  segments: RubySegment[];
  showFurigana: boolean;
}) {
  return (
    <>
      {segments.map((segment, index) => {
        if (showFurigana && segment.rt !== undefined && segment.rt !== "") {
          return (
            <ruby key={`${index}-${segment.text}`}>
              {segment.text}
              <rt>{segment.rt}</rt>
            </ruby>
          );
        }
        return <span key={`${index}-${segment.text}`}>{segment.text}</span>;
      })}
    </>
  );
}

import { memo } from "react";
import type { Line, Token } from "../types";
import { cn } from "../lib/cn";
import {
  activeMoraIndex,
  effectiveEnd,
  effectiveStart,
  flattenMorae,
  moraSpansForToken,
} from "../lib/timing";
import { RubyText } from "../components/RubyText";
import { IconMic } from "../components/Icons";

export type LineState = "current" | "previous" | "next" | "far";

interface Props {
  line: Line;
  offset: number;
  time: number;
  state: LineState;
  furigana: boolean;
  romaji: boolean;
  translation: boolean;
  onSeek: (seconds: number) => void;
  onSing: () => void;
  measureRef: (element: HTMLDivElement | null) => void;
}

function TokenSpan({
  token,
  furigana,
  activeMora,
}: {
  token: Token;
  furigana: boolean;
  activeMora: number;
}) {
  const parts = moraSpansForToken(token.surface, token.kana, token.morae);
  if (parts !== null && token.morae.length > 0) {
    return (
      <span className="token">
        {parts.map((part, index) => (
          <span
            key={`${token.id}-${index}`}
            className={cn("mora-frag", index === activeMora && "is-now")}
          >
            {part}
          </span>
        ))}
      </span>
    );
  }
  return (
    <span className={cn("token", activeMora >= 0 && "is-now")}>
      <RubyText segments={token.ruby} showFurigana={furigana} />
    </span>
  );
}

export const KaraokeLine = memo(function KaraokeLine({
  line,
  offset,
  time,
  state,
  furigana,
  romaji,
  translation,
  onSeek,
  onSing,
  measureRef,
}: Props) {
  const start = effectiveStart(line, offset);
  const end = effectiveEnd(line, offset);
  const synced = start >= 0 && end > start;
  const slots = flattenMorae(line, offset);
  const activeIndex = synced ? activeMoraIndex(slots, start, end, time) : -1;
  const activeSlot = activeIndex >= 0 ? slots[activeIndex] : undefined;
  const isCurrent = state === "current";
  const romajiText = line.tokens
    .map((token) => token.romaji)
    .filter((value) => value !== "")
    .join(" ");

  const handleActivate = () => {
    if (start >= 0) onSeek(start);
  };

  return (
    <div ref={measureRef} className={cn("lyric-line", `is-${state}`)} data-line-id={line.id}>
      <div
        className="lyric-hit"
        role={start >= 0 ? "button" : undefined}
        tabIndex={start >= 0 ? 0 : undefined}
        aria-label={start >= 0 ? `跳到这一句 ${Math.round(start)} 秒` : undefined}
        onClick={handleActivate}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            handleActivate();
          }
        }}
      >
        <p className="lyric-text">
          {line.tokens.map((token) => (
            <TokenSpan
              key={token.id}
              token={token}
              furigana={furigana}
              activeMora={activeSlot !== undefined && activeSlot.tokenId === token.id
                ? activeSlot.moraInToken
                : -1}
            />
          ))}
        </p>

        {isCurrent && romaji && romajiText !== "" && <p className="lyric-romaji">{romajiText}</p>}

        {isCurrent && slots.length > 0 && (
          <div className="morae-ruler" aria-hidden="true">
            {slots.map((slot) => (
              <span
                key={slot.key}
                className={cn(
                  "mora-pill",
                  activeIndex >= 0 && slot.index < activeIndex && "is-sung",
                  slot.index === activeIndex && "is-now",
                )}
              />
            ))}
          </div>
        )}

        {isCurrent && translation && (
          <p className={cn("lyric-translation", line.glossZh === null && "is-missing")}>
            {line.glossZh ?? "暂无译文 · 可在「読む」里 AI 注释"}
          </p>
        )}

        {isCurrent && !synced && <span className="line-unsynced-hint">这一行还没有时间</span>}
      </div>

      {isCurrent && (
        <button
          type="button"
          className="line-sing"
          onClick={onSing}
          title="跟唱这一句（实验性）"
          aria-label="跟唱这一句"
        >
          <IconMic size={15} />
        </button>
      )}
    </div>
  );
});

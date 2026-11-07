import type { Line } from "../types";

/**
 * Timing is not on the wire: flatten line.tokens[].morae into one ruler and
 * distribute the morae evenly across [start, end]. The ruler is the single
 * source of truth for "what to highlight".
 */

export interface MoraSlot {
  /** stable key: `${tokenId}:${moraInToken}` */
  key: string;
  tokenId: string;
  tokenIndex: number;
  /** index within that token's morae */
  moraInToken: number;
  /** index in the flattened line ruler */
  index: number;
  mora: string;
  start: number;
  end: number;
}

export function effectiveStart(line: Line, offset: number): number {
  return line.start < 0 ? -1 : line.start + offset;
}

export function effectiveEnd(line: Line, offset: number): number {
  return line.end < 0 ? -1 : line.end + offset;
}

export function lineDuration(line: Line, offset: number): number {
  const start = effectiveStart(line, offset);
  const end = effectiveEnd(line, offset);
  if (start < 0 || end <= start) return 0;
  return end - start;
}

/** Flat morae ruler for a line. Punctuation tokens contribute zero slots. */
export function flattenMorae(line: Line, offset: number): MoraSlot[] {
  const slots: MoraSlot[] = [];
  const start = effectiveStart(line, offset);
  const end = effectiveEnd(line, offset);
  const synced = start >= 0 && end > start;
  const total = countMorae(line);
  let index = 0;
  line.tokens.forEach((token, tokenIndex) => {
    token.morae.forEach((mora, moraInToken) => {
      const slotStart = synced ? start + ((end - start) * index) / total : -1;
      const slotEnd = synced ? start + ((end - start) * (index + 1)) / total : -1;
      slots.push({
        key: `${token.id}:${moraInToken}`,
        tokenId: token.id,
        tokenIndex,
        moraInToken,
        index,
        mora,
        start: slotStart,
        end: slotEnd,
      });
      index += 1;
    });
  });
  return slots;
}

export function countMorae(line: Line): number {
  let total = 0;
  for (const token of line.tokens) total += token.morae.length;
  return total;
}

/** Index of the active mora in a flattened ruler, or -1. */
export function activeMoraIndex(slots: MoraSlot[], start: number, end: number, t: number): number {
  if (slots.length === 0) return -1;
  if (start < 0 || end <= start) return -1;
  if (t < start || t >= end) return -1;
  const ratio = (t - start) / (end - start);
  const index = Math.floor(ratio * slots.length);
  return Math.min(slots.length - 1, Math.max(0, index));
}

export interface ActiveLine {
  index: number;
  /** whether t is inside the line's [start, end) span */
  inside: boolean;
  /** countdown seconds until the line begins when it's still ahead */
  untilStart: number;
}

/** The lyric line the playhead is on (or the closest one). */
export function findActiveLine(lines: Line[], offset: number, t: number): ActiveLine {
  if (lines.length === 0) return { index: 0, inside: false, untilStart: 0 };
  let fallback = 0;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (line === undefined) continue;
    const start = effectiveStart(line, offset);
    const end = effectiveEnd(line, offset);
    if (start < 0 || end <= start) continue;
    if (t >= start && t < end) return { index: i, inside: true, untilStart: 0 };
    if (t < start) {
      if (i === 0) return { index: 0, inside: false, untilStart: start - t };
      break;
    }
    fallback = i;
  }
  return { index: fallback, inside: false, untilStart: 0 };
}

/** First/last timed line span — used to draw the vocal region on the seek bar. */
export function vocalRegion(lines: Line[], offset: number): { from: number; to: number } | null {
  const timed = lines
    .map((line) => ({ start: effectiveStart(line, offset), end: effectiveEnd(line, offset) }))
    .filter((span) => span.start >= 0 && span.end > span.start);
  if (timed.length === 0) return null;
  return { from: timed[0]?.start ?? 0, to: timed[timed.length - 1]?.end ?? 0 };
}

/** Character spans inside a token that map 1:1 to its morae, when possible. */
export function moraSpansForToken(
  surface: string,
  kana: string,
  morae: string[],
): string[] | null {
  const surfaceChars = Array.from(surface);
  const kanaChars = Array.from(kana);
  if (surfaceChars.length !== kanaChars.length) return null;
  const parts: string[] = [];
  let offset = 0;
  for (const mora of morae) {
    const len = Array.from(mora).length;
    if (surfaceChars.length - offset < len) return null;
    parts.push(surfaceChars.slice(offset, offset + len).join(""));
    offset += len;
  }
  if (offset !== surfaceChars.length) return null;
  return parts;
}

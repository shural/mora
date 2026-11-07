/**
 * Authoritative wire types — mirrors contract/CONTRACT.md exactly.
 * Nothing in here may drift from the contract.
 */

export type Naturalness = "green" | "yellow" | "red";

export type TokenFlag = "ateji" | "jodai" | "rare-reading" | "kanji-trap";

export interface RubySegment {
  text: string;
  rt?: string;
}

export interface Token {
  id: string;
  surface: string;
  ruby: RubySegment[];
  /** hiragana reading; "" for punctuation / space */
  kana: string;
  romaji: string;
  /** ["きょ","う"] — see mora rules */
  morae: string[];
  pos: string;
  dictForm: string | null;
  glossZh: string | null;
  naturalness: Naturalness | null;
  note: string | null;
  flags: TokenFlag[];
  saved: boolean;
}

export interface Line {
  id: string;
  text: string;
  /** seconds; -1 when unsynced */
  start: number;
  /** seconds; -1 when unsynced */
  end: number;
  glossZh: string | null;
  naturalness: Naturalness | null;
  note: string | null;
  tokens: Token[];
}

export interface Card {
  id: string;
  songId: string;
  lineId: string;
  tokenId: string;
  surface: string;
  kana: string;
  romaji: string;
  glossZh: string | null;
  lineText: string;
  /** slice into the song */
  start: number;
  end: number;
  sliceUrl: string;
  due: string;
  interval: number;
  ease: number;
  reps: number;
  lapses: number;
  createdAt: string;
}

export interface SongSummary {
  id: string;
  title: string;
  artist: string;
  duration: number;
  audioUrl: string;
  coverUrl: string | null;
  linesTotal: number;
  cards: number;
  synced: boolean;
  /** 0-360, for a generated gradient placeholder */
  thumbHue: number;
}

export interface Song {
  id: string;
  title: string;
  artist: string;
  duration: number;
  audioUrl: string;
  coverUrl: string | null;
  sourceUrl: string | null;
  /** seconds, added to every line time */
  offset: number;
  synced: boolean;
  createdAt: string;
  cards: Card[];
  lines: Line[];
}

export type JobStatus = "running" | "done" | "error";

export interface Job {
  id: string;
  kind: string;
  status: JobStatus;
  /** 0..100 */
  progress: number;
  message: string;
  songId?: string;
  result?: unknown;
}

export interface SingDiffItem {
  op: "eq" | "del" | "ins" | "sub";
  a?: string;
  b?: string;
}

export interface SingResult {
  targetKana: string;
  heardKana: string;
  diff: SingDiffItem[];
  /** 0..100 */
  score: number;
  moraeOk: number;
  moraeTotal: number;
  hint: string;
}

export interface SyncLineInput {
  lineId: string;
  start: number;
  end: number;
}

export interface Health {
  ok: boolean;
  ytdlp?: unknown;
  ffmpeg?: unknown;
  whisper?: { ok: boolean; model?: string; reason?: string };
  ollama?: { ok: boolean; model?: string; reason?: string };
  tokenizer?: string;
}

/** Narrow an unknown job payload to a song id without exposing `any`. */
export function jobSongId(job: Job | null): string | null {
  if (!job) return null;
  const result = job.result;
  if (typeof result !== "object" || result === null) return null;
  const candidate = (result as Record<string, unknown>).songId;
  return typeof candidate === "string" ? candidate : null;
}

export const NATURALNESS_LABEL: Record<Naturalness, string> = {
  green: "日常可用",
  yellow: "诗意但成立",
  red: "只存在于歌词",
};

export const NATURALNESS_DOT: Record<Naturalness, string> = {
  green: "🟢",
  yellow: "🟡",
  red: "🔴",
};

export const FLAG_LABEL: Record<TokenFlag, string> = {
  ateji: "当て字",
  jodai: "古语",
  "rare-reading": "特殊读法",
  "kanji-trap": "汉字陷阱",
};

import type {
  Card,
  Health,
  Job,
  Line,
  SingResult,
  Song,
  SongSummary,
  SyncLineInput,
  Token,
} from "../types";
import { ApiError } from "../lib/errors";
import { diffChars } from "../lib/diff";
import { romajiForToken, splitMorae, toHiragana } from "../lib/japanese";
import { flattenMorae } from "../lib/timing";
import songFixture from "./fixtures/song.json";
import summaryFixture from "./fixtures/songs.json";
import { EXTRA_CARDS, EXTRA_HUES, EXTRA_SONGS } from "./extra";

const FIXTURE_SONG = songFixture as unknown as Song;
const FIXTURE_SUMMARIES = summaryFixture as unknown as SongSummary[];

interface MockJobRecord {
  id: string;
  kind: "ingest" | "autosync" | "annotate";
  startedAt: number;
  durationMs: number;
  songId?: string;
  error?: { at: number; message: string };
  done: boolean;
  result?: unknown;
}

interface MockState {
  songs: Song[];
  jobs: Map<string, MockJobRecord>;
  seq: number;
}

const state: MockState = { songs: [], jobs: new Map(), seq: 1 };
let seeded = false;

const JOB_MESSAGES: Record<MockJobRecord["kind"], string[]> = {
  ingest: ["正在解析链接…", "正在读取音频信息…", "正在准备曲目…"],
  autosync: ["正在分析人声段落…", "正在对齐每一行…", "正在写入时间轴…"],
  annotate: ["正在阅读歌词…", "正在生成中文释义…", "正在标注自然度…"],
};

function fakeLatency(): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, 200 + Math.random() * 400);
  });
}

function hueFor(songId: string): number {
  const summary = FIXTURE_SUMMARIES.find((item) => item.id === songId);
  if (summary !== undefined) return summary.thumbHue;
  return EXTRA_HUES[songId] ?? 338;
}

function tokenSlice(song: Song, line: Line, token: Token): { start: number; end: number } {
  if (line.start < 0 || line.end <= line.start) {
    return { start: 0, end: 0.8 };
  }
  const slots = flattenMorae(line, song.offset).filter((slot) => slot.tokenId === token.id);
  const first = slots[0];
  const last = slots[slots.length - 1];
  if (first === undefined || last === undefined) {
    const start = line.start + song.offset;
    return { start, end: Math.min(start + 0.6, line.end + song.offset) };
  }
  return { start: first.start, end: last.end };
}

function makeCard(song: Song, line: Line, token: Token, due: string): Card {
  const slice = tokenSlice(song, line, token);
  return {
    id: `card_${state.seq++}`,
    songId: song.id,
    lineId: line.id,
    tokenId: token.id,
    surface: token.surface,
    kana: token.kana,
    romaji: token.romaji,
    glossZh: token.glossZh,
    lineText: line.text,
    start: slice.start,
    end: slice.end,
    sliceUrl: `/api/media/${song.id}/slice?start=${slice.start.toFixed(2)}&end=${slice.end.toFixed(
      2,
    )}&format=wav`,
    due,
    interval: 0,
    ease: 2.5,
    reps: 1,
    lapses: 0,
    createdAt: new Date().toISOString(),
  };
}

function findSong(songId: string): Song {
  const song = state.songs.find((item) => item.id === songId);
  if (song === undefined) throw new ApiError("找不到这首歌。", { status: 404 });
  return song;
}

function findLine(song: Song, lineId: string): Line {
  const line = song.lines.find((item) => item.id === lineId);
  if (line === undefined) throw new ApiError("找不到这一行歌词。", { status: 404 });
  return line;
}

function findToken(line: Line, tokenId: string): Token {
  const token = line.tokens.find((item) => item.id === tokenId);
  if (token === undefined) throw new ApiError("找不到这个词。", { status: 404 });
  return token;
}

function ensureSeeded(): void {
  if (seeded) return;
  seeded = true;

  state.songs.push(structuredClone(FIXTURE_SONG));
  for (const extra of EXTRA_SONGS) {
    state.songs.push(structuredClone(extra));
  }

  for (const spec of EXTRA_CARDS) {
    const song = findSong(spec.songId);
    const line = findLine(song, spec.lineId);
    const token = findToken(line, spec.tokenId);
    if (song.cards.some((card) => card.tokenId === token.id)) continue;
    song.cards.push(makeCard(song, line, token, new Date().toISOString()));
    token.saved = true;
  }

  // These are demo cards: make them due now so 覚える has something to review.
  const now = Date.now();
  let offset = 0;
  for (const song of state.songs) {
    for (const card of song.cards) {
      card.due = new Date(now - (offset + 1) * 45_000).toISOString();
      offset += 1;
    }
  }
}

function summarize(song: Song): SongSummary {
  const synced =
    song.synced && song.lines.length > 0 && song.lines.every((line) => line.start >= 0);
  return {
    id: song.id,
    title: song.title,
    artist: song.artist,
    duration: song.duration,
    audioUrl: song.audioUrl,
    coverUrl: song.coverUrl,
    linesTotal: song.lines.length,
    cards: song.cards.length,
    synced,
    thumbHue: hueFor(song.id),
  };
}

function resyncTokenReading(token: Token, kana: string): void {
  token.kana = toHiragana(kana);
  token.morae = splitMorae(token.kana);
  token.romaji = romajiForToken(token.kana, token.pos);
  token.ruby = [{ text: token.surface, rt: token.kana }];
}

function refreshLineSyncFlags(song: Song): void {
  song.synced = song.lines.length > 0 && song.lines.every((line) => line.start >= 0);
}

function refreshCardsForLines(song: Song, lineIds: Set<string>): void {
  for (const card of song.cards) {
    if (!lineIds.has(card.lineId)) continue;
    const line = song.lines.find((item) => item.id === card.lineId);
    if (line === undefined) continue;
    const token = line.tokens.find((item) => item.id === card.tokenId);
    if (token === undefined) continue;
    const slice = tokenSlice(song, line, token);
    card.start = slice.start;
    card.end = slice.end;
    card.kana = token.kana;
    card.romaji = token.romaji;
    card.glossZh = token.glossZh;
    card.sliceUrl = `/api/media/${song.id}/slice?start=${slice.start.toFixed(2)}&end=${slice.end.toFixed(
      2,
    )}&format=wav`;
  }
}

function jobFor(record: MockJobRecord): Job {
  return {
    id: record.id,
    kind: record.kind,
    status: "running",
    progress: 0,
    message: JOB_MESSAGES[record.kind][0] ?? "处理中…",
    ...(record.songId !== undefined ? { songId: record.songId } : {}),
  };
}

function startJob(kind: MockJobRecord["kind"], options?: { songId?: string; fail?: boolean }): Job {
  const record: MockJobRecord = {
    id: `job_${state.seq++}`,
    kind,
    startedAt: Date.now(),
    durationMs: 2000,
    done: false,
    ...(options?.songId !== undefined ? { songId: options.songId } : {}),
    ...(options?.fail === true
      ? { error: { at: 950, message: "演示模式：任务失败（输入中包含 fail）。" } }
      : {}),
  };
  state.jobs.set(record.id, record);
  return jobFor(record);
}

function finalizeJob(record: MockJobRecord): void {
  if (record.kind === "ingest") {
    const first = state.songs[0];
    record.result = { songId: first?.id ?? FIXTURE_SONG.id };
    return;
  }
  if (record.kind === "autosync" && record.songId !== undefined) {
    const song = findSong(record.songId);
    const lines = song.lines;
    const count = lines.length;
    if (count > 0) {
      const intro = 2;
      const outro = 4;
      const span = Math.max(1, song.duration - intro - outro);
      const step = span / count;
      lines.forEach((line, index) => {
        line.start = Number((intro + step * index).toFixed(2));
        line.end = Number((intro + step * index + step * 0.84).toFixed(2));
      });
      refreshLineSyncFlags(song);
      refreshCardsForLines(song, new Set(lines.map((line) => line.id)));
    }
    record.result = { songId: song.id };
    return;
  }
  if (record.kind === "annotate" && record.songId !== undefined) {
    record.result = { songId: record.songId };
  }
}

function finishedJob(record: MockJobRecord): Job {
  return {
    id: record.id,
    kind: record.kind,
    status: "done",
    progress: 100,
    message: "完成",
    ...(record.songId !== undefined ? { songId: record.songId } : {}),
    ...(record.result !== undefined ? { result: record.result } : {}),
  };
}

function jobProgress(record: MockJobRecord, elapsed: number): number {
  return Math.min(97, Math.max(3, Math.round((elapsed / record.durationMs) * 96)));
}

function jobMessage(record: MockJobRecord, progress: number): string {
  const messages = JOB_MESSAGES[record.kind];
  if (progress > 80) return messages[2] ?? "收尾中…";
  if (progress > 42) return messages[1] ?? "处理中…";
  return messages[0] ?? "处理中…";
}

export const mockApi = {
  async health(): Promise<Health> {
    await fakeLatency();
    return {
      ok: true,
      ytdlp: true,
      ffmpeg: true,
      whisper: { ok: true, model: "small" },
      ollama: { ok: true, model: "qwen2.5" },
      tokenizer: "fugashi",
    };
  },

  async listSongs(): Promise<SongSummary[]> {
    ensureSeeded();
    await fakeLatency();
    return state.songs.map(summarize);
  },

  async getSong(songId: string): Promise<Song> {
    ensureSeeded();
    await fakeLatency();
    return structuredClone(findSong(songId));
  },

  async deleteSong(songId: string): Promise<{ ok: boolean }> {
    ensureSeeded();
    await fakeLatency();
    const index = state.songs.findIndex((song) => song.id === songId);
    if (index < 0) throw new ApiError("找不到这首歌。", { status: 404 });
    state.songs.splice(index, 1);
    return { ok: true };
  },

  async patchSong(
    songId: string,
    patch: Partial<Pick<Song, "title" | "artist" | "offset">>,
  ): Promise<Song> {
    ensureSeeded();
    await fakeLatency();
    const song = findSong(songId);
    if (patch.title !== undefined) song.title = patch.title;
    if (patch.artist !== undefined) song.artist = patch.artist;
    if (patch.offset !== undefined) song.offset = patch.offset;
    return structuredClone(song);
  },

  async postLyrics(songId: string, _text: string): Promise<Song> {
    ensureSeeded();
    await fakeLatency();
    findSong(songId);
    throw new ApiError("演示模式没有分词器，请连接后端后再重新粘贴歌词。");
  },

  async patchLine(
    songId: string,
    lineId: string,
    patch: Partial<Pick<Line, "start" | "end" | "naturalness" | "note" | "glossZh">>,
  ): Promise<Song> {
    ensureSeeded();
    await fakeLatency();
    const song = findSong(songId);
    const line = findLine(song, lineId);
    if (patch.start !== undefined) line.start = patch.start;
    if (patch.end !== undefined) line.end = patch.end;
    if (patch.naturalness !== undefined) line.naturalness = patch.naturalness;
    if (patch.note !== undefined) line.note = patch.note;
    if (patch.glossZh !== undefined) line.glossZh = patch.glossZh;
    refreshLineSyncFlags(song);
    refreshCardsForLines(song, new Set([line.id]));
    return structuredClone(song);
  },

  async patchToken(
    songId: string,
    tokenId: string,
    patch: { kana?: string; glossZh?: string | null; note?: string | null },
  ): Promise<Song> {
    ensureSeeded();
    await fakeLatency();
    const song = findSong(songId);
    for (const line of song.lines) {
      const token = line.tokens.find((item) => item.id === tokenId);
      if (token === undefined) continue;
      if (patch.kana !== undefined) {
        const kana = patch.kana.trim();
        if (kana === "") throw new ApiError("读音不能为空。", { status: 400 });
        resyncTokenReading(token, kana);
      }
      if (patch.glossZh !== undefined) token.glossZh = patch.glossZh;
      if (patch.note !== undefined) token.note = patch.note;
      for (const card of song.cards) {
        if (card.tokenId !== token.id) continue;
        card.kana = token.kana;
        card.romaji = token.romaji;
        card.glossZh = token.glossZh;
      }
      return structuredClone(song);
    }
    throw new ApiError("找不到这个词。", { status: 404 });
  },

  async putSync(songId: string, lines: SyncLineInput[]): Promise<Song> {
    ensureSeeded();
    await fakeLatency();
    const song = findSong(songId);
    const byId = new Map(lines.map((line) => [line.lineId, line]));
    for (const line of song.lines) {
      const input = byId.get(line.id);
      if (input === undefined) continue;
      line.start = Number.isFinite(input.start) ? Math.max(0, input.start) : -1;
      line.end = Number.isFinite(input.end) ? Math.max(line.start + 0.2, input.end) : -1;
    }
    refreshLineSyncFlags(song);
    refreshCardsForLines(song, new Set(byId.keys()));
    return structuredClone(song);
  },

  async ingest(query: string): Promise<{ jobId: string }> {
    ensureSeeded();
    await fakeLatency();
    const job = startJob("ingest", { fail: /fail|失败/i.test(query) });
    return { jobId: job.id };
  },

  async autosync(songId: string): Promise<{ jobId: string }> {
    ensureSeeded();
    await fakeLatency();
    findSong(songId);
    const job = startJob("autosync", { songId });
    return { jobId: job.id };
  },

  async annotate(songId: string): Promise<{ jobId: string }> {
    ensureSeeded();
    await fakeLatency();
    findSong(songId);
    const job = startJob("annotate", { songId });
    return { jobId: job.id };
  },

  async getJob(jobId: string): Promise<Job> {
    ensureSeeded();
    const record = state.jobs.get(jobId);
    if (record === undefined) throw new ApiError("任务不存在或已过期。", { status: 404 });
    const elapsed = Date.now() - record.startedAt;
    if (record.error !== undefined && elapsed >= record.error.at) {
      return {
        id: record.id,
        kind: record.kind,
        status: "error",
        progress: jobProgress(record, elapsed),
        message: record.error.message,
        ...(record.songId !== undefined ? { songId: record.songId } : {}),
      };
    }
    if (elapsed >= record.durationMs) {
      if (!record.done) {
        record.done = true;
        finalizeJob(record);
      }
      return finishedJob(record);
    }
    const progress = jobProgress(record, elapsed);
    return {
      ...jobFor(record),
      progress,
      message: jobMessage(record, progress),
    };
  },

  async listCards(): Promise<Card[]> {
    ensureSeeded();
    await fakeLatency();
    const cards = state.songs.flatMap((song) => song.cards);
    return structuredClone(cards).sort((a, b) => a.due.localeCompare(b.due));
  },

  async createCard(body: { songId: string; lineId: string; tokenId: string }): Promise<Card> {
    ensureSeeded();
    await fakeLatency();
    const song = findSong(body.songId);
    const line = findLine(song, body.lineId);
    const token = findToken(line, body.tokenId);
    const existing = song.cards.find((card) => card.tokenId === token.id);
    if (existing !== undefined) return structuredClone(existing);
    const card = makeCard(song, line, token, new Date().toISOString());
    song.cards.push(card);
    token.saved = true;
    return structuredClone(card);
  },

  async deleteCard(cardId: string): Promise<{ ok: boolean }> {
    ensureSeeded();
    await fakeLatency();
    for (const song of state.songs) {
      const index = song.cards.findIndex((card) => card.id === cardId);
      if (index < 0) continue;
      const [removed] = song.cards.splice(index, 1);
      if (removed !== undefined) {
        for (const line of song.lines) {
          const token = line.tokens.find((item) => item.id === removed.tokenId);
          if (token === undefined) continue;
          token.saved = song.cards.some((card) => card.tokenId === token.id);
        }
      }
      return { ok: true };
    }
    throw new ApiError("找不到这张卡片。", { status: 404 });
  },

  async reviewCard(cardId: string, grade: 0 | 1 | 2 | 3): Promise<Card> {
    ensureSeeded();
    await fakeLatency();
    for (const song of state.songs) {
      const card = song.cards.find((item) => item.id === cardId);
      if (card === undefined) continue;
      const now = Date.now();
      if (grade === 0) {
        card.lapses += 1;
        card.interval = 0;
        card.ease = Math.max(1.3, card.ease - 0.2);
        card.due = new Date(now + 10 * 60_000).toISOString();
      } else {
        card.reps += 1;
        if (grade === 1) {
          card.ease = Math.max(1.3, card.ease - 0.15);
          card.interval = Math.max(1, Math.round(Math.max(1, card.interval) * 1.2));
        } else if (grade === 2) {
          card.interval = Math.max(1, Math.round(Math.max(1, card.interval) * 1.8));
        } else {
          card.ease = Math.min(3.2, card.ease + 0.1);
          card.interval = Math.max(
            1,
            Math.round(Math.max(1, card.interval) * card.ease),
          );
        }
        card.due = new Date(now + card.interval * 86_400_000).toISOString();
      }
      return structuredClone(card);
    }
    throw new ApiError("找不到这张卡片。", { status: 404 });
  },

  async sing(songId: string, lineId: string, _audio: Blob): Promise<SingResult> {
    ensureSeeded();
    await fakeLatency();
    const song = findSong(songId);
    const line = findLine(song, lineId);
    const targetMorae = line.tokens.flatMap((token) => token.morae);
    const targetKana = line.tokens.map((token) => token.kana).join("");
    const heardMorae = [...targetMorae];
    if (heardMorae.length >= 3) {
      heardMorae.splice(Math.floor(heardMorae.length * 0.55), 1);
      const filler = ["ら", "ね", "の"][heardMorae.length % 3] ?? "ら";
      heardMorae.splice(Math.min(heardMorae.length, Math.floor(heardMorae.length * 0.9)), 0, filler);
    }
    const heardKana = heardMorae.join("");
    const diff = diffChars(targetKana, heardKana);
    const equal = diff.filter((item) => item.op === "eq").length;
    const score =
      targetKana.length > 0 ? Math.round((equal / Array.from(targetKana).length) * 100) : 0;
    const moraeTotal = targetMorae.length;
    const moraeOk = Math.max(0, moraeTotal - 1);
    const hint =
      score >= 90
        ? "很稳，长音再拖满一点就更好了。"
        : score >= 70
          ? "大部分都对了，漏掉的那一拍再跟一次。"
          : "有几处没跟上，先把速度调到 0.75× 再试。";
    return {
      targetKana,
      heardKana,
      diff,
      score,
      moraeOk,
      moraeTotal,
      hint,
    };
  },
};

export type MockApi = typeof mockApi;

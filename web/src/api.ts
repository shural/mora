import type {
  Card,
  Health,
  Job,
  Line,
  SingResult,
  Song,
  SongSummary,
  SyncLineInput,
} from "./types";
import { ApiError } from "./lib/errors";
import { mockApi } from "./mock";

/**
 * Mock switch.
 *
 * - VITE_MOCK unset: mock in `vite dev`, live API in a production build.
 * - VITE_MOCK=1 / true: always mock.
 * - VITE_MOCK=0 / false: always live.
 *
 * In a production build the app pings /api/health once; if the backend is not
 * there it falls back to mock with a visible 「演示数据」 badge instead of a
 * blank screen.
 */
const rawMock = import.meta.env.VITE_MOCK as string | undefined;
const mockFlagProvided = typeof rawMock === "string" && rawMock.trim() !== "";

function truthyFlag(value: string): boolean {
  return ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
}

export const USE_MOCK: boolean = mockFlagProvided ? truthyFlag(rawMock) : import.meta.env.DEV;

export type RuntimeMode = "mock" | "live";

let runtimeMode: RuntimeMode = USE_MOCK ? "mock" : "live";
let mockFallback = false;
const modeListeners = new Set<(mode: RuntimeMode) => void>();

export function getRuntimeMode(): RuntimeMode {
  return runtimeMode;
}

export function isMock(): boolean {
  return runtimeMode === "mock";
}

/** True when mock mode was entered because the real backend was unreachable. */
export function isMockFallback(): boolean {
  return mockFallback;
}

export function subscribeRuntimeMode(listener: (mode: RuntimeMode) => void): () => void {
  modeListeners.add(listener);
  return () => {
    modeListeners.delete(listener);
  };
}

function setRuntimeMode(mode: RuntimeMode): void {
  if (runtimeMode === mode) return;
  runtimeMode = mode;
  for (const listener of modeListeners) listener(mode);
}

export function enableMockFallback(): void {
  mockFallback = true;
  setRuntimeMode("mock");
}

/** Called once at boot in production builds. Never throws. */
export async function detectBackend(): Promise<RuntimeMode> {
  if (USE_MOCK) return "mock";
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 1600);
  try {
    const response = await fetch("/api/health", {
      signal: controller.signal,
      headers: { Accept: "application/json" },
    });
    if (response.ok) {
      setRuntimeMode("live");
      return "live";
    }
  } catch {
    // fall through to mock
  } finally {
    window.clearTimeout(timeout);
  }
  mockFallback = true;
  setRuntimeMode("mock");
  return "mock";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...init?.headers,
      },
    });
  } catch (error) {
    throw new ApiError("无法连接到本地后端，请确认 server 已启动。", {
      detail: error instanceof Error ? error.message : undefined,
    });
  }

  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    let detail: string | undefined;
    try {
      const body: unknown = await response.json();
      if (typeof body === "object" && body !== null) {
        const record = body as Record<string, unknown>;
        if (typeof record.error === "string" && record.error.trim() !== "") {
          message = record.error;
        }
        if (typeof record.detail === "string") detail = record.detail;
      }
    } catch {
      // non-JSON error body — keep the generic Chinese message
    }
    throw new ApiError(message, { status: response.status, detail });
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function getHealth(): Promise<Health> {
  if (isMock()) return mockApi.health();
  return request<Health>("/api/health");
}

export async function listSongs(): Promise<SongSummary[]> {
  if (isMock()) return mockApi.listSongs();
  return request<SongSummary[]>("/api/songs");
}

export async function getSong(songId: string): Promise<Song> {
  if (isMock()) return mockApi.getSong(songId);
  return request<Song>(`/api/songs/${encodeURIComponent(songId)}`);
}

export async function deleteSong(songId: string): Promise<{ ok: boolean }> {
  if (isMock()) return mockApi.deleteSong(songId);
  return request<{ ok: boolean }>(`/api/songs/${encodeURIComponent(songId)}`, {
    method: "DELETE",
  });
}

export async function patchSong(
  songId: string,
  patch: Partial<Pick<Song, "title" | "artist" | "offset">>,
): Promise<Song> {
  if (isMock()) return mockApi.patchSong(songId, patch);
  return request<Song>(`/api/songs/${encodeURIComponent(songId)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function postLyrics(songId: string, text: string): Promise<Song> {
  if (isMock()) return mockApi.postLyrics(songId, text);
  return request<Song>(`/api/songs/${encodeURIComponent(songId)}/lyrics`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function patchLine(
  songId: string,
  lineId: string,
  patch: Partial<Pick<Line, "start" | "end" | "naturalness" | "note" | "glossZh">>,
): Promise<Song> {
  if (isMock()) return mockApi.patchLine(songId, lineId, patch);
  return request<Song>(
    `/api/songs/${encodeURIComponent(songId)}/lines/${encodeURIComponent(lineId)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
}

export async function patchToken(
  songId: string,
  tokenId: string,
  patch: { kana?: string; glossZh?: string | null; note?: string | null },
): Promise<Song> {
  if (isMock()) return mockApi.patchToken(songId, tokenId, patch);
  return request<Song>(
    `/api/songs/${encodeURIComponent(songId)}/tokens/${encodeURIComponent(tokenId)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
  );
}

export async function putSync(songId: string, lines: SyncLineInput[]): Promise<Song> {
  if (isMock()) return mockApi.putSync(songId, lines);
  return request<Song>(`/api/songs/${encodeURIComponent(songId)}/sync`, {
    method: "PUT",
    body: JSON.stringify({ lines }),
  });
}

export async function ingest(query: string): Promise<{ jobId: string }> {
  if (isMock()) return mockApi.ingest(query);
  return request<{ jobId: string }>("/api/ingest", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export async function autosync(songId: string): Promise<{ jobId: string }> {
  if (isMock()) return mockApi.autosync(songId);
  return request<{ jobId: string }>(`/api/songs/${encodeURIComponent(songId)}/autosync`, {
    method: "POST",
  });
}

export async function annotate(songId: string): Promise<{ jobId: string }> {
  if (isMock()) return mockApi.annotate(songId);
  return request<{ jobId: string }>(`/api/songs/${encodeURIComponent(songId)}/annotate`, {
    method: "POST",
  });
}

export async function getJob(jobId: string): Promise<Job> {
  if (isMock()) return mockApi.getJob(jobId);
  return request<Job>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export async function listCards(): Promise<Card[]> {
  if (isMock()) return mockApi.listCards();
  return request<Card[]>("/api/cards");
}

export async function createCard(body: {
  songId: string;
  lineId: string;
  tokenId: string;
}): Promise<Card> {
  if (isMock()) return mockApi.createCard(body);
  return request<Card>("/api/cards", { method: "POST", body: JSON.stringify(body) });
}

export async function deleteCard(cardId: string): Promise<{ ok: boolean }> {
  if (isMock()) return mockApi.deleteCard(cardId);
  return request<{ ok: boolean }>(`/api/cards/${encodeURIComponent(cardId)}`, {
    method: "DELETE",
  });
}

export async function reviewCard(cardId: string, grade: 0 | 1 | 2 | 3): Promise<Card> {
  if (isMock()) return mockApi.reviewCard(cardId, grade);
  return request<Card>(`/api/cards/${encodeURIComponent(cardId)}/review`, {
    method: "POST",
    body: JSON.stringify({ grade }),
  });
}

export async function sing(songId: string, lineId: string, audio: Blob): Promise<SingResult> {
  if (isMock()) return mockApi.sing(songId, lineId, audio);
  const form = new FormData();
  form.append("file", audio, "take.webm");
  return request<SingResult>(
    `/api/songs/${encodeURIComponent(songId)}/lines/${encodeURIComponent(lineId)}/sing`,
    { method: "POST", body: form },
  );
}

/** Error type shared by the API layer and mock mode. Never a raw exception. */

export class ApiError extends Error {
  readonly status?: number;
  readonly detail?: string;

  constructor(message: string, options?: { status?: number; detail?: string }) {
    super(message);
    this.name = "ApiError";
    this.status = options?.status;
    this.detail = options?.detail;
  }
}

const NETWORK_HINTS = [
  "failed to fetch",
  "networkerror",
  "network error",
  "load failed",
  "network request failed",
  "fetch failed",
];

/** Turn anything thrown into a Chinese sentence we are willing to show a user. */
export function toMessage(error: unknown, fallback = "出了点问题，请稍后再试。"): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") return "浏览器没有授予权限，请检查设置。";
    if (error.name === "NotFoundError") return "没有找到可用的麦克风。";
    if (error.name === "NotReadableError") return "麦克风被其他程序占用了。";
    return fallback;
  }
  if (error instanceof Error) {
    const message = error.message.trim();
    const lowered = message.toLowerCase();
    if (NETWORK_HINTS.some((hint) => lowered.includes(hint))) {
      return "无法连接到本地后端，请确认 server 已启动。";
    }
    // Do not leak raw stack/technical text into the UI.
    return fallback;
  }
  return fallback;
}

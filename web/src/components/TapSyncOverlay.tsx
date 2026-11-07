import { useCallback, useEffect, useRef, useState } from "react";
import type { Song, SyncLineInput } from "../types";
import { cn } from "../lib/cn";
import { formatTime } from "../lib/format";
import { IconClose } from "./Icons";

interface Props {
  song: Song;
  /** Playhead getter supplied by the karaoke transport. */
  getTime: () => number;
  onStart: () => void;
  /** Returns null on success, or a Chinese error message. */
  onSave: (lines: SyncLineInput[]) => Promise<string | null>;
  onCancel: () => void;
}

/**
 * Tap-to-sync overlay: Space records the playhead as the next line's start and
 * the previous line's end. Esc cancels without writing anything.
 */
export function TapSyncOverlay({ song, getTime, onStart, onSave, onCancel }: Props) {
  const [recorded, setRecorded] = useState<Array<{ lineId: string; start: number }>>([]);
  const [finalEnd, setFinalEnd] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const getTimeRef = useRef(getTime);
  const onSaveRef = useRef(onSave);
  const onCancelRef = useRef(onCancel);
  getTimeRef.current = getTime;
  onSaveRef.current = onSave;
  onCancelRef.current = onCancel;

  useEffect(() => {
    onStart();
    return () => {
      mounted.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Live clock while the song plays underneath.
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      setNow(getTimeRef.current());
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  const buildLines = useCallback((): SyncLineInput[] => {
    if (recorded.length === 0) return [];
    return recorded.map((item, index) => {
      const next = recorded[index + 1];
      let end =
        next !== undefined
          ? next.start
          : (finalEnd ?? Math.max(getTimeRef.current(), item.start + 0.8));
      if (end <= item.start + 0.15) end = item.start + 0.8;
      return {
        lineId: item.lineId,
        start: Number(item.start.toFixed(2)),
        end: Number(end.toFixed(2)),
      };
    });
  }, [recorded, finalEnd]);

  const save = useCallback(async () => {
    if (saving) return;
    const lines = buildLines();
    if (lines.length === 0) {
      setError("先按空格，给至少一行打点。");
      return;
    }
    setSaving(true);
    setError(null);
    const message = await onSaveRef.current(lines);
    if (!mounted.current) return;
    setSaving(false);
    if (message !== null) setError(message);
  }, [buildLines, saving]);

  const tap = useCallback(() => {
    if (saving) return;
    if (finalEnd !== null) {
      void save();
      return;
    }
    if (recorded.length >= song.lines.length) {
      setFinalEnd(Number(getTimeRef.current().toFixed(2)));
      return;
    }
    const line = song.lines[recorded.length];
    if (line === undefined) return;
    const start = Math.max(0, getTimeRef.current());
    setRecorded((previous) => [...previous, { lineId: line.id, start: Number(start.toFixed(2)) }]);
  }, [recorded.length, finalEnd, saving, save, song.lines]);

  const undo = useCallback(() => {
    setRecorded((previous) => previous.slice(0, -1));
    setFinalEnd(null);
  }, []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.code === "Space") {
        event.preventDefault();
        tap();
        return;
      }
      if (event.code === "Backspace") {
        event.preventDefault();
        undo();
        return;
      }
      if (event.code === "Escape") {
        event.preventDefault();
        onCancelRef.current();
        return;
      }
      if (event.code === "Enter") {
        event.preventDefault();
        void save();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tap, undo, save]);

  const currentLine = song.lines[recorded.length];
  const tappedAll = recorded.length >= song.lines.length;
  const hint = tappedAll
    ? finalEnd === null
      ? "最后一句开始了。再按一次空格，标记它结束的位置。"
      : "再按一次空格，或点「保存」写入时间轴。"
    : "听到这一句开始唱时，按空格。";

  return (
    <div className="tap-overlay" role="dialog" aria-modal="true" aria-label="打点对齐">
      <header className="tap-top">
        <div className="tap-kicker">打点对齐</div>
        <div className="tap-count">
          {Math.min(recorded.length, song.lines.length)} / {song.lines.length} 行
        </div>
        <button
          type="button"
          className="icon-btn tap-close"
          onClick={() => onCancelRef.current()}
          aria-label="取消打点"
        >
          <IconClose size={18} />
        </button>
      </header>

      <main className="tap-main">
        <div className="tap-live">
          <span className="tap-live-dot" aria-hidden="true" />
          正在播放
          <span className="tap-live-time">{formatTime(now)}</span>
        </div>
        {currentLine !== undefined ? (
          <p className="tap-line" lang="ja">
            {currentLine.text}
          </p>
        ) : (
          <p className="tap-line tap-line--end" lang="ja">
            {song.lines[song.lines.length - 1]?.text ?? ""}
          </p>
        )}
        <p className="tap-hint">{hint}</p>
      </main>

      <div className="tap-dots" aria-hidden="true">
        {song.lines.map((line, index) => (
          <span
            key={line.id}
            className={cn(
              "tap-dot",
              index < recorded.length && "is-done",
              index === recorded.length && finalEnd === null && "is-now",
            )}
          />
        ))}
      </div>

      <footer className="tap-foot">
        <div className="tap-keys">
          <span>
            <kbd>空格</kbd> 打点
          </span>
          <span>
            <kbd>⌫</kbd> 撤销
          </span>
          <span>
            <kbd>Esc</kbd> 取消
          </span>
        </div>
        <div className="tap-buttons">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={undo}
            disabled={recorded.length === 0 || saving}
          >
            撤销
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void save()}
            disabled={saving || recorded.length === 0}
          >
            {saving ? "保存中…" : `保存 ${recorded.length} 行`}
          </button>
        </div>
        {error !== null && (
          <p className="tap-error" role="alert">
            {error}
          </p>
        )}
      </footer>
    </div>
  );
}

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { autosync, getSong, putSync } from "../api";
import type { Song, SyncLineInput } from "../types";
import { useJobPoller } from "../hooks/useJobPoller";
import { useLocalStorage } from "../hooks/useLocalStorage";
import { usePlayback } from "../hooks/usePlayback";
import { useToast } from "../components/Toast";
import { JobProgress } from "../components/JobProgress";
import { SingBackPanel } from "../components/SingBackPanel";
import { TapSyncOverlay } from "../components/TapSyncOverlay";
import {
  IconClose,
  IconKeyboard,
  IconLoop,
  IconPause,
  IconPlay,
  IconWarning,
} from "../components/Icons";
import { cn } from "../lib/cn";
import { isEditableTarget } from "../lib/dom";
import { toMessage } from "../lib/errors";
import { formatTime } from "../lib/format";
import { findActiveLine, vocalRegion } from "../lib/timing";
import { KaraokeLine, type LineState } from "./KaraokeLine";

interface KaraokePrefs {
  furigana: boolean;
  romaji: boolean;
  translation: boolean;
  tempo: number;
}

const DEFAULT_PREFS: KaraokePrefs = {
  furigana: true,
  romaji: true,
  translation: false,
  tempo: 1,
};

const TEMPOS = [0.5, 0.65, 0.75, 0.9, 1] as const;
const PREFS_KEY = "mora.karaoke.prefs.v1";

function isTempo(value: number): boolean {
  return TEMPOS.some((tempo) => tempo === value);
}

function normalizePrefs(value: KaraokePrefs): KaraokePrefs {
  return {
    furigana: typeof value.furigana === "boolean" ? value.furigana : true,
    romaji: typeof value.romaji === "boolean" ? value.romaji : true,
    translation: typeof value.translation === "boolean" ? value.translation : false,
    tempo: isTempo(value.tempo) ? value.tempo : 1,
  };
}

function tempoLabel(tempo: number): string {
  return tempo === 1 ? "1.0×" : `${tempo.toString().replace(/^0/, "")}×`;
}

interface Props {
  song: Song;
  onSongChange: (song: Song) => void;
  mock: boolean;
}

export function Karaoke({ song, onSongChange, mock }: Props) {
  const [storedPrefs, setStoredPrefs] = useLocalStorage<KaraokePrefs>(PREFS_KEY, DEFAULT_PREFS);
  const prefs = useMemo(() => normalizePrefs(storedPrefs), [storedPrefs]);
  const { toast } = useToast();
  const autosyncJob = useJobPoller();

  const [tapSyncOpen, setTapSyncOpen] = useState(false);
  const [singLineId, setSingLineId] = useState<string | null>(null);
  const [hover, setHover] = useState<{ seconds: number; ratio: number } | null>(null);

  const playback = usePlayback({ src: song.audioUrl, duration: song.duration, mock });
  const playbackRef = useRef(playback);
  playbackRef.current = playback;

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const lineElements = useRef(new Map<string, HTMLDivElement>());
  const lineRefCallbacks = useRef(new Map<string, (element: HTMLDivElement | null) => void>());
  const manualScrollUntil = useRef(0);

  const active = findActiveLine(song.lines, song.offset, playback.time);
  const synced =
    song.lines.length > 0 && song.lines.every((line) => line.start >= 0);
  const singLine =
    singLineId === null ? null : (song.lines.find((line) => line.id === singLineId) ?? null);

  const duration = Math.max(1, playback.duration > 0 ? playback.duration : song.duration);
  const progress = Math.min(1, Math.max(0, playback.time / duration));
  const region = vocalRegion(song.lines, song.offset);

  const getLineRef = useCallback((lineId: string) => {
    const existing = lineRefCallbacks.current.get(lineId);
    if (existing !== undefined) return existing;
    const callback = (element: HTMLDivElement | null) => {
      if (element === null) lineElements.current.delete(lineId);
      else lineElements.current.set(lineId, element);
    };
    lineRefCallbacks.current.set(lineId, callback);
    return callback;
  }, []);

  // Auto-scroll: keep the active line centered, without fighting the user.
  useEffect(() => {
    if (Date.now() < manualScrollUntil.current) return;
    const container = scrollRef.current;
    const line = song.lines[active.index];
    if (container === null || line === undefined) return;
    const element = lineElements.current.get(line.id);
    if (element === undefined) return;
    const containerRect = container.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();
    const target =
      container.scrollTop +
      (elementRect.top - containerRect.top) -
      (containerRect.height - elementRect.height) / 2;
    container.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
  }, [active.index, song.lines, singLine]);

  useEffect(() => {
    const container = scrollRef.current;
    if (container === null) return;
    const markManual = () => {
      manualScrollUntil.current = Date.now() + 2600;
    };
    container.addEventListener("wheel", markManual, { passive: true });
    container.addEventListener("touchstart", markManual, { passive: true });
    return () => {
      container.removeEventListener("wheel", markManual);
      container.removeEventListener("touchstart", markManual);
    };
  }, []);

  // Tempo: playbackRate + preservesPitch lives in usePlayback.
  const setPlaybackRate = playback.setRate;
  useEffect(() => {
    setPlaybackRate(prefs.tempo);
  }, [prefs.tempo, setPlaybackRate]);

  const togglePref = useCallback(
    (key: "furigana" | "romaji" | "translation") => {
      setStoredPrefs((previous) => {
        const normalized = normalizePrefs(previous);
        return { ...normalized, [key]: !normalized[key] };
      });
    },
    [setStoredPrefs],
  );

  const setTempo = useCallback(
    (tempo: number) => {
      setStoredPrefs((previous) => ({ ...normalizePrefs(previous), tempo }));
    },
    [setStoredPrefs],
  );

  // Global shortcuts (karaoke only). Overlays swallow keys while they are open.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (tapSyncOpen || singLine !== null) return;
      const transport = playbackRef.current;
      switch (event.code) {
        case "Space":
          event.preventDefault();
          transport.toggle();
          break;
        case "ArrowLeft":
          event.preventDefault();
          transport.seek(transport.time - 3);
          break;
        case "ArrowRight":
          event.preventDefault();
          transport.seek(transport.time + 3);
          break;
        case "KeyL":
          event.preventDefault();
          transport.toggleLoop();
          break;
        case "KeyF":
          event.preventDefault();
          togglePref("furigana");
          break;
        case "KeyR":
          event.preventDefault();
          togglePref("romaji");
          break;
        case "KeyT":
          event.preventDefault();
          togglePref("translation");
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [tapSyncOpen, singLine, togglePref]);

  const handleAutosync = async () => {
    playback.pause();
    const result = await autosyncJob.run(() => autosync(song.id));
    if (result === null) return;
    try {
      const updated = await getSong(song.id);
      onSongChange(updated);
      playback.seek(0);
      toast(mock ? "演示模式：已重新分布时间轴" : "自动对齐完成", "success");
    } catch (unknownError) {
      toast(toMessage(unknownError), "error");
    }
  };

  const openTapSync = () => {
    playback.pause();
    setSingLineId(null);
    setTapSyncOpen(true);
  };

  const beginTapSync = () => {
    playback.seek(0);
    playback.play();
  };

  const saveTapSync = async (lines: SyncLineInput[]): Promise<string | null> => {
    try {
      const updated = await putSync(song.id, lines);
      setTapSyncOpen(false);
      playback.pause();
      playback.seek(lines[0]?.start ?? 0);
      onSongChange(updated);
      toast(`已保存 ${lines.length} 行时间`, "success");
      return null;
    } catch (unknownError) {
      return toMessage(unknownError);
    }
  };

  const cancelTapSync = () => {
    setTapSyncOpen(false);
    playback.pause();
    playback.seek(0);
  };

  const openSing = () => {
    const line = song.lines[active.index];
    if (line === undefined) return;
    playback.pause();
    setSingLineId(line.id);
  };

  const seekFromClientX = (clientX: number, element: HTMLElement) => {
    const rect = element.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)));
    playback.seek(ratio * duration);
  };

  const handleSeekDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    seekFromClientX(event.clientX, event.currentTarget);
  };

  const handleSeekMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / Math.max(1, rect.width)));
    setHover({ seconds: ratio * duration, ratio });
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      playback.seek(ratio * duration);
    }
  };

  const handleSeekUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const untilStart = active.untilStart;
  const introChip =
    synced && !active.inside && untilStart > 0.4 ? `前奏 · 第一句在 ${formatTime(untilStart)}` : null;

  return (
    <div className="karaoke">
      <div className="karaoke-stage">
        {!synced && (
          <div className="sync-hint">
            <span className="hint-chip">未同步 · 先对齐时间</span>
            <button
              type="button"
              className="chip-action"
              onClick={() => void handleAutosync()}
              disabled={autosyncJob.running}
            >
              自动对齐
            </button>
            <button type="button" className="chip-action" onClick={openTapSync}>
              打点对齐
            </button>
          </div>
        )}
        {!synced && (autosyncJob.running || autosyncJob.error !== null) && (
          <div className="sync-job">
            <JobProgress
              job={autosyncJob.job}
              error={autosyncJob.error}
              running={autosyncJob.running}
            />
          </div>
        )}

        {playback.error !== null && (
          <div className="audio-error" role="alert">
            <IconWarning size={15} />
            {playback.error}
          </div>
        )}

        {synced && introChip !== null && (
          <div className="stage-chip" aria-live="off">
            {introChip}
          </div>
        )}

        <div className="lyrics-scroll" ref={scrollRef} aria-label="歌词">
          <div className="lyrics-pad" aria-hidden="true" />
          {song.lines.map((line, index) => {
            const state: LineState =
              index === active.index
                ? "current"
                : index === active.index - 1
                  ? "previous"
                  : index === active.index + 1
                    ? "next"
                    : "far";
            return (
              <KaraokeLine
                key={line.id}
                line={line}
                offset={song.offset}
                // Only the current line needs the playhead; this keeps the
                // other memoized lines out of the 60 fps render path.
                time={index === active.index ? playback.time : -1}
                state={state}
                furigana={prefs.furigana}
                romaji={prefs.romaji}
                translation={prefs.translation}
                onSeek={(seconds) => playback.seek(seconds)}
                onSing={openSing}
                measureRef={getLineRef(line.id)}
              />
            );
          })}
          <div className="lyrics-pad" aria-hidden="true" />
        </div>
      </div>

      {singLine !== null && (
        <SingBackPanel
          song={song}
          line={singLine}
          mock={mock}
          onClose={() => setSingLineId(null)}
        />
      )}

      <div className="controls">
        <div className="controls-inner">
          <div className="ctl-primary">
            <button
              type="button"
              className={cn("play-btn", playback.playing && "is-playing")}
              onClick={() => playback.toggle()}
              aria-label={playback.playing ? "暂停" : "播放"}
            >
              {playback.playing ? <IconPause size={20} /> : <IconPlay size={22} />}
            </button>

            <div className="time-read" aria-label="播放时间">
              <span className="time-now">{formatTime(playback.time)}</span>
              <span className="time-sep">/</span>
              <span className="time-total">{formatTime(duration)}</span>
            </div>

            <div
              className="seek"
              role="slider"
              tabIndex={0}
              aria-label="播放进度"
              aria-valuemin={0}
              aria-valuemax={Math.round(duration)}
              aria-valuenow={Math.round(playback.time)}
              aria-valuetext={`${formatTime(playback.time)} / ${formatTime(duration)}`}
              onPointerDown={handleSeekDown}
              onPointerMove={handleSeekMove}
              onPointerUp={handleSeekUp}
              onPointerCancel={handleSeekUp}
              onPointerLeave={() => setHover(null)}
            >
              <div className="seek-track">
                {region !== null && (
                  <span
                    className="seek-vocal"
                    style={{
                      left: `${(region.from / duration) * 100}%`,
                      width: `${(Math.max(0, region.to - region.from) / duration) * 100}%`,
                    }}
                  />
                )}
                <span className="seek-fill" style={{ width: `${progress * 100}%` }} />
                {playback.loop.a !== null && (
                  <span
                    className="seek-mark seek-mark--a"
                    style={{ left: `${(playback.loop.a / duration) * 100}%` }}
                  >
                    <i>A</i>
                  </span>
                )}
                {playback.loop.b !== null && (
                  <span
                    className="seek-mark seek-mark--b"
                    style={{ left: `${(playback.loop.b / duration) * 100}%` }}
                  >
                    <i>B</i>
                  </span>
                )}
              </div>
              <span className="seek-thumb" style={{ left: `${progress * 100}%` }} />
              {hover !== null && (
                <span className="seek-hover" style={{ left: `${hover.ratio * 100}%` }}>
                  {formatTime(hover.seconds)}
                </span>
              )}
            </div>

            <button
              type="button"
              className={cn("tap-sync-btn", !synced && "is-highlight")}
              onClick={openTapSync}
              title="打点对齐：空格记录每一行的开始 (Esc 取消)"
            >
              <IconKeyboard size={17} />
              <span>打点</span>
            </button>
          </div>

          <div className="ctl-secondary">
            <div className="ctl-group" role="group" aria-label="播放速度">
              <span className="ctl-label">速度</span>
              {TEMPOS.map((tempo) => (
                <button
                  key={tempo}
                  type="button"
                  className={cn("tempo-chip", prefs.tempo === tempo && "is-on")}
                  onClick={() => setTempo(tempo)}
                  aria-pressed={prefs.tempo === tempo}
                >
                  {tempoLabel(tempo)}
                </button>
              ))}
            </div>

            <div className="ctl-group loop-group" role="group" aria-label="A-B 循环">
              <span className="ctl-label">循环</span>
              <button
                type="button"
                className={cn("loop-set", playback.loop.a !== null && "is-set")}
                onClick={playback.setLoopA}
                title="把当前时间设为 A"
              >
                A
              </button>
              <button
                type="button"
                className={cn("loop-set", playback.loop.b !== null && "is-set")}
                onClick={playback.setLoopB}
                title="把当前时间设为 B"
              >
                B
              </button>
              <button
                type="button"
                className={cn("icon-btn loop-toggle", playback.loop.on && "is-on")}
                onClick={playback.toggleLoop}
                aria-pressed={playback.loop.on}
                aria-label="切换 A-B 循环"
                title="循环 (L)"
              >
                <IconLoop size={17} />
              </button>
              {(playback.loop.a !== null || playback.loop.b !== null) && (
                <button
                  type="button"
                  className="loop-clear"
                  onClick={playback.clearLoop}
                  aria-label="清除 A/B"
                  title="清除 A/B"
                >
                  <IconClose size={12} />
                </button>
              )}
              {playback.loop.a !== null && playback.loop.b !== null && (
                <span className="loop-times">
                  {formatTime(playback.loop.a)}–{formatTime(playback.loop.b)}
                </span>
              )}
            </div>

            <div className="ctl-group toggle-group" role="group" aria-label="显示选项">
              <button
                type="button"
                className={cn("display-toggle", prefs.furigana && "is-on")}
                onClick={() => togglePref("furigana")}
                aria-pressed={prefs.furigana}
                title="假名注音 (F)"
              >
                <span>假名</span>
                <kbd>F</kbd>
              </button>
              <button
                type="button"
                className={cn("display-toggle", prefs.romaji && "is-on")}
                onClick={() => togglePref("romaji")}
                aria-pressed={prefs.romaji}
                title="罗马音 (R)"
              >
                <span>罗马音</span>
                <kbd>R</kbd>
              </button>
              <button
                type="button"
                className={cn("display-toggle", prefs.translation && "is-on")}
                onClick={() => togglePref("translation")}
                aria-pressed={prefs.translation}
                title="中文译文 (T)"
              >
                <span>译文</span>
                <kbd>T</kbd>
              </button>
            </div>

            <div className="shortcut-hint">
              <kbd>空格</kbd> 播放
              <span className="meta-dot" aria-hidden="true" />
              <kbd>←</kbd>
              <kbd>→</kbd> 跳转
              <span className="meta-dot" aria-hidden="true" />
              <kbd>L</kbd> 循环
            </div>
          </div>
        </div>
      </div>

      {tapSyncOpen && (
        <TapSyncOverlay
          song={song}
          getTime={() => playbackRef.current.time}
          onStart={beginTapSync}
          onSave={saveTapSync}
          onCancel={cancelTapSync}
        />
      )}
    </div>
  );
}

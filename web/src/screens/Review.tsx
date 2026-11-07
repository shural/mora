import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { listCards, reviewCard } from "../api";
import type { Card, Song } from "../types";
import { useToast } from "../components/Toast";
import { useRuntimeMode } from "../hooks/useRuntimeMode";
import { IconRefresh, IconSound, IconWarning } from "../components/Icons";
import { formatDue } from "../lib/format";
import { toMessage } from "../lib/errors";
import { isEditableTarget } from "../lib/dom";
import { cn } from "../lib/cn";
import { canStartAudio, playMockSlice, type ToneHandle } from "../mock/tone";

const GRADES: Array<{ value: 0 | 1 | 2 | 3; key: string; label: string; hint: string }> = [
  { value: 0, key: "1", label: "重来", hint: "10 分钟后" },
  { value: 1, key: "2", label: "困难", hint: "明天" },
  { value: 2, key: "3", label: "良好", hint: "按间隔" },
  { value: 3, key: "4", label: "简单", hint: "更久之后" },
];

interface Props {
  song: Song;
  onGoStudy: () => void;
}

function isDue(card: Card): boolean {
  const due = new Date(card.due).getTime();
  return !Number.isNaN(due) && due <= Date.now();
}

/** 覚える — card stack, audio slice, blanked word, self grading. */
export function Review({ song, onGoStudy }: Props) {
  const [cards, setCards] = useState<Card[]>([]);
  const [queue, setQueue] = useState<Card[]>([]);
  const [sessionTotal, setSessionTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [grading, setGrading] = useState(false);
  const [nextDue, setNextDue] = useState<string | null>(null);
  const [audioNote, setAudioNote] = useState<"blocked" | "error" | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const toneRef = useRef<ToneHandle | null>(null);
  const { toast } = useToast();
  const mode = useRuntimeMode();
  const mock = mode === "mock";

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const all = await listCards();
      const mine = all
        .filter((card) => card.songId === song.id)
        .sort((a, b) => a.due.localeCompare(b.due));
      setCards(mine);
      const due = mine.filter(isDue);
      setQueue(due);
      setCursor(0);
      setSessionTotal(due.length);
      setRevealed(false);
      setNextDue(null);
    } catch (unknownError) {
      setError(toMessage(unknownError));
    } finally {
      setLoading(false);
    }
  }, [song.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const lastIndex = Math.max(0, queue.length - 1);
  const index = Math.min(cursor, lastIndex);
  const current = queue[index];
  /** what is printed in the lyric line — the sung form, not the dictionary form */
  const blankWord = current === undefined ? "" : current.asSung ?? current.surface;
  const reviewed = Math.max(0, sessionTotal - queue.length);
  const dueCount = useMemo(() => cards.filter(isDue).length, [cards]);
  const lineIndex = current === undefined
    ? -1
    : song.lines.findIndex((line) => line.id === current.lineId);

  // Auto-play the slice once when a new card appears.
  useEffect(() => {
    if (current === undefined) return;
    setAudioNote(null);
    if (mock) {
      // Don't create an AudioContext before the page has had a user gesture
      // (Chrome warns and refuses); the replay button still works afterwards.
      if (!canStartAudio()) return;
      const handle = playMockSlice(
        Math.max(0.4, current.end - current.start),
        current.surface.length,
      );
      toneRef.current = handle;
      return () => {
        handle?.stop();
        if (toneRef.current === handle) toneRef.current = null;
      };
    }
    const audio = audioRef.current;
    if (audio === null) return;
    audio.src = current.sliceUrl;
    audio.load();
    void audio.play().catch(() => setAudioNote("blocked"));
    return () => {
      audio.pause();
    };
  }, [current, mock]);

  const replay = useCallback(() => {
    if (current === undefined) return;
    if (mock) {
      toneRef.current?.stop();
      toneRef.current = playMockSlice(
        Math.max(0.4, current.end - current.start),
        current.surface.length,
      );
      return;
    }
    const audio = audioRef.current;
    if (audio === null) {
      setAudioNote("error");
      return;
    }
    audio.currentTime = 0;
    void audio.play().then(
      () => setAudioNote(null),
      () => setAudioNote("blocked"),
    );
  }, [current, mock]);

  const grade = useCallback(
    async (value: 0 | 1 | 2 | 3) => {
      if (current === undefined || grading) return;
      setGrading(true);
      try {
        const updated = await reviewCard(current.id, value);
        setCards((previous) =>
          previous.map((card) => (card.id === updated.id ? updated : card)),
        );
        setQueue((previous) => previous.filter((card) => card.id !== updated.id));
        setCursor((value) => Math.max(0, Math.min(value, Math.max(0, queue.length - 2))));
        setNextDue(formatDue(updated.due));
        setRevealed(false);
        toast(`下次复习：${formatDue(updated.due)}`, "success");
      } catch (unknownError) {
        toast(toMessage(unknownError), "error");
      } finally {
        setGrading(false);
      }
    },
    [current, grading, toast],
  );

  const goTo = useCallback((next: number) => {
    setCursor(Math.max(0, Math.min(queue.length - 1, next)));
    setRevealed(false);
  }, [queue.length]);

  /** Move the current card to the back of this round instead of grading it. */
  const skip = useCallback(() => {
    if (queue.length < 2) return;
    setQueue((previous) => {
      const card = previous[index];
      if (card === undefined) return previous;
      return [...previous.filter((_, i) => i !== index), card];
    });
    setCursor(Math.max(0, Math.min(index, queue.length - 2)));
    setRevealed(false);
  }, [index, queue.length]);

  // Keyboard: Space reveals, 1–4 grade, R replays, ←/→ browse.
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.code === "Space") {
        event.preventDefault();
        if (current !== undefined) setRevealed(true);
        return;
      }
      if (event.code === "ArrowLeft") {
        event.preventDefault();
        goTo(index - 1);
        return;
      }
      if (event.code === "ArrowRight") {
        event.preventDefault();
        goTo(index + 1);
        return;
      }
      if (event.code === "KeyR") {
        event.preventDefault();
        replay();
        return;
      }
      if (revealed) {
        const match = /^Digit([1-4])$/.exec(event.code);
        if (match !== null) {
          event.preventDefault();
          const value = (Number(match[1]) - 1) as 0 | 1 | 2 | 3;
          void grade(value);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [current, revealed, grade, replay, goTo, index]);

  const startEarlyReview = () => {
    setQueue([...cards].sort((a, b) => a.due.localeCompare(b.due)));
    setSessionTotal(cards.length);
    setRevealed(false);
    setNextDue(null);
  };

  const restart = () => {
    setQueue([...cards].sort((a, b) => a.due.localeCompare(b.due)));
    setSessionTotal(cards.length);
    setRevealed(false);
    setNextDue(null);
  };

  return (
    <main className="review">
      <audio ref={audioRef} hidden onError={() => setAudioNote("error")} />

      <div className="review-bar">
        <div className="review-counts">
          <span className="eyebrow">本曲复习</span>
          <span className="review-due">
            今日到期 <b>{dueCount}</b> 张
          </span>
          <span className="meta-dot" aria-hidden="true" />
          <span className="review-total">共 {cards.length} 张</span>
          {nextDue !== null && (
            <>
              <span className="meta-dot" aria-hidden="true" />
              <span className="review-next">下次：{nextDue}</span>
            </>
          )}
        </div>
        {sessionTotal > 0 && (
          <div className="review-progress" aria-label="本轮进度">
            <div className="review-progress-track">
              <div
                className="review-progress-fill"
                style={{ width: `${(reviewed / Math.max(1, sessionTotal)) * 100}%` }}
              />
            </div>
            <span className="review-progress-text">
              {reviewed} / {sessionTotal}
            </span>
          </div>
        )}
      </div>

      {!loading && error === null && queue.length > 0 && (
        <div className="review-nav">
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => goTo(index - 1)}
            disabled={index === 0}
            aria-label="上一张"
          >
            ← 上一张
          </button>
          <span className="review-nav-count">
            第 <b>{index + 1}</b> / {queue.length} 张
          </span>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => goTo(index + 1)}
            disabled={index >= queue.length - 1}
            aria-label="下一张"
          >
            下一张 →
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--sm review-nav-skip"
            onClick={skip}
            disabled={queue.length < 2}
            title="跳过这张，放回本轮末尾"
          >
            跳过
          </button>
        </div>
      )}

      {loading && (
        <div className="review-card review-card--skeleton" aria-hidden="true">
          <span className="sk sk--line" />
          <span className="sk sk--line sk--short" />
          <span className="sk sk--grade" />
        </div>
      )}

      {!loading && error !== null && (
        <div className="state-panel" role="alert">
          <p className="state-title">复习卡片加载失败</p>
          <p className="state-text">{error}</p>
          <button type="button" className="btn btn--ghost" onClick={() => void load()}>
            <IconRefresh size={16} />
            重试
          </button>
        </div>
      )}

      {!loading && error === null && cards.length === 0 && (
        <div className="review-empty">
          <div className="review-empty-mark" aria-hidden="true">
            <span className="brand-petal" />
            <span className="brand-ring" />
          </div>
          <p className="empty-title">先存几张卡</p>
          <p className="empty-lede">
            在「読む」里点开一个词，按「加入复习」，它就会带着原唱片段出现在这里。
          </p>
          <button type="button" className="btn btn--primary" onClick={onGoStudy}>
            去「読む」挑词
          </button>
        </div>
      )}

      {!loading && error === null && cards.length > 0 && queue.length === 0 && (
        <div className="review-empty">
          <p className="empty-title">
            {sessionTotal > 0 ? "这一轮复习完了" : "今天没有到期卡片"}
          </p>
          <p className="empty-lede">
            {sessionTotal > 0
              ? nextDue !== null
                ? `下次复习：${nextDue}。想多练一轮也可以。`
                : "本曲的卡片都过了一遍。"
              : `本曲还有 ${cards.length} 张卡没到期，可以提前复习，或者去「読む」再存几个词。`}
          </p>
          <div className="review-empty-actions">
            {sessionTotal > 0 ? (
              <button type="button" className="btn btn--primary" onClick={restart}>
                再复习一轮
              </button>
            ) : (
              <button type="button" className="btn btn--primary" onClick={startEarlyReview}>
                提前复习 {cards.length} 张
              </button>
            )}
            <button type="button" className="btn btn--ghost" onClick={onGoStudy}>
              去「読む」挑词
            </button>
          </div>
        </div>
      )}

      {!loading && error === null && current !== undefined && (
        <article className="review-card" key={current.id}>
          <div className="review-audio-row">
            <button
              type="button"
              className="audio-btn"
              onClick={replay}
              aria-label="重播原唱片段"
              title="重播 (R)"
            >
              <IconSound size={18} />
            </button>
            <div className="audio-meta">
              <span>
                原唱片段 · {(current.end - current.start).toFixed(1)} 秒
              </span>
              {mock && <span className="audio-tag">演示提示音</span>}
              {audioNote !== null && (
                <span className="audio-warn">
                  <IconWarning size={12} />
                  {audioNote === "error" ? "提示音不可用" : "点击播放提示音"}
                </span>
              )}
            </div>
            <span className="review-line-no">
              {lineIndex >= 0 ? `第 ${lineIndex + 1} 行` : "歌词"}
            </span>
          </div>

          <p className="review-context">
            {song.title}
            <span className="meta-dot" aria-hidden="true" />
            {song.artist}
          </p>

          <p className="review-line" lang="ja">
            {blankWord !== "" && current.lineText.includes(blankWord) ? (
              <>
                {current.lineText.slice(0, current.lineText.indexOf(blankWord))}
                <span className="blank">＿＿＿</span>
                {current.lineText.slice(current.lineText.indexOf(blankWord) + blankWord.length)}
              </>
            ) : (
              <>
                <span className="blank">＿＿＿</span>
                {current.lineText}
              </>
            )}
          </p>

          {!revealed ? (
            <button type="button" className="reveal-btn" onClick={() => setRevealed(true)}>
              显示答案
              <kbd>空格</kbd>
            </button>
          ) : (
            <div className="review-answer">
              <div className="answer-grid">
                <div className="answer-cell">
                  <span className="answer-label">词</span>
                  <span className="answer-surface" lang="ja">
                    {current.surface}
                  </span>
                </div>
                <div className="answer-cell">
                  <span className="answer-label">读音</span>
                  <span className="answer-kana" lang="ja">
                    {current.kana !== "" ? current.kana : "—"}
                  </span>
                </div>
                <div className="answer-cell">
                  <span className="answer-label">罗马音</span>
                  <span className="answer-romaji">{current.romaji !== "" ? current.romaji : "—"}</span>
                </div>
                {current.asSung != null && current.asSung !== "" && (
                  <div className="answer-cell">
                    <span className="answer-label">歌里唱</span>
                    <span className="answer-sung" lang="ja">
                      {current.asSung}
                    </span>
                  </div>
                )}
                <div className="answer-cell">
                  <span className="answer-label">释义</span>
                  <span className="answer-gloss">{current.glossZh ?? "暂无释义"}</span>
                </div>
              </div>

              <div className="grade-row">
                {GRADES.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    className={cn("grade-btn", `grade-btn--${item.value}`)}
                    onClick={() => void grade(item.value)}
                    disabled={grading}
                  >
                    <span className="grade-key">{item.key}</span>
                    <span className="grade-label">{item.label}</span>
                    <span className="grade-hint">{item.hint}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </article>
      )}

      <p className="review-foot">
        <kbd>空格</kbd> 显示答案 <span className="meta-dot" aria-hidden="true" />
        <kbd>1</kbd>–<kbd>4</kbd> 评分 <span className="meta-dot" aria-hidden="true" />
        <kbd>←</kbd> <kbd>→</kbd> 切换卡片 <span className="meta-dot" aria-hidden="true" />
        <kbd>R</kbd> 重播
        {mock && (
          <>
            <span className="meta-dot" aria-hidden="true" />
            演示模式：提示音为合成音
          </>
        )}
      </p>
    </main>
  );
}

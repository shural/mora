import { useEffect, useRef, useState } from "react";
import { sing } from "../api";
import type { Line, SingDiffItem, SingResult, Song } from "../types";
import { toMessage } from "../lib/errors";
import { cn } from "../lib/cn";
import { RubyText } from "./RubyText";
import { IconClose, IconMic, IconWarning } from "./Icons";

type Phase = "idle" | "recording" | "uploading" | "result" | "error";

interface Props {
  song: Song;
  line: Line;
  mock: boolean;
  onClose: () => void;
}

function DiffSpan({ item }: { item: SingDiffItem }) {
  if (item.op === "eq") return <span className="diff-eq">{item.a}</span>;
  if (item.op === "del") {
    return (
      <span className="diff-del" title="漏唱">
        {item.a}
      </span>
    );
  }
  if (item.op === "ins") {
    return (
      <span className="diff-ins" title="多唱">
        {item.b}
      </span>
    );
  }
  return (
    <span className="diff-sub">
      <span className="diff-del">{item.a}</span>
      <span className="diff-ins">{item.b}</span>
    </span>
  );
}

/**
 * Experimental sing-back: hold to record one line, let whisper compare the kana,
 * show a character diff. The disclaimer is always on screen.
 */
export function SingBackPanel({ song, line, mock, onClose }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<SingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [micReady, setMicReady] = useState(false);
  const [simulated, setSimulated] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);
  const startRef = useRef(0);
  const recordingRef = useRef(false);
  const pressedRef = useRef(false);
  const mounted = useRef(true);

  const stopTimer = () => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const releaseStream = () => {
    const stream = streamRef.current;
    if (stream !== null) {
      for (const track of stream.getTracks()) track.stop();
      streamRef.current = null;
    }
  };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      stopTimer();
      recordingRef.current = false;
      const recorder = recorderRef.current;
      if (recorder !== null && recorder.state !== "inactive") {
        try {
          recorder.stop();
        } catch {
          // already stopped
        }
      }
      releaseStream();
    };
  }, []);

  const upload = async (blob: Blob) => {
    if (!mounted.current) return;
    setPhase("uploading");
    try {
      const data = await sing(song.id, line.id, blob);
      if (!mounted.current) return;
      setResult(data);
      setPhase("result");
    } catch (unknownError) {
      if (!mounted.current) return;
      setError(toMessage(unknownError, "识别失败，请再试一次。"));
      setPhase("error");
    } finally {
      releaseStream();
    }
  };

  const stop = () => {
    pressedRef.current = false;
    if (!recordingRef.current) return;
    recordingRef.current = false;
    stopTimer();
    const duration = (performance.now() - startRef.current) / 1000;
    if (duration < 0.3) {
      setPhase("idle");
      setError("按住麦克风，唱完一句再松开。");
      if (mock) setSimulated(false);
      return;
    }
    if (mock) {
      void upload(new Blob(["mock-take"], { type: "audio/webm" }));
      return;
    }
    const recorder = recorderRef.current;
    if (recorder !== null && recorder.state === "recording") {
      recorder.stop();
    }
  };

  const start = async () => {
    if (phase === "recording" || phase === "uploading") return;
    setError(null);
    setResult(null);
    setPhase("recording");
    setMicReady(false);
    setElapsed(0);
    pressedRef.current = true;
    recordingRef.current = true;
    startRef.current = performance.now();
    stopTimer();
    timerRef.current = window.setInterval(() => {
      setElapsed((performance.now() - startRef.current) / 1000);
    }, 120);

    if (mock) {
      setSimulated(true);
      setMicReady(true);
      return;
    }

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        throw new Error("media devices unavailable");
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mounted.current) {
        for (const track of stream.getTracks()) track.stop();
        return;
      }
      streamRef.current = stream;
      const preferred = "audio/webm;codecs=opus";
      const options: MediaRecorderOptions = MediaRecorder.isTypeSupported(preferred)
        ? { mimeType: preferred }
        : {};
      const recorder = new MediaRecorder(stream, options);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType !== "" ? recorder.mimeType : "audio/webm",
        });
        void upload(blob);
      };
      recorderRef.current = recorder;
      recorder.start();
      setMicReady(true);
      if (!pressedRef.current) recorder.stop();
    } catch (unknownError) {
      recordingRef.current = false;
      stopTimer();
      setPhase("error");
      setError(toMessage(unknownError, "无法打开麦克风，请检查浏览器权限。"));
      releaseStream();
    }
  };

  const reset = () => {
    setPhase("idle");
    setResult(null);
    setError(null);
    setElapsed(0);
    setSimulated(false);
  };

  const scoreTone =
    result === null ? "mid" : result.score >= 85 ? "good" : result.score >= 60 ? "mid" : "low";

  return (
    <section className="sing-panel" aria-label="跟唱这一句">
      <header className="sing-head">
        <span className="sing-title">
          <IconMic size={16} />
          跟唱这一句
        </span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="关闭跟唱面板">
          <IconClose size={17} />
        </button>
      </header>

      <p className="sing-line" lang="ja">
        <RubyText
          segments={line.tokens.flatMap((token) => token.ruby)}
          showFurigana
        />
      </p>

      {phase === "result" && result !== null ? (
        <>
          <div className="sing-score-row">
            <div className={cn("sing-score", `is-${scoreTone}`)}>
              <span className="sing-score-num">{result.score}</span>
              <span className="sing-score-max">/100</span>
            </div>
            <div className="sing-score-meta">
              <p>
                音拍正确 <b>{result.moraeOk}</b> / {result.moraeTotal}
              </p>
              <p className="sing-hint">{result.hint}</p>
            </div>
          </div>

          <div className="sing-compare">
            <div className="sing-row">
              <span className="sing-label">目标</span>
              <span className="sing-kana" lang="ja">
                {result.targetKana !== "" ? result.targetKana : "—"}
              </span>
            </div>
            <div className="sing-row">
              <span className="sing-label">你唱</span>
              <span className="sing-kana sing-diff" lang="ja">
                {result.diff.map((item, index) => (
                  <DiffSpan item={item} key={`${item.op}-${index}-${item.a ?? item.b ?? ""}`} />
                ))}
              </span>
            </div>
          </div>
          <div className="sing-legend">
            <span className="diff-eq">唱对</span>
            <span className="diff-del">漏掉</span>
            <span className="diff-ins">多唱</span>
            {simulated && <span className="sing-simulated">演示模式：模拟识别结果</span>}
          </div>
          <div className="sing-actions">
            <button type="button" className="btn btn--primary" onClick={reset}>
              再试一次
            </button>
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              关闭
            </button>
          </div>
        </>
      ) : phase === "uploading" ? (
        <div className="sing-status">
          <span className="sing-spinner" aria-hidden="true" />
          <p>正在识别你唱的假名…</p>
        </div>
      ) : phase === "error" ? (
        <div className="sing-status sing-status--error" role="alert">
          <IconWarning size={18} />
          <p>{error ?? "识别失败，请再试一次。"}</p>
          <button type="button" className="btn btn--ghost" onClick={reset}>
            重试
          </button>
        </div>
      ) : (
        <div className="sing-record-wrap">
          <button
            type="button"
            className={cn("sing-record-btn", phase === "recording" && "is-recording")}
            aria-label={phase === "recording" ? "松开结束录音" : "按住录音"}
            onPointerDown={(event) => {
              event.preventDefault();
              if (event.button !== 0) return;
              event.currentTarget.setPointerCapture(event.pointerId);
              void start();
            }}
            onPointerUp={stop}
            onPointerCancel={stop}
            onContextMenu={(event) => event.preventDefault()}
            onKeyDown={(event) => {
              if (event.repeat) return;
              if (event.key === " " || event.key === "Enter") {
                event.preventDefault();
                void start();
              }
            }}
            onKeyUp={(event) => {
              if (event.key === " " || event.key === "Enter") {
                event.preventDefault();
                stop();
              }
            }}
          >
            <span className="sing-record-ring" aria-hidden="true" />
            {phase === "recording" ? (
              <>
                <span className="sing-record-time">{elapsed.toFixed(1)}s</span>
                <span className="sing-record-label">
                  {micReady ? "松开结束" : "正在准备麦克风…"}
                </span>
              </>
            ) : (
              <>
                <IconMic size={26} />
                <span className="sing-record-label">按住唱这一句</span>
              </>
            )}
          </button>
          <p className="sing-tip">
            {mock
              ? "演示模式：不会真的打开麦克风，松开后返回模拟识别结果。"
              : "按住按钮开始录音，唱完这一句再松开。"}
          </p>
          {error !== null && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
      )}

      <p className="sing-disclaimer">实验性：靠语音识别判断，仅供参考</p>
    </section>
  );
}

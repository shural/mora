import { useCallback, useEffect, useRef, useState } from "react";

export interface LoopRange {
  a: number | null;
  b: number | null;
  on: boolean;
}

export interface PlaybackApi {
  time: number;
  duration: number;
  playing: boolean;
  error: string | null;
  rate: number;
  loop: LoopRange;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (seconds: number) => void;
  setRate: (rate: number) => void;
  setLoopA: () => void;
  setLoopB: () => void;
  toggleLoop: () => void;
  clearLoop: () => void;
}

type PitchPreservingAudio = HTMLAudioElement & {
  webkitPreservesPitch?: boolean;
};

interface Options {
  src: string;
  duration: number;
  mock: boolean;
}

const EMPTY_LOOP: LoopRange = { a: null, b: null, on: false };

/**
 * One playback surface for both modes.
 *
 * live: requestAnimationFrame reads <audio>.currentTime (the real backend audio,
 *       Range requests included). preservesPitch keeps the tempo honest.
 * mock: a synthetic clock advanced by rAF with the same API, so the whole
 *       karaoke flow (ruler, auto-scroll, A–B loop, tempo) is demoable with no
 *       backend and no audio files.
 */
export function usePlayback({ src, duration, mock }: Options): PlaybackApi {
  const [time, setTime] = useState(0);
  const [durationState, setDurationState] = useState(duration > 0 ? duration : 1);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rate, setRateState] = useState(1);
  const [loop, setLoop] = useState<LoopRange>(EMPTY_LOOP);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timeRef = useRef(0);
  const durationRef = useRef(duration > 0 ? duration : 1);
  const rateRef = useRef(1);
  const loopRef = useRef<LoopRange>(EMPTY_LOOP);
  const mockRef = useRef(mock);
  mockRef.current = mock;

  const clampTime = useCallback((seconds: number): number => {
    const limit = durationRef.current;
    if (!Number.isFinite(seconds)) return 0;
    return Math.min(limit, Math.max(0, seconds));
  }, []);

  const commitLoop = useCallback((next: LoopRange) => {
    loopRef.current = next;
    setLoop(next);
  }, []);

  // Reset transport when the song changes.
  useEffect(() => {
    timeRef.current = 0;
    setTime(0);
    setPlaying(false);
    setError(null);
    setRateState(1);
    rateRef.current = 1;
    commitLoop(EMPTY_LOOP);
    durationRef.current = duration > 0 ? duration : 1;
    setDurationState(duration > 0 ? duration : 1);
  }, [src, duration, commitLoop]);

  // Real audio element (live mode only).
  useEffect(() => {
    if (mock) return;
    const audio = new Audio(src) as PitchPreservingAudio;
    audio.preload = "auto";
    audio.preservesPitch = true;
    audio.webkitPreservesPitch = true;
    audio.playbackRate = rateRef.current;
    audioRef.current = audio;

    const handleMetadata = () => {
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        durationRef.current = audio.duration;
        setDurationState(audio.duration);
      }
    };
    const handlePlay = () => setPlaying(true);
    const handlePause = () => setPlaying(false);
    const handleEnded = () => {
      setPlaying(false);
      setTime(durationRef.current);
      timeRef.current = durationRef.current;
    };
    const handleError = () => {
      // A missing/404 audioUrl must never throw into the console.
      setPlaying(false);
      setError("音频加载失败，请确认后端已启动或换一首歌。");
    };

    audio.addEventListener("loadedmetadata", handleMetadata);
    audio.addEventListener("play", handlePlay);
    audio.addEventListener("pause", handlePause);
    audio.addEventListener("ended", handleEnded);
    audio.addEventListener("error", handleError);

    return () => {
      audio.pause();
      audio.removeEventListener("loadedmetadata", handleMetadata);
      audio.removeEventListener("play", handlePlay);
      audio.removeEventListener("pause", handlePause);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("error", handleError);
      audioRef.current = null;
    };
  }, [src, mock]);

  // Tempo without pitch change.
  useEffect(() => {
    rateRef.current = rate;
    if (mock) return;
    const audio = audioRef.current as PitchPreservingAudio | null;
    if (audio === null) return;
    audio.preservesPitch = true;
    audio.webkitPreservesPitch = true;
    audio.playbackRate = rate;
  }, [rate, mock]);

  // The single rAF loop: read current time, drive highlighting, enforce A–B.
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let last = performance.now();

    const tick = (now: number) => {
      const delta = Math.min(0.25, Math.max(0, (now - last) / 1000));
      last = now;

      if (mockRef.current) {
        timeRef.current = Math.min(
          durationRef.current,
          timeRef.current + delta * rateRef.current,
        );
      } else {
        const audio = audioRef.current;
        if (audio !== null) {
          timeRef.current = audio.currentTime;
          if (audio.playbackRate !== rateRef.current) {
            audio.playbackRate = rateRef.current;
          }
        }
      }

      const range = loopRef.current;
      if (range.on && range.b !== null && timeRef.current >= range.b) {
        const target = range.a ?? 0;
        timeRef.current = target;
        if (!mockRef.current) {
          const audio = audioRef.current;
          if (audio !== null) audio.currentTime = target;
        }
      }

      if (mockRef.current && timeRef.current >= durationRef.current) {
        timeRef.current = durationRef.current;
        setTime(durationRef.current);
        setPlaying(false);
        return;
      }

      setTime(timeRef.current);
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  const play = useCallback(() => {
    setError(null);
    if (mockRef.current) {
      if (timeRef.current >= durationRef.current) {
        timeRef.current = 0;
        setTime(0);
      }
      setPlaying(true);
      return;
    }
    const audio = audioRef.current;
    if (audio === null) return;
    void audio.play().catch(() => {
      setPlaying(false);
      setError("浏览器阻止了播放，请再点一次播放键。");
    });
  }, []);

  const pause = useCallback(() => {
    if (mockRef.current) {
      setPlaying(false);
      return;
    }
    audioRef.current?.pause();
  }, []);

  const toggle = useCallback(() => {
    if (playing) pause();
    else play();
  }, [playing, pause, play]);

  const seek = useCallback(
    (seconds: number) => {
      const target = clampTime(seconds);
      timeRef.current = target;
      setTime(target);
      if (!mockRef.current) {
        const audio = audioRef.current;
        if (audio !== null) {
          try {
            audio.currentTime = target;
          } catch {
            // seeking before metadata is ready — ignore
          }
        }
      }
    },
    [clampTime],
  );

  const setRate = useCallback((next: number) => {
    setRateState(next);
  }, []);

  const setLoopA = useCallback(() => {
    const a = Number(clampTime(timeRef.current).toFixed(2));
    const current = loopRef.current;
    const keepB = current.b !== null && current.b > a ? current.b : null;
    commitLoop({ a, b: keepB, on: keepB !== null });
  }, [clampTime, commitLoop]);

  const setLoopB = useCallback(() => {
    const b = Number(clampTime(timeRef.current).toFixed(2));
    const current = loopRef.current;
    const a = current.a ?? 0;
    // B must land after A. Clicking both at the same playhead is not a loop;
    // ignore it instead of silently moving A to the start.
    if (b <= a + 0.25) return;
    commitLoop({ a, b, on: true });
  }, [clampTime, commitLoop]);

  const toggleLoop = useCallback(() => {
    const current = loopRef.current;
    if (current.on) {
      commitLoop({ ...current, on: false });
      return;
    }
    const a = current.a ?? 0;
    const limit = durationRef.current;
    const b = current.b !== null && current.b > a + 0.1 ? current.b : limit;
    if (b <= a + 0.1) return;
    commitLoop({ a, b, on: true });
    if (timeRef.current < a || timeRef.current > b) {
      timeRef.current = a;
      setTime(a);
      if (!mockRef.current) {
        const audio = audioRef.current;
        if (audio !== null) audio.currentTime = a;
      }
    }
  }, [commitLoop]);

  const clearLoop = useCallback(() => {
    commitLoop(EMPTY_LOOP);
  }, [commitLoop]);

  return {
    time,
    duration: durationState,
    playing,
    error,
    rate,
    loop,
    play,
    pause,
    toggle,
    seek,
    setRate,
    setLoopA,
    setLoopB,
    toggleLoop,
    clearLoop,
  };
}

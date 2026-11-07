/**
 * Mock audio for review cards.
 *
 * `sliceUrl` points at the FastAPI backend and is a 404 in mock mode, so card
 * review gets a quiet synthesized cue instead of a broken <audio> element.
 * This is only ever used when the runtime mode is mock.
 */

let context: AudioContext | null = null;

function getContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (context !== null) return context;
  const AudioCtor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (AudioCtor === undefined) return null;
  context = new AudioCtor();
  return context;
}

export interface ToneHandle {
  stop: () => void;
}

/** Chrome blocks AudioContext until the page has had a user gesture. */
export function canStartAudio(): boolean {
  const activation = (
    navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }
  ).userActivation;
  return activation === undefined ? true : activation.hasBeenActive;
}

/** Soft two-note chime whose length follows the card slice. */
export function playMockSlice(duration: number, seed = 0): ToneHandle | null {
  const ctx = getContext();
  if (ctx === null) return null;
  void ctx.resume().catch(() => undefined);

  const now = ctx.currentTime;
  const length = Math.max(0.35, Math.min(3, Number.isFinite(duration) ? duration : 1));
  const base = 330 + (Math.abs(seed) % 4) * 28;
  const osc = ctx.createOscillator();
  osc.type = "sine";
  osc.frequency.setValueAtTime(base, now);
  osc.frequency.exponentialRampToValueAtTime(base * 1.5, now + length * 0.55);

  const gain = ctx.createGain();
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.085, now + 0.05);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + length);

  osc.connect(gain);
  gain.connect(ctx.destination);
  osc.start(now);
  osc.stop(now + length + 0.03);

  return {
    stop: () => {
      try {
        osc.stop();
      } catch {
        // already stopped
      }
    },
  };
}

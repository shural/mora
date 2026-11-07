import type { Job } from "../types";
import { IconWarning } from "./Icons";

interface JobProgressProps {
  job: Job | null;
  error: string | null;
  running: boolean;
  label?: string;
}

/** Inline job progress — polls arrive every 700 ms, so this is real movement. */
export function JobProgress({ job, error, running, label }: JobProgressProps) {
  if (error !== null) {
    return (
      <div className="job job--error" role="alert">
        <IconWarning size={16} />
        <span>{error}</span>
      </div>
    );
  }
  if (!running) return null;

  const progress = Math.max(2, Math.min(100, job?.progress ?? 2));
  const message = job?.message ?? "正在排队…";
  return (
    <div className="job" role="status" aria-live="polite">
      <div className="job-head">
        <span className="job-dot" aria-hidden="true" />
        <span className="job-message">{label !== undefined ? `${label} · ${message}` : message}</span>
        <span className="job-pct">{Math.round(progress)}%</span>
      </div>
      <div className="job-track" aria-hidden="true">
        <div className="job-fill" style={{ width: `${progress}%` }} />
      </div>
    </div>
  );
}

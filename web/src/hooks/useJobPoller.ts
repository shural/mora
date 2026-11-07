import { useCallback, useEffect, useRef, useState } from "react";
import { getJob } from "../api";
import { toMessage } from "../lib/errors";
import type { Job } from "../types";

const POLL_MS = 700;

export interface JobPoller {
  job: Job | null;
  running: boolean;
  error: string | null;
  /** Start a backend job and poll GET /api/jobs/{id} every 700 ms. */
  run: (begin: () => Promise<{ jobId: string }>) => Promise<Job | null>;
  reset: () => void;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

/**
 * Long operations are always jobs. Poll every 700 ms and report real progress;
 * never block the UI and never throw into render.
 */
export function useJobPoller(): JobPoller {
  const [job, setJob] = useState<Job | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
    };
  }, []);

  const reset = useCallback(() => {
    generation.current += 1;
    setJob(null);
    setError(null);
    setRunning(false);
  }, []);

  const run = useCallback(
    async (begin: () => Promise<{ jobId: string }>): Promise<Job | null> => {
      const currentGeneration = generation.current + 1;
      generation.current = currentGeneration;
      setError(null);
      setJob(null);
      setRunning(true);

      try {
        const { jobId } = await begin();
        for (;;) {
          if (generation.current !== currentGeneration) return null;
          const snapshot = await getJob(jobId);
          if (generation.current !== currentGeneration) return null;
          if (!mounted.current) return null;
          setJob(snapshot);
          if (snapshot.status === "done") {
            setRunning(false);
            return snapshot;
          }
          if (snapshot.status === "error") {
            setRunning(false);
            setError(snapshot.message !== "" ? snapshot.message : "任务失败，请稍后再试。");
            return null;
          }
          await sleep(POLL_MS);
        }
      } catch (unknownError) {
        if (mounted.current && generation.current === currentGeneration) {
          setError(toMessage(unknownError));
          setRunning(false);
        }
        return null;
      }
    },
    [],
  );

  return { job, running, error, run, reset };
}

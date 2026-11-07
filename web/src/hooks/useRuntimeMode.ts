import { useEffect, useState } from "react";
import { getRuntimeMode, subscribeRuntimeMode, type RuntimeMode } from "../api";

/** Reactive view of the live/mock runtime switch. */
export function useRuntimeMode(): RuntimeMode {
  const [mode, setMode] = useState<RuntimeMode>(getRuntimeMode);
  useEffect(() => subscribeRuntimeMode(setMode), []);
  return mode;
}

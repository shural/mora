import { useState } from "react";
import { isMockFallback, reconnectBackend } from "../api";
import { useRuntimeMode } from "../hooks/useRuntimeMode";
import { IconWarning } from "./Icons";

/**
 * Visible failure state: the production build could not reach the backend and
 * fell back to demo data. Warns that nothing is being written to disk, retries
 * automatically every few seconds, and lets you force a retry.
 */
export function ModeBanner() {
  const mode = useRuntimeMode();
  const [retrying, setRetrying] = useState(false);
  const [failed, setFailed] = useState(false);

  if (mode !== "mock" || !isMockFallback()) return null;

  const retry = async () => {
    setRetrying(true);
    setFailed(false);
    const alive = await reconnectBackend();
    setRetrying(false);
    setFailed(!alive);
  };

  return (
    <div className="mode-banner" role="alert">
      <IconWarning size={15} />
      <span>
        本地后端没有响应，已切换到<b>演示数据</b>。页面仍可完整点击，但不会写入磁盘。
        {failed ? " 仍然连不上，正在自动重试…" : ""}
      </span>
      <button type="button" className="mode-banner-btn" onClick={retry} disabled={retrying}>
        {retrying ? "连接中…" : "重新连接"}
      </button>
    </div>
  );
}

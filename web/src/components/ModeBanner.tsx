import { isMockFallback } from "../api";
import { useRuntimeMode } from "../hooks/useRuntimeMode";
import { IconWarning } from "./Icons";

/**
 * Visible failure state: the production build could not reach the backend and
 * fell back to demo data. Mock-by-default builds (VITE_MOCK) don't show this.
 */
export function ModeBanner() {
  const mode = useRuntimeMode();
  if (mode !== "mock" || !isMockFallback()) return null;
  return (
    <div className="mode-banner" role="alert">
      <IconWarning size={15} />
      <span>
        本地后端没有响应，已切换到<b>演示数据</b>。页面仍可完整点击，但不会写入磁盘。
      </span>
      <button type="button" className="mode-banner-btn" onClick={() => window.location.reload()}>
        重试连接
      </button>
    </div>
  );
}

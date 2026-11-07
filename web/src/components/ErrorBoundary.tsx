import { Component, type ErrorInfo, type ReactNode } from "react";
import { Brand } from "./Brand";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

/** Last line of defence: no raw exception ever reaches the screen. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // Deliberately quiet: we show a human fallback instead of a stack trace.
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="crash">
          <Brand />
          <p className="crash-title">页面出了点问题。</p>
          <p className="crash-text">刷新一下就好，你的歌曲和卡片都还在这台机器上。</p>
          <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

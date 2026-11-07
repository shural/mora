import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { USE_MOCK, detectBackend } from "./api";
import { Boot } from "./components/Boot";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ToastProvider } from "./components/Toast";
import { Library } from "./screens/Library";
import { SongView } from "./screens/SongView";

/**
 * Boot gate: mock builds render immediately; production builds ping
 * /api/health once and fall back to demo data if the backend is down.
 */
export function App() {
  const [ready, setReady] = useState(USE_MOCK);

  useEffect(() => {
    if (USE_MOCK) return;
    let cancelled = false;
    void detectBackend().finally(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return <Boot text="正在连接本地后端…" />;
  }

  return (
    <ErrorBoundary>
      <ToastProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route path="/" element={<Library />} />
            <Route path="/song/:id" element={<SongView />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </ErrorBoundary>
  );
}

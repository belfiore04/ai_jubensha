import { useEffect, useState, useRef } from "react";
import "./DebugPanel.css";

interface DebugEntry {
  ts: number;
  msg: string;
}

interface DebugPanelProps {
  gameId: string | null;
  apiBase?: string;
}

export default function DebugPanel({
  gameId,
  apiBase = "http://localhost:8000",
}: DebugPanelProps) {
  const [logs, setLogs] = useState<DebugEntry[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!gameId) return;

    const es = new EventSource(`${apiBase}/api/game/${gameId}/debug`);

    es.addEventListener("debug", (ev) => {
      try {
        const entry: DebugEntry = JSON.parse(ev.data);
        setLogs((prev) => [...prev, entry]);
      } catch {
        // ignore
      }
    });

    return () => es.close();
  }, [gameId, apiBase]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  if (!gameId) return null;

  return (
    <div className={`debug-panel ${collapsed ? "debug-panel--collapsed" : ""}`}>
      <button
        className="debug-toggle"
        onClick={() => setCollapsed((c) => !c)}
      >
        🐛 Debug {collapsed ? "▲" : "▼"} ({logs.length})
      </button>
      {!collapsed && (
        <div className="debug-logs">
          {logs.length === 0 && (
            <div className="debug-entry">等待后端事件...</div>
          )}
          {logs.map((entry, i) => {
            const time = new Date(entry.ts * 1000).toLocaleTimeString();
            return (
              <div key={i} className="debug-entry">
                <span className="debug-time">{time}</span>
                <span className="debug-msg">{entry.msg}</span>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}

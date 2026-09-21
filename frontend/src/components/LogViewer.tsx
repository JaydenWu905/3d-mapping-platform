import { useEffect, useRef, useState } from 'react';
import { api } from '../api/api';

export interface LogViewerProps {
  jobId: string;
  stage: string;
  active: boolean; // 阶段运行中 → 轮询日志
}

/**
 * 日志通过 REST offset 轮询拉取（与 SSE 解耦，避免长连接日志量过大）。
 * 阶段处于 running / cancelling 时每 1.5s 轮询一次；其它状态只拉一次。
 */
export function LogViewer({ jobId, stage, active }: LogViewerProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const load = async () => {
      try {
        const r = await api.getLogs(jobId, stage, 0, 2000);
        if (cancelled) return;
        setLines(r.lines);
        setTotal(r.total);
        setError(null);
      } catch {
        if (!cancelled) setError('日志暂不可用（阶段尚未产生输出）');
      }
    };

    void load();
    if (active) {
      timer = window.setInterval(() => void load(), 1500);
    }
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [jobId, stage, active]);

  // 自动滚动到底部；用户向上滚动查看历史时不强行下拉。
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (active || nearBottom) el.scrollTop = el.scrollHeight;
  }, [lines, active]);

  return (
    <div className="log-panel">
      <div className="log-head">
        <span>运行日志</span>
        <span className="log-count">
          {total} 行 {active ? '· 实时' : ''}
        </span>
      </div>
      <div className="log-body" ref={boxRef}>
        {error ? <div className="log-empty">{error}</div> : null}
        {lines.length === 0 && !error ? <div className="log-empty">（暂无日志输出）</div> : null}
        {lines.map((line, i) => (
          <div key={i} className="log-line">
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}
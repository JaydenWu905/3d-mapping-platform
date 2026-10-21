import { useEffect, useRef, useState } from 'react';
import { Box, Typography } from '@mui/material';
import type { StageDetail } from '../types';
import type { StageKey } from '../types';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { PreviewTips } from './PreviewTips';
import { StageProgressBar } from './StageProgressBar';
import { measuredProgress } from './runInsight';
import { formatElapsed } from './progressLabel';
import { stageNotice, waitingMessages, waitingTitle } from './waitingPreview/presentation';

export type WaitingPreviewProps = { stage: StageDetail; connected: boolean; runKey?: string;
  resultStage?: StageKey | null; onOpenResult?: (key: StageKey) => void;
  elapsed?: number; etaText?: string };

/** Decorative SVG loops have no access to counters, percentages or elapsed time. */
function ProcessingGlyph({ stage }: { stage: string }) {
  return <svg className="processing-glyph" viewBox="0 0 280 150" aria-hidden="true">
    {stage === 'pose' ? <g fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M55 95 L98 53 L143 88 L186 52 L225 75" opacity=".16" />
      <path className="processing-trace" d="M55 95 L98 53 L143 88 L186 52 L225 75" />
      {[[55,95],[98,53],[143,88],[186,52],[225,75]].map(([x,y],i)=><circle className="processing-dot" style={{animationDelay:`${i * .5}s`}} key={i} cx={x} cy={y} r="5" fill="currentColor" stroke="none" />)}
    </g> : stage === 'surface' ? <g stroke="currentColor" strokeWidth="1.5">
      {[[102,50],[140,50],[178,50],[83,83],[121,83],[159,83],[197,83]].map(([x,y],i)=><g className="processing-voxel" style={{animationDelay:`${i * .4}s`}} key={i} transform={`translate(${x} ${y})`}>
        <path d="M0 -15 L17 -5 L0 5 L-17 -5 Z" fill="currentColor" fillOpacity=".2" />
        <path d="M-17 -5 L0 5 L0 25 L-17 15 Z M0 5 L17 -5 L17 15 L0 25 Z" fill="currentColor" fillOpacity=".08" />
      </g>)}
    </g> : <g fill="none" stroke="currentColor" strokeWidth="1.5">
      {[1,2,3].map(i=><ellipse key={i} className="processing-contour" style={{animationDelay:`${i * .7}s`}} cx="140" cy="76" rx={30+i*23} ry={14+i*12} />)}
      <path d="M108 81 L124 60 L153 57 L173 79 L151 94 L124 96 Z" fill="currentColor" fillOpacity=".12" strokeWidth="2" />
    </g>}
  </svg>;
}

export function WaitingPreview({ stage, connected, runKey, resultStage, onOpenResult, elapsed, etaText }: WaitingPreviewProps) {
  const reduced = useReducedMotion();
  const everConnected = useRef(false);
  if (connected) everConnected.current = true;
  const [hidden, setHidden] = useState(() => document.hidden);
  const [copyIndex, setCopyIndex] = useState(0);
  const running = stage.status === 'running';
  const animate = running && connected && !reduced && !hidden;
  const messages = waitingMessages(stage);
  const phaseKey = `${runKey}:${stage.stage}:${stage.status}:${stage.phase}`;
  useEffect(() => { setCopyIndex(0); }, [phaseKey]);
  useEffect(() => {
    const onVisibility = () => setHidden(document.hidden);
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);
  useEffect(() => {
    if (!animate || messages.length < 2) return undefined;
    const timer = window.setInterval(() => setCopyIndex(i => i + 1), 18000);
    return () => window.clearInterval(timer);
  }, [animate, messages.length, phaseKey]);
  const notice = stageNotice(stage);
  return <Box className="processing-preview" data-waiting-stage={stage.stage} data-waiting-mode={stage.status}
    data-waiting-animating={animate ? 'true' : 'false'} data-reduced-motion={reduced ? 'true' : 'false'}>
    <span className="processing-preview__tag">处理示意</span>
    <Box className={`processing-preview__art processing-preview__art--${stage.stage}`}>
      {running ? <ProcessingGlyph stage={stage.stage} /> : <span className="processing-preview__symbol" aria-hidden="true">{stage.status === 'failed' ? '!' : stage.status === 'cancelled' ? '—' : stage.status === 'queued' ? '···' : '◇'}</span>}
    </Box>
    <Typography className="processing-preview__title">{waitingTitle(stage)}</Typography>
    <Typography className="processing-preview__copy">{messages[copyIndex % messages.length]}</Typography>
    {running ? <div className="processing-preview__actual">
      <strong>真实进度</strong>
      <StageProgressBar stage={stage} large />
      <span>{measuredProgress(stage).label}</span>
      <span>已运行 {formatElapsed(elapsed ?? stage.elapsed_sec)} · 预计剩余：{etaText ?? '剩余时间暂无法估算'}</span>
    </div> : null}
    {notice && stage.status !== 'failed' ? <Typography color="warning.main">{notice.text}</Typography> : null}
    {!connected && running ? <Typography color="text.secondary">{everConnected.current ? '连接中断，正在重连；保留最后收到的状态。' : '正在连接状态服务。'}</Typography> : null}
    <PreviewTips stage={stage} resultStage={resultStage} onOpenResult={onOpenResult} />
  </Box>;
}

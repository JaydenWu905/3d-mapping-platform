import { useEffect, useRef, useState } from 'react';
import { Box, Typography } from '@mui/material';
import type { StageDetail } from '../types';
import type { StageKey } from '../types';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { PreviewTips } from './PreviewTips';
import { ProcessingIllustration } from './waitingPreview/ProcessingIllustration';
import { StageProgressBar } from './StageProgressBar';
import { measuredProgress } from './runInsight';
import { formatElapsed } from './progressLabel';
import { stageNotice, waitingMessages, waitingTitle } from './waitingPreview/presentation';

export type WaitingPreviewProps = { stage: StageDetail; connected: boolean; runKey?: string;
  resultStage?: StageKey | null; onOpenResult?: (key: StageKey) => void;
  elapsed?: number };

export function WaitingPreview({ stage, connected, runKey, resultStage, onOpenResult, elapsed }: WaitingPreviewProps) {
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
      {running ? <ProcessingIllustration stage={stage.stage} animate={animate} /> : <span className="processing-preview__symbol" aria-hidden="true">{stage.status === 'failed' ? '!' : stage.status === 'cancelled' ? '—' : stage.status === 'queued' ? '···' : '◇'}</span>}
    </Box>
    <Typography className="processing-preview__title">{waitingTitle(stage)}</Typography>
    <Typography className="processing-preview__copy">{messages[copyIndex % messages.length]}</Typography>
    {running ? <div className="processing-preview__actual">
      <strong>真实进度</strong>
      <StageProgressBar stage={stage} large />
      <span>{measuredProgress(stage).label}</span>
      <span>已运行 {formatElapsed(elapsed ?? stage.elapsed_sec)}</span>
    </div> : null}
    {notice && stage.status !== 'failed' ? <Typography color="warning.main">{notice.text}</Typography> : null}
    {!connected && running ? <Typography color="text.secondary">{everConnected.current ? '连接中断，正在重连；保留最后收到的状态。' : '正在连接状态服务。'}</Typography> : null}
    <PreviewTips stage={stage} resultStage={resultStage} onOpenResult={onOpenResult} />
  </Box>;
}

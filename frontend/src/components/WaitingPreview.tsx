import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Typography,
} from '@mui/material';
import type { StageDetail } from '../types';
import { stagePhaseLabel } from './progressLabel';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { drawWaitingScene, stageColor } from './waitingPreview/draw';
import { advanceRobotProgress, buildScannerMap } from './waitingPreview/route';
import { variantForRun } from './waitingPreview/variation';
import {
  deriveWaitingPreviewState,
  type WaitingPreviewMode,
} from './waitingPreview/state';

export type WaitingPreviewProps = {
  stage: StageDetail;
  connected: boolean;
  runKey?: string;
};
const FRAME_INTERVAL_MS = 1000 / 30;
const DPR_CAP = 2;
const STAGE_ORDINALS = { pose: '第一阶段', surface: '第二阶段', distance: '第三阶段' };

function noticeSeverity(
  mode: WaitingPreviewMode,
): 'info' | 'warning' | 'error' {
  if (mode === 'failed') return 'error';
  if (mode === 'cancelled' || mode === 'completed-missing') return 'warning';
  return 'info';
}

/**
 * 当前阶段没有可用真实产物时的等待区。
 * 画面在有效进度范围内随小车同步展开；新一轮自动更换房间和方向，没有场景交互。
 */
export function WaitingPreview({ stage, connected, runKey }: WaitingPreviewProps) {
  const reducedMotion = useReducedMotion();
  const everConnected = useRef(false);
  useEffect(() => {
    if (connected) everConnected.current = true;
  }, [connected]);
  const connectionLost = everConnected.current && !connected;

  const state = useMemo(
    () => deriveWaitingPreviewState(stage, connected, connectionLost),
    [stage, connected, connectionLost],
  );

  const sceneKey = runKey ?? `${stage.stage}:${stage.backend}:${stage.started_at ?? 'pending'}`;
  const variant = useMemo(() => variantForRun(sceneKey), [sceneKey]);
  const [hidden, setHidden] = useState(
    () => typeof document !== 'undefined' && document.hidden,
  );

  const map = useMemo(() => buildScannerMap(variant.room, variant.direction), [variant]);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const timeRef = useRef(0);
  const robotProgressRef = useRef(state.reveal);
  const lastTickRef = useRef(0);
  const lastDrawRef = useRef(0);
  const sceneRef = useRef({ map, state, reducedMotion });
  sceneRef.current = { map, state, reducedMotion };

  const renderFrame = useCallback((advance: boolean) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width < 2 || height < 2) return;

    const dpr = Math.min(DPR_CAP, Math.max(1, window.devicePixelRatio || 1));
    const pixelWidth = Math.round(width * dpr);
    const pixelHeight = Math.round(height * dpr);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const snapshot = sceneRef.current;
    if (advance) {
      const now = performance.now();
      const delta = lastTickRef.current
        ? Math.min(0.1, (now - lastTickRef.current) / 1000)
        : 0;
      lastTickRef.current = now;
      timeRef.current += delta;
      if (!snapshot.state.standby) {
        robotProgressRef.current = advanceRobotProgress(snapshot.map, robotProgressRef.current, snapshot.state.reveal, delta);
      }
    }

    if (!snapshot.state.showScene) return;
    if (snapshot.reducedMotion) robotProgressRef.current = snapshot.state.reveal;
    drawWaitingScene(ctx, width, height, {
      map: snapshot.map,
      progress: snapshot.state.reveal,
      robotProgress: robotProgressRef.current,
      stage: snapshot.state.stage,
      standby: snapshot.state.standby,
      time: timeRef.current,
    });
  }, []);

  const canAnimate =
    state.animate &&
    state.showScene &&
    !reducedMotion &&
    !hidden;

  // 新一轮使用新的自动场景，清空上一轮的动画计时。
  useEffect(() => {
    timeRef.current = 0;
    robotProgressRef.current = sceneRef.current.state.reveal;
    lastTickRef.current = 0;
    lastDrawRef.current = 0;
    renderFrame(false);
  }, [sceneKey, renderFrame]);

  // 尺寸变化时重建 DPR 画布；只在静态时立即重绘，动画由唯一 RAF 负责。
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return undefined;
    const observer = new ResizeObserver(() => {
      if (!canAnimate) renderFrame(false);
    });
    observer.observe(wrap);
    renderFrame(false);
    return () => observer.disconnect();
  }, [canAnimate, renderFrame]);

  // 减少动态效果、页面隐藏或状态不支持动画时，保留静态帧但响应新快照。
  useEffect(() => {
    if (!canAnimate) renderFrame(false);
  }, [
    canAnimate,
    state,
    map,
    reducedMotion,
    hidden,
    renderFrame,
  ]);

  useEffect(() => {
    if (!canAnimate) return undefined;
    let cancelled = false;
    lastTickRef.current = performance.now();
    lastDrawRef.current = 0;

    const loop = (now: number) => {
      if (cancelled) return;
      rafRef.current = requestAnimationFrame(loop);
      if (now - lastDrawRef.current < FRAME_INTERVAL_MS) return;
      lastDrawRef.current = now;
      renderFrame(true);
    };
    rafRef.current = requestAnimationFrame(loop);

    return () => {
      cancelled = true;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      lastTickRef.current = 0;
    };
  }, [canAnimate, renderFrame]);

  useEffect(() => {
    const onVisibility = () => setHidden(document.hidden);
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  const accent = stageColor(state.stage);
  const motionNote = reducedMotion ? '静态显示' : '';
  const phase = connectionLost ? '连接中断，正在重连'
    : state.standby ? stage.phase === 'associating' ? '轨迹关联' : '等待轨迹导出'
    : stagePhaseLabel(stage);
  const caption = state.mode === 'not-started'
    ? `${STAGE_ORDINALS[state.stage]}尚未开始`
    : `${state.stageLabel}：${phase}`;

  return (
    <Box
      ref={wrapRef}
      className={`waiting-preview waiting-preview--${state.mode}`}
      data-waiting-stage={state.stage}
      data-waiting-mode={state.mode}
      data-waiting-scene={state.showScene ? 'true' : 'false'}
      data-waiting-reveal={state.reveal.toFixed(4)}
      data-waiting-percent={state.percent === null ? '' : state.percent.toFixed(2)}
      data-waiting-animating={canAnimate ? 'true' : 'false'}
      data-waiting-room={variant.room}
      data-waiting-direction={variant.direction}
      sx={{ '--waiting-accent': accent }}
    >
      <Box className="waiting-preview__top">
        <Box className="waiting-preview__tag">等待动画 · 非实时地图</Box>
        <Typography className="waiting-preview__stage">{state.stageLabel}</Typography>
        <Box sx={{ flex: 1 }} />
        {motionNote ? (
          <Typography className="waiting-preview__motion">{motionNote}</Typography>
        ) : null}
        <Typography className="waiting-preview__percent">
          {state.percentText}
        </Typography>
      </Box>

      {state.showScene ? (
        <>
          <canvas
            ref={canvasRef}
            className="waiting-preview__canvas"
            aria-hidden="true"
          />
          <Box className="waiting-preview__bottom">
            <Typography className="waiting-preview__title" role="status" aria-live="polite">
              {caption}
            </Typography>
          </Box>
        </>
      ) : (
        <Box className="waiting-preview__notice">
          <Alert severity={noticeSeverity(state.mode)} sx={{ maxWidth: 560 }}>
            <Typography sx={{ fontSize: 16, fontWeight: 700 }}>
              {state.title}
            </Typography>
            <Typography sx={{ fontSize: 13, lineHeight: 1.6 }}>
              {state.detail}
            </Typography>
          </Alert>
          <Typography className="waiting-preview__footnote">
            图形为示意，不是真实地图；不会用示意动画代替真实结果。
          </Typography>
        </Box>
      )}
    </Box>
  );
}

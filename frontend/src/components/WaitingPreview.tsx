import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { MouseEvent } from 'react';
import {
  Alert,
  Box,
  Button,
  Stack,
  Typography,
} from '@mui/material';
import type { StageDetail } from '../types';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { drawWaitingScene, stageColor } from './waitingPreview/draw';
import { buildScannerMap, clamp, routeAt, sceneArea } from './waitingPreview/route';
import type { Point } from './waitingPreview/route';
import {
  deriveWaitingPreviewState,
  type WaitingPreviewMode,
} from './waitingPreview/state';

export type WaitingPreviewProps = {
  stage: StageDetail;
  connected: boolean;
};

type ScanTarget = {
  point: Point;
  /** 本地示意动画时间轴上的失效时刻，与任务进度无关。 */
  until: number;
};

const TARGET_SECONDS = 2.4;
const FRAME_INTERVAL_MS = 1000 / 30;
const DPR_CAP = 2;

function noticeSeverity(
  mode: WaitingPreviewMode,
): 'info' | 'warning' | 'error' {
  if (mode === 'failed') return 'error';
  if (mode === 'cancelled' || mode === 'completed-missing') return 'warning';
  return 'info';
}

/**
 * 当前阶段没有可用真实产物时的等待区。
 * 画面展开量只来自服务端有效进度；点击、换方向和换房间只改变本地示意。
 */
export function WaitingPreview({ stage, connected }: WaitingPreviewProps) {
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

  const [room, setRoom] = useState(0);
  const [paused, setPaused] = useState(false);
  const [target, setTarget] = useState<ScanTarget | null>(null);
  const [hidden, setHidden] = useState(
    () => typeof document !== 'undefined' && document.hidden,
  );

  const map = useMemo(() => buildScannerMap(room), [room]);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const timeRef = useRef(0);
  const lastTickRef = useRef(0);
  const lastDrawRef = useRef(0);
  const directionStepRef = useRef(0);

  const sceneRef = useRef({ map, state, target });
  sceneRef.current = { map, state, target };

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

    if (advance) {
      const now = performance.now();
      const delta = lastTickRef.current
        ? Math.min(0.1, (now - lastTickRef.current) / 1000)
        : 0;
      lastTickRef.current = now;
      timeRef.current += delta;
    }

    const snapshot = sceneRef.current;
    if (!snapshot.state.showScene) return;
    drawWaitingScene(ctx, width, height, {
      map: snapshot.map,
      progress: snapshot.state.reveal,
      stage: snapshot.state.stage,
      standby: snapshot.state.standby,
      time: timeRef.current,
      target: snapshot.target?.point ?? null,
      targetUntil: snapshot.target?.until ?? 0,
    });
  }, []);

  const canAnimate =
    state.animate &&
    state.showScene &&
    !paused &&
    !reducedMotion &&
    !hidden;

  // 重跑（started_at 变化）时清空上一轮的本地交互和计时。
  useEffect(() => {
    setRoom(0);
    setPaused(false);
    setTarget(null);
    directionStepRef.current = 0;
    timeRef.current = 0;
    lastTickRef.current = 0;
    lastDrawRef.current = 0;
    renderFrame(false);
  }, [stage.stage, stage.started_at, renderFrame]);

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

  // 暂停、减少动态效果、页面隐藏或状态不支持动画时，保留静态帧但响应新快照。
  useEffect(() => {
    if (!canAnimate) renderFrame(false);
  }, [
    canAnimate,
    state,
    map,
    target,
    paused,
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

  const aimAt = useCallback((point: Point) => {
    setTarget({ point, until: timeRef.current + TARGET_SECONDS });
  }, []);

  const onClickCanvas = (event: MouseEvent<HTMLCanvasElement>) => {
    if (!state.showScene || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const area = sceneArea(rect.width, rect.height);
    if (area.w <= 0 || area.h <= 0) return;
    const x = (event.clientX - rect.left - area.x) / area.w;
    const y = (event.clientY - rect.top - area.y) / area.h;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    aimAt({ x: clamp(x, 0, 1), y: clamp(y, 0, 1) });
  };

  const onNewDirection = () => {
    const base = routeAt(map, state.reveal);
    const angle = Math.PI / 6 + directionStepRef.current * (Math.PI / 4);
    directionStepRef.current += 1;
    aimAt({
      x: clamp(base.x + Math.cos(angle) * 0.25, 0.05, 0.95),
      y: clamp(base.y + Math.sin(angle) * 0.2, 0.05, 0.95),
    });
  };

  const onNewRoom = () => {
    setRoom((value) => (value + 1) % 3);
    setTarget(null);
    directionStepRef.current = 0;
  };

  const accent = stageColor(state.stage);
  const motionNote = reducedMotion ? '静态显示' : paused ? '已暂停' : '';
  const showControls = state.showScene && state.mode !== 'cancelling';

  return (
    <Box
      className={`waiting-preview waiting-preview--${state.mode}`}
      data-waiting-stage={state.stage}
      data-waiting-mode={state.mode}
      data-waiting-scene={state.showScene ? 'true' : 'false'}
      data-waiting-reveal={state.reveal.toFixed(4)}
      data-waiting-percent={state.percent === null ? '' : state.percent.toFixed(2)}
      data-waiting-animating={canAnimate ? 'true' : 'false'}
      sx={{ '--waiting-accent': accent }}
    >
      <Box className="waiting-preview__top">
        <Box className="waiting-preview__tag">等待互动 · 非实时地图</Box>
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
            onClick={onClickCanvas}
          />
          <Box className="waiting-preview__bottom">
            <Box className="waiting-preview__copy">
              <Typography className="waiting-preview__title">
                {state.title}
              </Typography>
              <Typography className="waiting-preview__detail">
                {state.detail}
              </Typography>
            </Box>
            {showControls ? (
              <Stack
                direction="row"
                spacing={1}
                flexWrap="wrap"
                useFlexGap
                className="waiting-preview__actions"
              >
                {state.animate && !reducedMotion ? (
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={() => setPaused((value) => !value)}
                  >
                    {paused ? '继续示意' : '暂停示意'}
                  </Button>
                ) : null}
                <Button size="small" variant="outlined" onClick={onNewDirection}>
                  换个方向
                </Button>
                <Button size="small" variant="outlined" onClick={onNewRoom}>
                  换个房间
                </Button>
              </Stack>
            ) : null}
            <Typography className="waiting-preview__footnote">
              {state.legend} · 展开量跟随进度；图形为示意，不是真实地图。
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

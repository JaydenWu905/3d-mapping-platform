import { useEffect, useState } from 'react';
import type { StageDetail, StageKey } from '../types';
import { STAGE_NAMES } from '../utils/jobDisplay';
import { useReducedMotion } from '../hooks/useReducedMotion';

export type Tip = { kind: '介绍' | '操作'; text: string };

/** Keep this list in step with TrajectoryViewer, MeshViewer and EsdfViewer. */
export function tipsForStage(key: string): Tip[] {
  const explain: Record<string, string> = {
    pose: '先给每帧点云找准站位，免得大家各说各话。',
    surface: '让散落的点云排好队，墙面和地面逐渐有了形状。',
    distance: '给已知空间配一把距离尺；没看见的地方先不乱猜。',
  };
  const operations: Record<string, string[]> = {
    pose: ['完成后可用鼠标左键拖拽旋转轨迹、滚轮缩放、右键平移。', '完成后可点“重置视角”；绿色是起点，红色是终点。'],
    surface: ['完成后可用左键旋转模型、滚轮缩放、右键平移，并重置视角。', '完成后可切换中性灰、原始材质或法线方向显示。'],
    distance: ['完成后可切换 XY、XZ、YZ 切片查看不同方向。', '完成后可切换观测掩码和梯度箭头；白色区域没有有效预览采样。'],
  };
  return [{ kind: '介绍', text: explain[key] ?? '' }, ...(operations[key] ?? []).map(text => ({ kind: '操作' as const, text }))];
}

export function PreviewTips({ stage, resultStage, onOpenResult }: {
  stage: StageDetail;
  resultStage?: StageKey | null;
  onOpenResult?: (key: StageKey) => void;
}) {
  const tips = tipsForStage(stage.stage);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [hidden, setHidden] = useState(() => document.hidden);
  const reduced = useReducedMotion();
  useEffect(() => setIndex(0), [stage.stage]);
  useEffect(() => {
    const visibility = () => setHidden(document.hidden || !document.hasFocus());
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('focus', visibility);
    window.addEventListener('blur', visibility);
    return () => { document.removeEventListener('visibilitychange', visibility); window.removeEventListener('focus', visibility); window.removeEventListener('blur', visibility); };
  }, []);
  useEffect(() => {
    if (paused || hidden || reduced || stage.status !== 'running' || tips.length < 2) return undefined;
    const timer = window.setInterval(() => setIndex(i => (i + 1) % tips.length), 10000);
    return () => window.clearInterval(timer);
  }, [paused, hidden, reduced, stage.status, stage.stage, tips.length]);
  const tip = tips[index % tips.length];
  return <section className="preview-tips" aria-label="阶段介绍与预览操作" onMouseEnter={() => setPaused(true)}
    onMouseLeave={() => setPaused(false)} onFocusCapture={() => setPaused(true)} onBlurCapture={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node)) setPaused(false);
    }}>
    <div className="preview-tips__top"><strong>{tip.kind === '操作' ? '结果出来后怎么玩' : '这一步在做什么'}</strong>
      <span>{index % tips.length + 1} / {tips.length}</span></div>
    <p>{tip.text}</p>
    <div className="preview-tips__actions">
      <button type="button" aria-label="上一条提示" onClick={() => setIndex(i => (i - 1 + tips.length) % tips.length)}>上一条</button>
      <button type="button" aria-label="下一条提示" onClick={() => setIndex(i => (i + 1) % tips.length)}>下一条</button>
      {resultStage && onOpenResult ? <button className="preview-tips__result" type="button" onClick={() => onOpenResult(resultStage)}>
        查看已有{STAGE_NAMES[resultStage]}结果
      </button> : null}
    </div>
  </section>;
}

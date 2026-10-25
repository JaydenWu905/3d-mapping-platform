import { useEffect, useState } from 'react';
import type { StageDetail, StageKey } from '../types';
import { STAGE_NAMES } from '../utils/jobDisplay';
import { useReducedMotion } from '../hooks/useReducedMotion';

export type Tip = { kind: '介绍' | '操作'; text: string };
export const TIP_INTERVAL_MS = 14000;

/** Principle explanations, never live measurements or accuracy claims. */
export function tipsForStage(key: string): Tip[] {
  const explain: Record<string, string[]> = {
    pose: ['位姿估计利用 LiDAR 扫描与 IMU 数据，估计传感器的位置、朝向和运动轨迹。', '相邻扫描之间的几何关系与惯性信息共同约束轨迹；示意图不对应本任务的真实路线或定位精度。'],
    surface: ['表面重建依据已估计的位姿，将不同位置采集的点云观测融合到共同坐标系中。', '融合后的观测用于生成墙面、地板等表面；模型覆盖范围与细节取决于输入数据和重建结果。'],
    distance: ['距离场基于已重建的空间数据，计算已知空间中采样位置到表面的距离。', '未知或未观测区域没有足够的数据依据，不能视为已确认安全或可通行区域。'],
  };
  const operations: Record<string, string[]> = {
    pose: ['完成后可用鼠标左键拖拽旋转轨迹、滚轮缩放、右键平移。', '完成后可点“重置视角”；绿色是起点，红色是终点。'],
    surface: ['完成后可用左键旋转模型、滚轮缩放、右键平移，并重置视角。', '完成后可切换中性灰、原始材质或法线方向显示。'],
    distance: ['完成后可切换 XY、XZ、YZ 切片查看不同方向。', '完成后可切换观测掩码和梯度箭头；白色区域没有有效预览采样。'],
  };
  return [...(explain[key] ?? []).map(text => ({kind:'介绍' as const,text})), ...(operations[key] ?? []).map(text => ({kind:'操作' as const,text}))];
}

export function PreviewTips({ stage, resultStage, onOpenResult }: {
  stage: StageDetail; resultStage?: StageKey | null; onOpenResult?: (key: StageKey) => void;
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
    window.addEventListener('focus', visibility); window.addEventListener('blur', visibility);
    return () => { document.removeEventListener('visibilitychange', visibility); window.removeEventListener('focus', visibility); window.removeEventListener('blur', visibility); };
  }, []);
  useEffect(() => {
    if (paused || hidden || reduced || stage.status !== 'running' || tips.length < 2) return undefined;
    const timer = window.setInterval(() => setIndex(i => (i + 1) % tips.length), TIP_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [paused, hidden, reduced, stage.status, stage.stage, tips.length]);
  const active = index % tips.length;
  return <section className="preview-tips" aria-label="阶段介绍与预览操作" onFocusCapture={() => setPaused(true)} onBlurCapture={event => {
    if (!event.currentTarget.contains(event.relatedTarget as Node)) setPaused(false);
  }}>
    <div className="preview-tips__top"><strong>{tips[active]?.kind === '操作' ? '预览操作提示' : '这一步在做什么'}</strong><span>{active + 1} / {tips.length}</span></div>
    <div className="preview-tips__body">{tips.map((tip,i) => <p key={i} aria-hidden={i !== active} style={{visibility:i === active ? 'visible' : 'hidden'}}>{tip.text}</p>)}</div>
    {resultStage && onOpenResult ? <div className="preview-tips__actions"><button className="preview-tips__result" type="button" onClick={() => onOpenResult(resultStage)}>查看已有{STAGE_NAMES[resultStage]}结果</button></div> : null}
  </section>;
}

import { isStageKey } from '../../types';
import type { StageDetail, StageKey } from '../../types';
import { progressBarState } from '../progressLabel';

export type WaitingPreviewMode =
  | 'running'
  | 'queued'
  | 'not-started'
  | 'cancelling'
  | 'failed'
  | 'cancelled'
  | 'completed-missing'
  | 'not-requested';

export type WaitingPreviewState = {
  stage: StageKey;
  stageLabel: string;
  mode: WaitingPreviewMode;
  /** 服务端有效进度，0—100；未知时为 null。 */
  percent: number | null;
  /** 展开量，0—1；未知/排队/未开始时为 0。 */
  reveal: number;
  kind: 'input' | 'stage';
  busy: boolean;
  standby: boolean;
  showScene: boolean;
  /** 是否允许装饰动效；仍需叠加减少动态效果和页面隐藏。 */
  animate: boolean;
  title: string;
  detail: string;
  percentText: string;
  legend: string;
};

const STAGE_LABELS: Record<StageKey, string> = {
  pose: '位姿估计',
  surface: '表面重建',
  distance: '距离场',
};

const TERMINAL_STATUSES: ReadonlySet<string> = new Set(['failed', 'cancelled', 'completed']);

function finitePercent(value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(100, value));
}

function stageDetailCopy(
  stage: StageKey,
  percent: number | null,
  kind: 'input' | 'stage',
  standby: boolean,
): { title: string; detail: string } {
  if (stage === 'pose') {
    if (standby) {
      return {
        title: '输入已发布，等待轨迹导出/关联',
        detail: '位姿估计尚未完成；轨迹预览可用后，可点击“已有成果”查看。',
      };
    }
    if (kind === 'input') {
      return {
        title: '正在发布输入',
        detail: '蓝色路线随小车行进展开，范围以输入发布进度为限。',
      };
    }
    if (percent === null) {
      return {
        title: '正在等待位姿进度',
        detail: '暂未收到有效阶段进度；这里不估算剩余时间。',
      };
    }
    return {
      title: '正在估计位姿',
      detail: '蓝色路线随小车前进展开；轨迹就绪后可在“已有成果”中查看。',
    };
  }

  if (stage === 'surface') {
    if (percent === null) {
      return {
        title: '正在重建表面',
        detail: '暂未收到有效进度，小车和紫色网格会等待进度更新。',
      };
    }
    return {
      title: '正在重建表面',
      detail: '紫色三角网格在小车经过时铺开；完成后可在“已有成果”中查看网格。',
    };
  }

  if (percent === null) {
    return {
      title: '正在计算距离场',
      detail: '暂未收到有效进度，小车和距离色块会等待进度更新。',
    };
  }
  return {
    title: '正在计算距离场',
    detail: '距离色块在小车经过时展开，颜色只表示示意空间的远近。',
  };
}

/**
 * 把现有 StageDetail 语义收窄成等待预览所需的状态。
 * 展开量只来自 progressBarState 的有效百分比，不使用时间或扫描圈数。
 */
export function deriveWaitingPreviewState(
  stage: StageDetail,
  connected: boolean,
  connectionLost = false,
): WaitingPreviewState {
  // StageViewer 只会把三个固定阶段传进来；这里仍做一次运行时收窄。
  const stageKey: StageKey = isStageKey(stage.stage) ? stage.stage : 'pose';
  const stageLabel = STAGE_LABELS[stageKey];
  const bar = progressBarState(stage);
  const percent = finitePercent(bar.percent);

  if (stage.status === 'not_integrated') {
    return {
      stage: stageKey,
      stageLabel,
      mode: 'not-requested',
      percent: null,
      reveal: 0,
      kind: bar.kind,
      busy: false,
      standby: false,
      showScene: false,
      animate: false,
      title: '本任务未请求该阶段',
      detail: '该阶段没有运行，因此没有等待预览。',
      percentText: '未请求',
      legend: '未运行',
    };
  }

  if (stage.status === 'completed') {
    return {
      stage: stageKey,
      stageLabel,
      mode: 'completed-missing',
      percent: null,
      reveal: 0,
      kind: bar.kind,
      busy: false,
      standby: false,
      showScene: false,
      animate: false,
      title: '阶段已完成，但没有可用的预览产物',
      detail: '请检查产物清单或下载完整产物；不会用示意动画代替真实结果。',
      percentText: '已完成 · 缺少产物',
      legend: '等待真实产物',
    };
  }

  if (stage.status === 'failed') {
    return {
      stage: stageKey,
      stageLabel,
      mode: 'failed',
      percent: null,
      reveal: 0,
      kind: bar.kind,
      busy: false,
      standby: false,
      showScene: false,
      animate: false,
      title: '阶段运行失败',
      detail: '请查看阶段状态与错误信息；等待动效已停止。',
      percentText: '运行失败',
      legend: '已停止',
    };
  }

  if (stage.status === 'cancelled') {
    return {
      stage: stageKey,
      stageLabel,
      mode: 'cancelled',
      percent: null,
      reveal: 0,
      kind: bar.kind,
      busy: false,
      standby: false,
      showScene: false,
      animate: false,
      title: '阶段已取消',
      detail: '等待动效已停止；重新运行后会按新的进度重新绘制。',
      percentText: '已取消',
      legend: '已停止',
    };
  }

  if (stage.status === 'cancelling') {
    return {
      stage: stageKey,
      stageLabel,
      mode: 'cancelling',
      percent,
      reveal: percent === null ? 0 : percent / 100,
      kind: bar.kind,
      busy: false,
      standby: false,
      showScene: true,
      animate: false,
      title: '正在取消阶段',
      detail: '已停止等待动效，等待取消结果。',
      percentText: percent === null ? '取消中' : `阶段进度 ${Math.round(percent)}%`,
      legend: '已停止 · 等待取消',
    };
  }

  if (stage.status === 'queued') {
    return {
      stage: stageKey,
      stageLabel,
      mode: 'queued',
      percent: null,
      reveal: 0,
      kind: bar.kind,
      busy: false,
      standby: false,
      showScene: true,
      animate: false,
      title: '任务排队中',
      detail: '开始处理后，示意画面才会随有效进度展开。',
      percentText: '排队中',
      legend: '尚未展开',
    };
  }

  if (stage.status === 'waiting') {
    return {
      stage: stageKey,
      stageLabel,
      mode: 'not-started',
      percent: null,
      reveal: 0,
      kind: bar.kind,
      busy: false,
      standby: false,
      showScene: true,
      animate: false,
      title: '阶段尚未开始',
      detail: '运行后会显示等待动画；展开量只跟随有效进度。',
      percentText: '尚未开始',
      legend: '尚未展开',
    };
  }

  const standby =
    stageKey === 'pose' &&
    stage.backend === 'glim' &&
    (stage.phase === 'waiting_glim_export' ||
      stage.phase === 'associating' ||
      (bar.kind === 'input' && percent === 100));

  const copy = stageDetailCopy(stageKey, percent, bar.kind, standby);
  const lost = connectionLost && !TERMINAL_STATUSES.has(stage.status);

  return {
    stage: stageKey,
    stageLabel,
    mode: 'running',
    percent,
    reveal: percent === null ? 0 : percent / 100,
    kind: bar.kind,
    busy: bar.busy,
    standby,
    showScene: true,
    animate: connected,
    title: lost ? '连接中断，正在重连' : copy.title,
    detail: lost
      ? '画面保留最后一次有效状态；连接恢复后会按新快照更新。'
      : copy.detail,
    percentText:
      percent === null
        ? '进度未上报'
        : bar.kind === 'input'
          ? `输入发布 ${Math.round(percent)}%`
          : `阶段进度 ${Math.round(percent)}%`,
    legend: standby
      ? '输入发布完毕 · 小车待命'
      : stageKey === 'pose'
        ? '蓝色路线示意'
        : stageKey === 'surface'
          ? '紫色三角网格示意'
          : '距离色块示意',
  };
}

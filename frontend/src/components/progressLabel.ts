import type { StageDetail } from '../types';

export type ProgressBarState = {
  percent: number | null;
  kind: 'input' | 'stage';
  busy: boolean;
};

export const STAGE_LABELS: Record<string, string> = {
  pose: '位姿估计',
  surface: '表面重建',
  distance: '距离场',
};

export const STAGE_STATUS_LABELS: Record<string, string> = {
  waiting: '等待中',
  queued: '排队中',
  running: '运行中',
  cancelling: '取消中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  not_integrated: '未请求',
};

/** 后端 phase 的展示名；未知值不应直接出现在界面上。 */
const PHASE_LABELS: Record<string, string> = {
  waiting: '等待中',
  queued: '排队中',
  running: '运行中',
  starting: '启动中',
  preparing: '准备中',
  validating: '校验输入',
  loading: '加载输入',
  input_publishing: '输入发布',
  waiting_glim_export: '等待 GLIM 导出',
  associating: '轨迹关联',
  starting_glim: '启动 GLIM',
  tracking: '位姿跟踪',
  optimizing: '优化处理',
  mapping: '表面融合',
  computing: '距离场计算',
  esdf_generation: '距离计算',
  slice_rendering: '整理距离切片',
  building_preview: '生成预览',
  validating_outputs: '检查输出',
  exporting: '正在导出',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  cancelling: '取消中',
  interrupted: '已中断',
  input_preparation_failed: '输入准备失败',
};

/** 后端固定英文消息的展示名，原始文本保留在悬停提示与技术详情中。 */
const MESSAGE_LABELS: Record<string, string> = {
  'Starting mock runner': '正在启动演示运行器',
  Completed: '已完成',
  'Simulated failure (demo)': '演示模拟失败',
  'Cancelled by user': '用户已取消',
  'Demo assets missing': '演示数据缺失',
  'Starting real MrHash process': '正在启动真实 MrHash 进程',
  'Validating server-registered precomputed Pose': '正在校验服务器注册的预计算位姿',
  'Registered precomputed Pose validated and imported': '服务器注册的预计算位姿已校验并导入',
  'Loading input sequence': '正在加载输入序列',
  'Global pose-graph optimization': '正在进行全局位姿图优化',
  'Exporting trajectory': '正在导出轨迹',
  'Preparing surface map': '正在准备表面地图',
  'Post-processing mesh': '正在进行网格后处理',
  'Exporting surface mesh': '正在导出表面网格',
  'Loading surface mesh': '正在加载表面网格',
  'Computing signed distance to TSDF zero surface': '正在计算到 TSDF 零交叉表面的带符号欧氏距离',
  'Rendering observed-support signed distance slices': '正在渲染观测支持域的距离切片',
  'Brute-force ESDF propagation': '正在进行 ESDF 传播计算',
  'Multi-resolution sweep': '正在进行多分辨率扫描',
  'Exporting distance slices': '正在导出距离场切片',
  'Backend restarted while the subprocess was running': '后端服务重启，运行中的子进程已中断',
};

const UNIT_LABELS: Record<string, string> = {
  frame: '帧',
  frames: '帧',
  voxel: '体素',
  voxels: '体素',
  pose: '位姿',
  poses: '位姿',
  second: '秒',
  seconds: '秒',
  sec: '秒',
  s: '秒',
};

function hasChinese(text: string): boolean {
  return /[㐀-鿿]/.test(text);
}

function trimText(value: string | null | undefined): string {
  return (value || '').trim();
}

/** 后端单位转中文；未知单位（含已经写好的中文单位）原样展示。 */
export function unitLabel(unit: string | null | undefined): string {
  const value = trimText(unit);
  if (!value) return '';
  return UNIT_LABELS[value.toLowerCase()] ?? value;
}

/** 耗时统一为“42 秒 / 1 分 58 秒 / 1 小时 2 分”。 */
export function formatElapsed(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec) || sec <= 0) return '—';
  const total = Math.floor(sec);
  if (total <= 0) return '不足 1 秒';
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  if (minutes > 0) return `${minutes} 分 ${seconds} 秒`;
  return `${seconds} 秒`;
}

function statusMessageFallback(stage: StageDetail): string {
  switch (stage.status) {
    case 'completed':
      return '已完成';
    case 'failed':
      return '运行失败，请展开技术详情查看原因';
    case 'cancelled':
      return '已取消';
    case 'cancelling':
      return '取消中';
    case 'queued':
      return '排队中';
    case 'running':
      return '处理中';
    case 'not_integrated':
      return '未请求';
    default:
      return '待命';
  }
}

/** 阶段当前环节；GLIM 位姿阶段沿用输入发布/等待导出/轨迹关联的专用语义。 */
export function stagePhaseLabel(stage: StageDetail): string {
  if (stage.stage === 'pose' && stage.backend === 'glim') {
    return posePhaseLabel(stage);
  }
  if (stage.status === 'waiting') {
    const match = /^(Pose|Surface) must be completed/.exec(stage.run_blocked_reason || '');
    if (match) return `等待${match[1] === 'Pose' ? '位姿估计' : '表面重建'}完成`;
    return stage.can_run ? '准备就绪' : '等待开始';
  }
  if (stage.status === 'not_integrated') return '未请求';
  if (stage.status === 'queued') return '等待计算资源';
  if (stage.status === 'cancelling') return '取消中';
  if (stage.status === 'completed') return '已完成';
  if (stage.status === 'failed') return '失败';
  if (stage.status === 'cancelled') return '已取消';

  const phase = trimText(stage.phase);
  if (!phase) return stage.status === 'running' ? '运行中' : '待命';
  const mapped = PHASE_LABELS[phase];
  if (mapped) return mapped;
  if (hasChinese(phase)) return phase;
  return stage.status === 'running' ? '处理中' : '待命';
}

/** 阶段消息的中文摘要；未知英文回退到状态文案，原始消息仍保留在 title 中。 */
export function stageMessageLabel(stage: StageDetail): string {
  if (stage.status === 'waiting') return stagePhaseLabel(stage);
  if (stage.status === 'queued') return '等待计算资源';
  if (stage.status === 'completed') return '已完成，可查看真实结果';
  if (stage.status === 'cancelled') return '已取消';
  if (stage.status === 'cancelling') return '正在取消';
  const message = trimText(stage.message);
  if (stage.status === 'failed') {
    const code = /^Algorithm adapter exited with code (\d+)$/.exec(message);
    return code ? `运行失败（退出代码 ${code[1]}）` : '运行失败，请查看日志与技术详情';
  }
  if (/tqdm|融合调用|分母|全包消息/.test(message)) return '正在重建表面';
  if (!message) return statusMessageFallback(stage);
  const mapped = MESSAGE_LABELS[message];
  if (mapped) return mapped;
  if (hasChinese(message)) return message;

  const tracking = /^Tracking pose (\d+)\/(\d+)$/.exec(message);
  if (tracking) return `位姿跟踪 ${tracking[1]} / ${tracking[2]} 帧`;
  const fusing = /^Fusing frames (\d+)\/(\d+)$/.exec(message);
  if (fusing) return `正在融合 ${fusing[1]} / ${fusing[2]} 帧`;
  const exitCode = /^Algorithm adapter exited with code (\d+)$/.exec(message);
  if (exitCode) return `算法适配器退出（代码 ${exitCode[1]}）`;
  if (message === 'Adapter exited successfully without a completed manifest') {
    return '算法适配器结束，但未生成完整结果清单';
  }
  if (/^GPU reservation or runner failed:/.test(message)) {
    return 'GPU 资源预留或运行器启动失败';
  }
  if (/^Invalid runner mode:/.test(message)) return '运行模式无效';
  if (/stage exceeded its configured timeout$/.test(message)) return '阶段执行超时';
  if (/^Surface input preparation failed:/.test(message)) {
    return '表面输入准备失败，请展开技术详情查看原因';
  }
  return statusMessageFallback(stage);
}

const BLOCKED_REASON_LABELS: Record<string, string> = {
  'Stage already running': '阶段正在运行',
  'Stage already completed': '阶段已完成',
  'Selected backend is disabled': '所选后端已禁用',
  '此阶段未包含在本 Job 的执行范围': '此阶段未包含在本任务的执行范围',
};

const STAGE_EN_LABELS: Record<string, string> = {
  Pose: '位姿估计',
  Surface: '表面重建',
  Distance: '距离场',
};

/** can_run 阻止原因的中文摘要；未知英文回退为通用说明。 */
export function blockedReasonLabel(reason: string | null | undefined): string {
  const value = trimText(reason);
  if (!value) return '';
  const exact = BLOCKED_REASON_LABELS[value];
  if (exact) return exact;
  if (hasChinese(value)) return value;

  let match = /^Backend '([^']+)' not in registry$/.exec(value);
  if (match) return `所选后端未注册（${match[1]}）`;
  match = /^No real runner is available for ([^/]+)\/([^/]+)$/.exec(value);
  if (match) {
    const stage = STAGE_LABELS[match[1]] ?? match[1];
    return `真实后端运行器不可用（${stage} / ${match[2]}）`;
  }
  match = /^(Pose|Surface) must be completed before running (Pose|Surface|Distance)$/.exec(value);
  if (match) {
    return `需先完成${STAGE_EN_LABELS[match[1]]}，才能运行${STAGE_EN_LABELS[match[2]]}`;
  }
  match = /^backend '([^']+)' is not in the (Pose|Surface) registry$/.exec(value);
  if (match) {
    const stage = match[2] === 'Pose' ? '位姿' : '表面重建';
    return `${stage}后端未注册（${match[1]}）`;
  }
  match = /^the dataset registry declares Pose backend '([^']+)'$/.exec(value);
  if (match) return `数据集注册的位姿后端为 ${match[1]}`;
  if (/^the dataset registry has no 'pose' block/.test(value)) {
    return '数据集未声明位姿后端配置（缺少话题、帧或 GLIM 配置）';
  }
  match = /^the dataset is missing required Pose modalities: (.+)$/.exec(value);
  if (match) return `数据集缺少位姿估计所需模态：${match[1]}`;
  match = /^Dataset '([^']+)' currently supports surface backend '([^']+)' only$/.exec(value);
  if (match) return `数据集 ${match[1]} 仅支持表面重建后端 ${match[2]}`;
  match = /^Dataset '([^']+)' modalities .* are incompatible with surface backend '([^']+)'/.exec(value);
  if (match) return `数据集 ${match[1]} 的模态与表面重建后端 ${match[2]} 不兼容`;
  return '当前条件下不可运行，请展开技术详情查看原因';
}

export function progressBarState(stage: StageDetail): ProgressBarState {
  const active = stage.status === 'running' || stage.status === 'queued' || stage.status === 'cancelling';
  if (stage.stage !== 'pose' || stage.backend !== 'glim' || stage.status === 'completed') {
    return { percent: Math.max(0, Math.min(100, stage.progress || 0)), kind: 'stage', busy: false };
  }
  const total = stage.lidar_total ?? 0;
  const published = stage.lidar_published ?? 0;
  const publishing = stage.phase === 'input_publishing';
  const publishedDone = stage.phase === 'waiting_glim_export' || stage.phase === 'associating';
  if (total > 0 && (publishing || publishedDone || published > 0)) {
    return {
      percent: publishedDone ? 100 : Math.max(0, Math.min(100, published / total * 100)),
      kind: 'input',
      busy: active && publishedDone,
    };
  }
  return { percent: null, kind: 'input', busy: active };
}

export function progressLabel(stage: StageDetail): string {
  const metrics = stage.manifest?.metrics;
  if (stage.stage === 'pose' && metrics?.pose_count != null) {
    return `输出 ${metrics.pose_count} 位姿 · 全包 ${metrics.bag_frame_count ?? '—'} 帧`;
  }
  if (stage.stage === 'pose') {
    if (stage.phase === 'input_publishing' || stage.phase === 'waiting_glim_export' || stage.phase === 'associating') {
      const lidar = stage.lidar_published ?? 0;
      const total = stage.lidar_total ?? 0;
      const ratio = total > 0 ? `（输入发布进度 ${Math.round(progressBarState(stage).percent ?? 0)}%）` : '';
      return `LiDAR 已发布 ${lidar}/${total || '总量未知'} ${ratio} · IMU 已发布 ${stage.imu_published ?? 0}${stage.imu_total ? `/${stage.imu_total}` : ''}`;
    }
    return stage.status === 'failed' ? '位姿估计失败' : '等待执行 / 启动 GLIM';
  }
  if (stage.stage === 'distance' && stage.status === 'completed' && typeof metrics?.observed === 'number') {
    return `输出 ${metrics.observed.toLocaleString('zh-CN')} 有效体素 · 分辨率 ${metrics.resolution_m ?? '—'} m`;
  }
  if (stage.stage === 'surface' && typeof metrics?.fused_frames === 'number') {
    return `已融合 ${metrics.fused_frames.toLocaleString('zh-CN')} 帧 · 选中 ${metrics.selected_frames ?? '—'} 帧`;
  }
  if (stage.stage === 'surface' && stage.total > 0) return `处理计数 ${stage.current} / ${stage.total}`;
  if (!stage.total) return stage.status === 'running' ? '暂未收到计数' : '';
  const unit = unitLabel(stage.unit);
  return `${stage.current} / ${stage.total}${unit ? ` ${unit}` : ''}`;
}

export function posePhaseLabel(stage: StageDetail): string {
  if (stage.status === 'completed') return '位姿估计完成';
  if (stage.status === 'failed') return '位姿估计失败';
  if (stage.status === 'cancelled') return '位姿估计已取消';
  if (stage.status === 'cancelling') return '位姿估计取消中';
  if (stage.status === 'queued') return '位姿估计排队中';
  if (stage.status === 'waiting') return stage.can_run ? '准备就绪' : '等待开始';
  switch (stage.phase) {
    case 'input_publishing': return '输入发布';
    case 'waiting_glim_export': return '输入发布完成，正在等待 GLIM 导出';
    case 'associating': return '轨迹关联与产物生成';
    case 'starting_glim': return '启动 GLIM';
    case 'starting': return '启动中';
    case 'preparing': return '准备中';
    case 'tracking': return '位姿跟踪';
    case 'optimizing': return '全局位姿优化';
    case 'exporting': return '正在导出轨迹';
    default:
      return stage.status === 'running' ? 'GLIM 运行中' : '等待执行 / 启动 GLIM';
  }
}

export function stageProgressText(stage: StageDetail): string {
  return stage.stage === 'pose' && stage.backend === 'glim' && stage.status !== 'completed'
    ? posePhaseLabel(stage)
    : `阶段 ${Math.round(stage.progress)}%`;
}

import type { StageDetail } from '../../types';
import { blockedReasonLabel, STAGE_LABELS } from '../progressLabel';

export function dependencyLabel(stage: StageDetail): string | null {
  if (stage.status !== 'waiting') return null;
  const match = /^(Pose|Surface) must be completed before running/.exec(stage.run_blocked_reason || '');
  if (match) return `等待${match[1] === 'Pose' ? '位姿估计' : '表面重建'}完成`;
  const chinese = /需先完成(位姿估计|表面重建)/.exec(stage.run_blocked_reason || '');
  return chinese ? `等待${chinese[1]}完成` : null;
}

/** Normal lifecycle restrictions are not warnings. Never infer an automatic chain. */
export function stageNotice(stage: StageDetail): { severity: 'error' | 'warning'; text: string } | null {
  if (stage.status === 'failed') return { severity: 'error', text: '运行失败，请查看下方日志与技术详情。' };
  if (stage.status !== 'waiting' || stage.can_run || dependencyLabel(stage)) return null;
  const reason = stage.run_blocked_reason || '';
  if (!reason || /Stage already (running|completed)/.test(reason)) return null;
  return { severity: 'warning', text: blockedReasonLabel(reason) };
}

export function waitingTitle(stage: StageDetail): string {
  const dependency = dependencyLabel(stage);
  if (dependency) return dependency;
  const status: Record<string, string> = {
    waiting: stage.can_run ? '准备就绪，可启动' : '等待开始',
    queued: '等待计算资源', cancelling: '正在取消', cancelled: '已取消',
    failed: '运行遇到了问题', completed: '阶段已完成，暂无预览', not_integrated: '本任务未请求该阶段',
  };
  if (status[stage.status]) return status[stage.status];
  if (stage.stage === 'pose') {
    if (stage.phase === 'waiting_glim_export' || stage.phase === 'exporting') return '等待轨迹导出';
    if (stage.phase === 'associating') return '正在关联轨迹';
    if (stage.phase === 'input_publishing') return '正在处理扫描输入';
  }
  if (/export|preview|slice/.test(stage.phase)) return '正在整理结果';
  return `${STAGE_LABELS[stage.stage] || '任务'}进行中`;
}

export function waitingMessages(stage: StageDetail): readonly string[] {
  if (stage.status === 'failed') return ['这一步没能完成。可展开技术详情或日志查看原因。'];
  if (stage.status === 'cancelled') return ['处理已停止。若有已完成的阶段，可切换查看结果。'];
  if (stage.status === 'cancelling') return ['正在等待处理进程退出。'];
  if (stage.status === 'queued') return [stage.message && /位置|前方|第\s*\d/.test(stage.message) ? stage.message : '正在等待计算资源。队列信息以任务状态为准。'];
  if (stage.status === 'completed') return ['请检查结果清单，或在文件可用时下载原生产物。'];
  if (stage.status === 'not_integrated') return ['本阶段不在此次运行范围内。'];
  if (stage.status === 'waiting') return [dependencyLabel(stage) ? '前一步的结果就绪后，才能处理这一阶段。' : '运行范围和阶段算法已保留，可按任务状态选择操作。'];
  if (stage.stage === 'pose') {
    if (stage.phase === 'waiting_glim_export' || stage.phase === 'exporting') return ['输入已送达，正在等待轨迹导出。', 'GLIM 正在整理轨迹，已运行时间会继续更新。'];
    if (stage.phase === 'associating') return ['正在对齐点云帧时间与位姿时间。', '时间关联完成后，表面重建可读取对应帧的位姿。'];
    return ['位姿估计使用 LiDAR 扫描与 IMU 数据估计位置和朝向。', '示意路线仅说明处理过程，实际轨迹以生成的结果为准。'];
  }
  if (/export|preview|slice/.test(stage.phase)) return ['计算结果正在整理，准备好可查看的预览与文件。', '预览文件与原生产物会分别列出。'];
  if (stage.stage === 'surface') return ['依据位姿融合点云观测，生成场景表面。', '表面重建将不同位置的观测放入共同坐标系。'];
  return ['基于已重建的数据计算空间到表面的距离。', '未观测区域不表示已确认安全或可通行。'];
}

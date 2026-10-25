export const JOB_NAME_LIMIT = 80;

export function normalizedJobName(value: string): string {
  return value.normalize('NFC').trim().replace(/\s+/gu, ' ');
}

export function jobNameError(value: string): string | null {
  if (/[\p{C}<>\\]/u.test(value)) return '名称不能包含控制字符、尖括号或反斜杠';
  const length = [...normalizedJobName(value)].length;
  return length < 1 || length > JOB_NAME_LIMIT ? '请输入 1–80 个字符的任务名称' : null;
}

export function jobDisplayName(job: { name?: string | null; created_at?: string }): string {
  if (job.name?.trim()) return job.name.trim();
  const date = job.created_at?.match(/^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/);
  return date ? `建图任务 · ${date[1]} ${date[2]}` : '未命名任务';
}

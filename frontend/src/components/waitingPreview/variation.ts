export type SceneVariant = { room: number; direction: number };

/** 连续场景和每隔三个阶段的下一轮都换房间、换出发方向。 */
export function sceneVariant(sequence: number): SceneVariant {
  const index = Math.max(0, Math.floor(sequence));
  return { room: (index + Math.floor(index / 3)) % 3, direction: index % 4 };
}

const STORAGE_KEY = 'mapping-waiting-scenes-v1';
const assigned = new Map<string, SceneVariant>();
let nextSequence = 0;
let restored = false;

/** 同一任务阶段重挂载时复用布局；新一轮自动选下一种，无需任何点击。 */
export function variantForRun(key: string): SceneVariant {
  if (!restored) {
    restored = true;
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null');
      if (saved && Number.isSafeInteger(saved.next) && saved.next >= 0) {
        nextSequence = saved.next;
        for (const entry of (Array.isArray(saved.entries) ? saved.entries : []).slice(-64)) {
          const [runKey, value] = entry;
          if (typeof runKey === 'string' && Number.isInteger(value?.room) && value.room >= 0 && value.room < 3 && Number.isInteger(value.direction) && value.direction >= 0 && value.direction < 4) assigned.set(runKey, value);
        }
      }
    } catch { /* 存储不可用时保留本页内自动轮换。 */ }
  }
  const existing = assigned.get(key);
  if (existing) return existing;
  const variant = sceneVariant(nextSequence++);
  assigned.set(key, variant);
  if (assigned.size > 64) assigned.delete(assigned.keys().next().value as string);
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ next: nextSequence, entries: [...assigned] }));
  } catch { /* 不影响等待动画和任务状态。 */ }
  return variant;
}

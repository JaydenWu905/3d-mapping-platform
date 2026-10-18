export type Point = { x: number; y: number };

export type Obstacle = { x: number; y: number; w: number; h: number };

export type RouteCell = Point & {
  col: number;
  row: number;
  key: string;
  reveal: number;
  clearance: number;
};

export type ScannerMap = {
  room: number;
  direction: number;
  cols: number;
  rows: number;
  route: RouteCell[];
  lengths: number[];
  cells: RouteCell[];
};

export type SceneArea = { x: number; y: number; w: number; h: number };

const COLS = 17;
const ROWS = 11;
const MAP_ASPECT = COLS / ROWS;

/** 三个原创示意房间；坐标均为 0—1 的抽象空间，不对应真实地图。 */
const ROOM_OBSTACLES: Obstacle[][] = [
  [
    { x: 0.22, y: 0.28, w: 0.16, h: 0.18 },
    { x: 0.59, y: 0.38, w: 0.19, h: 0.23 },
    { x: 0.32, y: 0.73, w: 0.23, h: 0.05 },
  ],
  [
    { x: 0.3, y: 0.3, w: 0.07, h: 0.42 },
    { x: 0.58, y: 0.1, w: 0.07, h: 0.35 },
    { x: 0.68, y: 0.7, w: 0.18, h: 0.08 },
  ],
  [
    { x: 0.16, y: 0.2, w: 0.26, h: 0.09 },
    { x: 0.65, y: 0.22, w: 0.18, h: 0.18 },
    { x: 0.4, y: 0.55, w: 0.13, h: 0.2 },
  ],
];

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function obstaclesForRoom(room: number, direction = 0): Obstacle[] {
  return ROOM_OBSTACLES[((room % 3) + 3) % 3].map(o => ({
    ...o,
    x: direction & 1 ? 1 - o.x - o.w : o.x,
    y: direction & 2 ? 1 - o.y - o.h : o.y,
  }));
}

/**
 * 生成一条覆盖房间内空闲格子的蛇形路线。
 * 结果只取决于房间编号，是纯粹的示意几何，与后端进度和真实坐标无关。
 */
export function buildScannerMap(room: number, direction = 0): ScannerMap {
  const obstacles = obstaclesForRoom(room, direction);
  const cells: RouteCell[] = [];
  const byKey = new Map<string, RouteCell>();

  for (let rowIndex = ROWS - 1; rowIndex >= 0; rowIndex -= 1) {
    const row = direction & 2 ? ROWS - 1 - rowIndex : rowIndex;
    for (let i = 0; i < COLS; i += 1) {
      const baseCol = rowIndex % 2 ? i : COLS - 1 - i;
      const col = direction & 1 ? COLS - 1 - baseCol : baseCol;
      const x = (col + 0.5) / COLS;
      const y = (row + 0.5) / ROWS;
      const blocked = obstacles.some(
        (o) =>
          x > o.x - 0.025 &&
          x < o.x + o.w + 0.025 &&
          y > o.y - 0.025 &&
          y < o.y + o.h + 0.025,
      );
      if (blocked) continue;
      const cell: RouteCell = {
        col,
        row,
        x,
        y,
        key: `${col}:${row}`,
        reveal: 0,
        clearance: 0,
      };
      cells.push(cell);
      byKey.set(cell.key, cell);
    }
  }

  const first = cells[0];
  if (!first) {
    return { room, direction, cols: COLS, rows: ROWS, route: [], lengths: [0], cells: [] };
  }

  const route: RouteCell[] = [first];
  const seen = new Set<string>([first.key]);

  for (const cell of cells.slice(1)) {
    if (seen.has(cell.key)) continue;
    const start = route[route.length - 1];
    const queue: RouteCell[] = [start];
    const parents = new Map<string, RouteCell | null>([[start.key, null]]);
    for (let head = 0; head < queue.length && !parents.has(cell.key); head += 1) {
      const current = queue[head];
      for (const [dx, dy] of [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
      ] as const) {
        const next = byKey.get(`${current.col + dx}:${current.row + dy}`);
        if (next && !parents.has(next.key)) {
          parents.set(next.key, current);
          queue.push(next);
        }
      }
    }
    if (!parents.has(cell.key)) continue;
    const segment: RouteCell[] = [];
    let cursor: RouteCell | null = cell;
    while (cursor && cursor.key !== start.key) {
      segment.push(cursor);
      cursor = parents.get(cursor.key) ?? null;
    }
    segment.reverse().forEach((point) => {
      route.push(point);
      seen.add(point.key);
    });
  }

  const firstIndex = new Map<string, number>();
  route.forEach((point, index) => {
    if (!firstIndex.has(point.key)) firstIndex.set(point.key, index);
  });

  const ordered = cells
    .filter((cell) => firstIndex.has(cell.key))
    .sort((a, b) => (firstIndex.get(a.key) ?? 0) - (firstIndex.get(b.key) ?? 0));

  const lengths = [0];
  for (let i = 1; i < route.length; i += 1) {
    lengths.push(
      lengths[i - 1] +
        Math.hypot(route[i].x - route[i - 1].x, route[i].y - route[i - 1].y),
    );
  }

  const total = lengths[lengths.length - 1] || 1;
  ordered.forEach((cell) => {
    cell.reveal = (lengths[firstIndex.get(cell.key) ?? 0] ?? 0) / total;
    const toWalls = Math.min(cell.x, 1 - cell.x, cell.y, 1 - cell.y);
    const toObstacles = obstacles.map((o) =>
      Math.hypot(
        Math.max(o.x - cell.x, 0, cell.x - o.x - o.w),
        Math.max(o.y - cell.y, 0, cell.y - o.y - o.h),
      ),
    );
    cell.clearance = Math.min(toWalls, ...toObstacles);
  });

  return { room, direction, cols: COLS, rows: ROWS, route, lengths, cells: ordered };
}

/** 按累计路线长度插值；progress 只应来自服务端有效进度。 */
export function routeAt(map: ScannerMap, progress: number): Point {
  const route = map.route;
  if (route.length === 0) return { x: 0.5, y: 0.5 };
  if (route.length === 1) return { x: route[0].x, y: route[0].y };

  const total = map.lengths[map.lengths.length - 1] || 0;
  const distance = clamp(progress, 0, 1) * total;
  let index = 1;
  while (index < map.lengths.length - 1 && map.lengths[index] < distance) index += 1;
  const span = map.lengths[index] - map.lengths[index - 1];
  const fraction = span > 0 ? clamp((distance - map.lengths[index - 1]) / span, 0, 1) : 0;
  return {
    x: route[index - 1].x + (route[index].x - route[index - 1].x) * fraction,
    y: route[index - 1].y + (route[index].y - route[index - 1].y) * fraction,
  };
}

export function revealedCellCount(map: ScannerMap, progress: number): number {
  if (progress <= 0) return 0;
  return map.cells.filter((cell) => cell.reveal <= progress + 1e-9).length;
}

/**
 * 画布内示意地图的位置。上下留出简短说明，避免窄屏时被遮住。
 */
export function sceneArea(width: number, height: number): SceneArea {
  const padX = Math.max(14, Math.min(48, width * 0.045));
  const compact = height < 520;
  const top = compact ? 56 : Math.max(48, Math.min(68, height * 0.12));
  // 自动播放没有操作区，把腾出的空间留给地图。
  const bottom = compact
    ? 118
    : Math.max(112, Math.min(144, height * 0.19));
  const availableW = Math.max(40, width - padX * 2);
  const availableH = Math.max(40, height - top - bottom);

  let w = Math.min(availableW, 900, availableH * MAP_ASPECT);
  let h = w / MAP_ASPECT;
  if (h > availableH) {
    h = availableH;
    w = h * MAP_ASPECT;
  }

  return {
    x: (width - w) / 2,
    y: top + (availableH - h) / 2,
    w,
    h,
  };
}

import type { StageKey } from '../../types';
import { clamp, obstaclesForRoom, routeAt, sceneArea } from './route';
import type { Point, SceneArea, ScannerMap } from './route';

const BLUE = '#1877F2';
const PURPLE = '#8E33FF';
const CYAN = '#00B8D9';
const MUTED = '#637381';

const DISTANCE_COLORS = ['#9ecbff', '#64bce9', '#65d5df', '#b6e9c3', '#ffe09a'];
const SURFACE_COLORS = ['#ddc4ff', '#cfa5ff', '#bb80fa'];

export type WaitingSceneOptions = {
  map: ScannerMap;
  progress: number;
  stage: StageKey;
  standby: boolean;
  time: number;
  target: Point | null;
  targetUntil: number;
};

export function stageColor(stage: StageKey): string {
  if (stage === 'surface') return PURPLE;
  if (stage === 'distance') return CYAN;
  return BLUE;
}

function withAlpha(hex: string, alpha: number): string {
  const value = hex.replace('#', '');
  const r = Number.parseInt(value.slice(0, 2), 16);
  const g = Number.parseInt(value.slice(2, 4), 16);
  const b = Number.parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * 绘制等待区示意场景。
 * 展开量完全由 options.progress 决定；time 只影响小车局部巡航、扫描线和目标脉冲。
 */
export function drawWaitingScene(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  options: WaitingSceneOptions,
): SceneArea {
  const { map, progress, stage, standby, time, target, targetUntil } = options;
  const area = sceneArea(width, height);
  const color = stageColor(stage);

  ctx.clearRect(0, 0, width, height);
  ctx.lineCap = 'butt';
  ctx.lineJoin = 'miter';

  const px = (x: number) => area.x + x * area.w;
  const py = (y: number) => area.y + y * area.h;
  const rect = (x: number, y: number, w: number, h: number, fill: string) => {
    ctx.fillStyle = fill;
    ctx.fillRect(x, y, w, h);
  };
  const line = (
    x1: number,
    y1: number,
    x2: number,
    y2: number,
    stroke: string,
    weight = 1,
  ) => {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.strokeStyle = stroke;
    ctx.lineWidth = weight;
    ctx.stroke();
  };

  rect(area.x, area.y, area.w, area.h, '#f0f4f9');
  for (let i = 0; i <= map.cols; i += 1) {
    const x = area.x + (i / map.cols) * area.w;
    line(x, area.y, x, area.y + area.h, '#e1e8f0');
  }
  for (let i = 0; i <= map.rows; i += 1) {
    const y = area.y + (i / map.rows) * area.h;
    line(area.x, y, area.x + area.w, y, '#e1e8f0');
  }

  const cellW = area.w / map.cols;
  const cellH = area.h / map.rows;

  if (stage !== 'pose') {
    map.cells.forEach((cell) => {
      if (progress <= 0 || cell.reveal > progress + 1e-9) return;
      const x = px(cell.x - 0.5 / map.cols);
      const y = py(cell.y - 0.5 / map.rows);
      if (stage === 'surface') {
        const first = SURFACE_COLORS[(cell.col + cell.row) % SURFACE_COLORS.length];
        const second = SURFACE_COLORS[(cell.col + cell.row + 1) % SURFACE_COLORS.length];
        ctx.beginPath();
        ctx.moveTo(x + 1, y + 1);
        ctx.lineTo(x + cellW - 1, y + 1);
        ctx.lineTo(x + 1, y + cellH - 1);
        ctx.closePath();
        ctx.fillStyle = first;
        ctx.fill();
        ctx.beginPath();
        ctx.moveTo(x + cellW - 1, y + 1);
        ctx.lineTo(x + cellW - 1, y + cellH - 1);
        ctx.lineTo(x + 1, y + cellH - 1);
        ctx.closePath();
        ctx.fillStyle = second;
        ctx.fill();
        line(
          x + 1,
          y + 1,
          x + cellW - 1,
          y + cellH - 1,
          'rgba(104, 36, 195, 0.42)',
          0.9,
        );
      } else {
        const t = clamp(cell.clearance / 0.21, 0, 1);
        const shade =
          t < 0.2
            ? DISTANCE_COLORS[0]
            : t < 0.4
              ? DISTANCE_COLORS[1]
              : t < 0.65
                ? DISTANCE_COLORS[2]
                : t < 0.85
                  ? DISTANCE_COLORS[3]
                  : DISTANCE_COLORS[4];
        rect(x + 0.7, y + 0.7, cellW - 1.4, cellH - 1.4, shade);
        if (t > 0.4 && (cell.col + cell.row) % 2 === 0) {
          ctx.fillStyle = '#00839b';
          ctx.globalAlpha = 0.3;
          ctx.beginPath();
          ctx.arc(px(cell.x), py(cell.y), 1.4, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = 1;
        }
      }
    });
  }

  ctx.strokeStyle = '#a8b7c7';
  ctx.lineWidth = 3;
  ctx.strokeRect(area.x, area.y, area.w, area.h);

  const obstacles = obstaclesForRoom(map.room);

  obstacles.forEach((obstacle, index) => {
    rect(
      px(obstacle.x),
      py(obstacle.y) + 5,
      obstacle.w * area.w,
      obstacle.h * area.h,
      '#d4dee9',
    );
    rect(
      px(obstacle.x),
      py(obstacle.y),
      obstacle.w * area.w,
      obstacle.h * area.h,
      index === 1 ? '#e9def9' : '#e0e8f1',
    );
    line(
      px(obstacle.x),
      py(obstacle.y),
      px(obstacle.x + obstacle.w),
      py(obstacle.y),
      '#acbdd0',
      2,
    );
    line(
      px(obstacle.x),
      py(obstacle.y),
      px(obstacle.x),
      py(obstacle.y + obstacle.h),
      '#acbdd0',
      2,
    );
  });

  const routeLength = map.lengths[map.lengths.length - 1] || 0;

  ctx.beginPath();
  map.route.forEach((point, index) => {
    if (index === 0) ctx.moveTo(px(point.x), py(point.y));
    else ctx.lineTo(px(point.x), py(point.y));
  });
  ctx.setLineDash([2, 7]);
  ctx.strokeStyle = 'rgba(99, 115, 129, 0.12)';
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.setLineDash([]);

  if (progress > 0 && map.route.length > 0) {
    ctx.beginPath();
    ctx.moveTo(px(map.route[0].x), py(map.route[0].y));
    for (
      let index = 1;
      index < map.route.length && map.lengths[index] <= routeLength * progress;
      index += 1
    ) {
      ctx.lineTo(px(map.route[index].x), py(map.route[index].y));
    }
    const end = routeAt(map, progress);
    ctx.lineTo(px(end.x), py(end.y));
    ctx.strokeStyle = stage === 'pose' ? BLUE : withAlpha(color, 0.42);
    ctx.lineWidth = stage === 'pose' ? 2.7 : 1.6;
    ctx.stroke();

    if (stage === 'pose') {
      map.cells.forEach((cell, index) => {
        if (cell.reveal > progress + 1e-9) return;
        if (index % 3 !== 0) return;
        rect(
          px(cell.x) - 2,
          py(cell.y) - 2,
          4,
          4,
          index % 9 === 0 ? PURPLE : BLUE,
        );
      });
    }

    ctx.fillStyle = color;
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(px(end.x), py(end.y), 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }

  const patrol =
    progress > 0 && !standby
      ? Math.min(0.012, progress) * ((1 + Math.sin(time * 1.3)) / 2)
      : 0;
  const robotPosition = routeAt(map, Math.max(0, progress - patrol));
  const ahead = routeAt(map, Math.min(1, Math.max(0, progress - patrol) + 0.003));
  const robotAngle = Math.atan2(
    ahead.y - robotPosition.y,
    ahead.x - robotPosition.x,
  );

  const rx = px(robotPosition.x);
  const ry = py(robotPosition.y);
  const sweep =
    target && time < targetUntil
      ? Math.atan2(py(target.y) - ry, px(target.x) - rx)
      : standby
        ? -Math.PI / 2 + Math.sin(time * 0.5) * 0.25
        : time * 0.62;

  const contacts: Array<[number, number]> = [];
  for (let index = 0; index < 32; index += 1) {
    const angle = sweep + (index / 31 - 0.5) * (standby ? 0.5 : 1.3);
    let x = robotPosition.x;
    let y = robotPosition.y;
    for (let distance = 0.006; distance <= 1.6; distance += 0.008) {
      x = robotPosition.x + Math.cos(angle) * distance;
      y = robotPosition.y + (Math.sin(angle) * distance * area.w) / area.h;
      if (
        x <= 0 ||
        x >= 1 ||
        y <= 0 ||
        y >= 1 ||
        obstacles.some(
          (obstacle) =>
            x >= obstacle.x &&
            x <= obstacle.x + obstacle.w &&
            y >= obstacle.y &&
            y <= obstacle.y + obstacle.h,
        )
      ) {
        break;
      }
    }
    x = clamp(x, 0, 1);
    y = clamp(y, 0, 1);
    contacts.push([px(x), py(y)]);
    if (index % 4 === 0) {
      ctx.globalAlpha = 0.12;
      line(rx, ry, px(x), py(y), color);
      ctx.globalAlpha = 1;
    }
  }

  ctx.globalAlpha = 0.05;
  ctx.beginPath();
  ctx.moveTo(rx, ry);
  contacts.forEach(([x, y]) => ctx.lineTo(x, y));
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  ctx.globalAlpha = 1;

  contacts.forEach(([x, y], index) => {
    if (index % 2 !== 0) return;
    rect(x - 1.7, y - 1.7, 3.4, 3.4, index % 7 === 0 ? PURPLE : color);
  });

  if (target && time < targetUntil) {
    const tx = px(target.x);
    const ty = py(target.y);
    const pulse = 4 + (Math.sin(time * 3) + 1) * 3;
    ctx.strokeStyle = 'rgba(142, 51, 255, 0.28)';
    ctx.lineWidth = 1;
    ctx.strokeRect(tx - pulse, ty - pulse, pulse * 2, pulse * 2);
    line(tx - 9, ty, tx + 9, ty, PURPLE, 1.4);
    line(tx, ty - 9, tx, ty + 9, PURPLE, 1.4);
  }

  const scale = clamp(Math.min(area.w, area.h) / 280, 0.82, 1.3);
  ctx.save();
  ctx.translate(rx, ry);
  ctx.rotate(
    Math.atan2(
      Math.sin(robotAngle) * area.h,
      Math.cos(robotAngle) * area.w,
    ),
  );
  rect(-13 * scale, -12 * scale, 26 * scale, 24 * scale, withAlpha(color, 0.13));
  rect(-10 * scale, -13 * scale, 6 * scale, 4 * scale, '#454f5b');
  rect(-10 * scale, 9 * scale, 6 * scale, 4 * scale, '#454f5b');
  rect(4 * scale, -13 * scale, 6 * scale, 4 * scale, '#454f5b');
  rect(4 * scale, 9 * scale, 6 * scale, 4 * scale, '#454f5b');
  rect(-12 * scale, -9 * scale, 24 * scale, 18 * scale, color);
  rect(-7 * scale, -5 * scale, 12 * scale, 10 * scale, '#fff');
  rect(8 * scale, -4 * scale, 6 * scale, 8 * scale, CYAN);
  rect(-4 * scale, -2 * scale, 5 * scale, 4 * scale, PURPLE);
  if (stage === 'surface') {
    line(-6 * scale, -4 * scale, 4 * scale, 4 * scale, PURPLE, 1.4);
    line(-6 * scale, 4 * scale, 4 * scale, -4 * scale, PURPLE, 1.4);
  }
  if (stage === 'distance') {
    ctx.strokeStyle = CYAN;
    ctx.lineWidth = 1;
    ctx.strokeRect(-5 * scale, -4 * scale, 7 * scale, 7 * scale);
  }
  ctx.restore();

  ctx.fillStyle = MUTED;
  return area;
}

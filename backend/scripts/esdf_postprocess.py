#!/usr/bin/env python3
"""把 Voxblox 导出的 ASCII PLY 转成 XY/XZ/YZ 三张切片 PNG。

PLY 字段格式（由 voxel_points_to_esdf.cpp 导出）：
  x y z distance red green blue
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def load_ply_data(path: Path) -> np.ndarray:
    """读取 ASCII PLY（只处理我们自己导出的格式）。"""
    with path.open("r", encoding="utf-8") as fh:
        while True:
            line = fh.readline()
            if not line:
                raise ValueError("PLY 文件头不完整")
            if line.strip() == "end_header":
                break
        # 读取所有数据行（忽略末尾空行）
        data = np.loadtxt(fh, dtype=np.float64, ndmin=2)
    if data.shape[0] == 0 or data.shape[1] != 7 or not np.isfinite(data).all():
        raise ValueError("Empty, invalid or nonfinite ESDF preview")
    return data


def render_slice(
    u: np.ndarray, v: np.ndarray, d: np.ndarray,
    out_png: Path, res: int, d_min: float, d_max: float
) -> dict | None:
    """把 (u,v) 散点投影到 res×res 网格，颜色按 distance 映射：红近蓝远。"""
    u_min, u_max = float(u.min()), float(u.max())
    v_min, v_max = float(v.min()), float(v.max())
    span = max(u_max - u_min, v_max - v_min)
    if span < 1e-6:
        return None

    # 归一化到 0..res-1
    px = ((u - u_min) / span * (res - 1)).astype(int)
    py = ((v - v_min) / span * (res - 1)).astype(int)
    px = np.clip(px, 0, res - 1)
    py = np.clip(py, 0, res - 1)

    # 距离 → 颜色
    norm = np.clip((d - d_min) / max(d_max - d_min, 1e-6), 0, 1)
    r = (255 * (1.0 - norm)).astype(np.uint8)
    b = (255 * norm).astype(np.uint8)
    g = np.zeros_like(r)

    # 全白背景，逐点覆盖
    img = np.full((res, res, 3), 255, dtype=np.uint8)
    img[py, px] = np.stack([r, g, b], axis=-1)

    # 图像 y 轴翻转（工程习惯：y 朝上）
    img = np.flipud(img)
    Image.fromarray(img).save(out_png)

    return {
        "file": out_png.name,
        "u_range": [u_min, u_max],
        "v_range": [v_min, v_max],
        "distance_range": [float(d_min), float(d_max)],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_ply", required=True, type=Path)
    parser.add_argument("--output_dir", required=True, type=Path)
    parser.add_argument("--resolution", type=int, default=480)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[postprocess] 读取 {args.input_ply}")
    data = load_ply_data(args.input_ply)
    print(f"[postprocess] 共 {data.shape[0]} 点, {data.shape[1]} 列")

    if data.shape[1] < 7:
        raise ValueError(f"PLY 至少 7 列 (x y z distance r g b)，实际 {data.shape[1]}")

    xs, ys, zs, dist = data[:, 0], data[:, 1], data[:, 2], data[:, 3]
    d_min, d_max = -1.5, 1.5  # Fixed signed meter legend; matches declared preview window.
    print(f"[postprocess] distance 范围: [{d_min:.3f}, {d_max:.3f}]")

    planes = {
        "xy": (xs, ys, zs),
        "xz": (xs, zs, ys),
        "yz": (ys, zs, xs),
    }

    meta = {}
    for name, (u_all, v_all, w_all) in planes.items():
        w_center = float(np.median(w_all))
        thickness = 0.1  # 切片厚度
        mask = np.abs(w_all - w_center) < thickness
        if mask.sum() < 50:
            print(f"[postprocess] {name} 切片点数太少，跳过")
            continue
        print(f"[postprocess] {name} 切片 {mask.sum()} 点")
        out_png = args.output_dir / f"slice_{name}.png"
        order = np.argsort(-np.abs(w_all[mask] - w_center), kind="stable")
        info = render_slice(
            u_all[mask][order], v_all[mask][order], dist[mask][order],
            out_png, args.resolution, d_min, d_max
        )
        if info:
            info.update(normal_axis={"xy":"z","xz":"y","yz":"x"}[name], center_m=w_center, half_thickness_m=thickness, sampled_points=int(mask.sum()), unit="meter", unknown_color="white", preview_abs_distance_max_m=1.5)
            meta[name] = info

    (args.output_dir / "slices_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    print(f"[postprocess] 完成，生成 {len(meta)} 张切片")


if __name__ == "__main__":
    main()
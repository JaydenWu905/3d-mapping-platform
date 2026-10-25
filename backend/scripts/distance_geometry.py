"""Small-input reference of coordinate/weight contracts, NOT an ESDF algorithm.

No interpolation, distance conversion, sign invention, or unknown-space filling.
"""
from dataclasses import dataclass
import heapq
import math


@dataclass(frozen=True)
class Sample:
    point: tuple[float, float, float]
    sdf_m: float
    weight: float
    level: int = 0


def positive(h):
    if not math.isfinite(h) or h <= 0:
        raise ValueError('voxel size must be finite and positive')


def target_index(point, h):
    """Voxblox containment index; does not assert the sample is at its center."""
    positive(h)
    if len(point) != 3 or not all(map(math.isfinite, point)):
        raise ValueError('nonfinite/invalid point')
    return tuple(math.floor(x / h + 1e-6) for x in point)


def target_center(index, h):
    positive(h)
    return tuple((i + .5) * h for i in index)


def center_index(point, h):
    positive(h)
    if len(point) != 3 or not all(map(math.isfinite, point)):
        raise ValueError('nonfinite/invalid point')
    index = tuple(math.floor(x / h) for x in point)
    if any(abs(x / h - (i + .5)) > 1e-3 for x, i in zip(point, index)):
        raise ValueError('explicit resampling required; do not shift native samples')
    return index


def canonical_samples(samples, source_h, target_h):
    positive(source_h); positive(target_h)
    if not math.isclose(source_h, target_h, rel_tol=1e-6):
        raise ValueError('different resolutions require resampling policy')
    result = {}
    for sample in samples:
        if sample.level != 0:
            raise ValueError('mixed/coarse levels require extent metadata and resampling')
        if not all(map(math.isfinite, (*sample.point, sample.sdf_m, sample.weight))) or sample.weight <= 0:
            raise ValueError('nonfinite or nonpositive weight')
        if sample.weight < 2:
            continue
        index = center_index(sample.point, target_h)
        if index in result:
            raise ValueError('duplicate target voxel; aggregation policy required')
        result[index] = sample
    if not result:
        raise ValueError('empty input or no samples survive weight >= 2')
    # Absence from this dictionary remains UNKNOWN, never distance=0/free.
    return result


def graph_shortest_paths(seeds, edges):
    """Reference queue regression only; weights are graph costs, not metric ESDF."""
    best = dict(seeds); queue = [(d, i) for i,d in best.items()]; heapq.heapify(queue)
    while queue:
        distance, index = heapq.heappop(queue)
        if distance > best[index]: continue
        for neighbor, step in edges.get(index, []):
            candidate = distance + step
            if neighbor not in seeds and candidate < best.get(neighbor, math.inf):
                best[neighbor] = candidate; heapq.heappush(queue, (candidate, neighbor))
    return best

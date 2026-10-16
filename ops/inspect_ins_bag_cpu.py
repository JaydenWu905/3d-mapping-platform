#!/usr/bin/env python3
"""Read ROS1 bag metadata and a few Livox records; never publish messages."""
from pathlib import Path
from rosbags.highlevel import AnyReader

BAG = Path('/root/autodl-tmp/INS/2024-06-04-16-24-55.bag')
TOPIC = '/livox_mid360/livox/lidar'

with AnyReader([BAG]) as reader:
    for conn in reader.connections:
        print(f'CONNECTION\t{conn.topic}\t{conn.msgtype}\t{conn.msgcount}')
    lidar = [conn for conn in reader.connections if conn.topic == TOPIC]
    for number, (conn, record_ns, raw) in enumerate(reader.messages(connections=lidar), 1):
        msg = reader.deserialize(raw, conn.msgtype)
        stamp = msg.header.stamp
        offsets = [point.offset_time for point in msg.points]
        first = msg.points[0] if msg.points else None
        print(f'FRAME\t{number}\trecord_ns={record_ns}\theader_ns={stamp.sec * 1000000000 + stamp.nanosec}'
              f'\tframe_id={msg.header.frame_id}\ttimebase={msg.timebase}'
              f'\tpoint_num={msg.point_num}\tactual_points={len(msg.points)}'
              f'\toffset_min={min(offsets) if offsets else None}'
              f'\toffset_max={max(offsets) if offsets else None}'
              f'\tfirst_xyz={tuple((first.x, first.y, first.z)) if first else None}'
              f'\tfirst_reflectivity={first.reflectivity if first else None}'
              f'\tfirst_offset_time={first.offset_time if first else None}')
        if number >= 3:
            break

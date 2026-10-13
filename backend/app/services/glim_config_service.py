"""GLIM configuration materialisation and command construction.

GLIM reads JSON files that contain C-style comments.  The platform must not
require an operator to hand-edit a server config for every dataset, so this
module:

1. parses the comment-tolerant JSON;
2. overlays the dataset's sensor parameters (topics, frame ids, ``acc_scale``,
   ``T_lidar_imu``, per-point time settings) from the dataset registry;
3. writes a *plain* JSON effective config next to an untouched copy of the
   registered config, so a run can always be reproduced and audited.

Everything here is pure Python: the command/environment builders are unit
tested without ROS2, CUDA or a GPU.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping


class GlimConfigError(ValueError):
    pass


#: Config files the platform knows how to overlay, keyed by the JSON section.
CONFIG_SECTIONS: dict[str, str] = {
    "config_ros.json": "glim_ros",
    "config_sensors.json": "sensors",
}

#: Extension modules that need a display; reported (never silently rewritten).
DISPLAY_DEPENDENT_MODULES = ("viewer", "rviz", "glfw", "x11")


def strip_json_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments without touching string literals."""
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    escaped = False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def load_jsonc(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GlimConfigError(f"cannot read GLIM config {path}: {exc}") from exc
    stripped = strip_json_comments(text)
    # Tolerate a trailing comma before a closing brace/bracket.
    compact: list[str] = []
    index = 0
    while index < len(stripped):
        char = stripped[index]
        if char == ",":
            look = index + 1
            while look < len(stripped) and stripped[look] in " \t\r\n":
                look += 1
            if look < len(stripped) and stripped[look] in "}]":
                index += 1
                continue
        compact.append(char)
        index += 1
    try:
        data = json.loads("".join(compact))
    except ValueError as exc:
        raise GlimConfigError(f"GLIM config {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GlimConfigError(f"GLIM config {path} must contain a JSON object")
    return data


def build_overrides(spec: Mapping[str, Any], *, points_topic: str, imu_topic: str) -> dict[str, Any]:
    """Translate dataset sensor parameters into ``{file: {section: {key: value}}}``."""
    ros: dict[str, Any] = {
        "points_topic": points_topic,
        "imu_topic": imu_topic,
    }
    for source, target in (
        ("lidar_frame_id", "lidar_frame_id"),
        ("imu_frame_id", "imu_frame_id"),
        ("acc_scale", "acc_scale"),
    ):
        if spec.get(source) is not None:
            ros[target] = spec[source]
    sensors: dict[str, Any] = {}
    if spec.get("T_lidar_imu") is not None:
        sensors["T_lidar_imu"] = list(spec["T_lidar_imu"])
    if spec.get("perpoint_relative_time") is not None:
        sensors["perpoint_relative_time"] = bool(spec["perpoint_relative_time"])
    if spec.get("perpoint_time_scale") is not None:
        sensors["perpoint_time_scale"] = float(spec["perpoint_time_scale"])
    return {"config_ros.json": {"glim_ros": ros}, "config_sensors.json": {"sensors": sensors}}


def merge_overrides(base: Mapping[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge two ``{file: {section: {key: value}}}`` override maps."""
    merged: dict[str, Any] = {file: {section: dict(values) for section, values in sections.items()}
                              for file, sections in base.items()}
    for file, sections in (extra or {}).items():
        target_file = merged.setdefault(file, {})
        if not isinstance(sections, dict):
            raise GlimConfigError(f"config_overrides.{file} must map sections to key/value objects")
        for section, values in sections.items():
            if not isinstance(values, dict):
                raise GlimConfigError(f"config_overrides.{file}.{section} must be an object")
            target_file.setdefault(section, {}).update(values)
    return merged


def materialize_config(
    registered_dir: Path,
    destination: Path,
    overrides: Mapping[str, Any],
    *,
    registered_copy: Path | None = None,
) -> dict[str, Any]:
    """Copy the registered GLIM config and write an effective, plain-JSON version."""
    if not registered_dir.is_dir():
        raise GlimConfigError(f"GLIM config directory is missing: {registered_dir}")
    if registered_copy is not None:
        if registered_copy.exists():
            shutil.rmtree(registered_copy)
        shutil.copytree(registered_dir, registered_copy)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(registered_dir, destination)

    applied: list[dict[str, Any]] = []
    for file_name, sections in overrides.items():
        path = destination / file_name
        if not path.is_file():
            raise GlimConfigError(
                f"registered GLIM config has no {file_name}; cannot apply pose overrides "
                "(the dataset registry must point at a complete GLIM config directory)"
            )
        data = load_jsonc(path)
        for section, values in sections.items():
            if section not in data or not isinstance(data[section], dict):
                raise GlimConfigError(f"GLIM config {file_name} has no '{section}' section")
            for key, value in values.items():
                applied.append({
                    "file": file_name, "section": section, "key": key,
                    "previous": data[section].get(key), "value": value,
                })
                data[section][key] = value
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "registered": str(registered_dir),
        "effective": str(destination),
        "registered_copy": str(registered_copy) if registered_copy else None,
        "applied": applied,
    }
    summary["headless_warnings"] = headless_warnings(destination)
    return summary


def headless_warnings(config_dir: Path) -> list[str]:
    """Report display-dependent extension modules; never rewrite them silently."""
    warnings: list[str] = []
    path = config_dir / "config_ros.json"
    if not path.is_file():
        return warnings
    try:
        data = load_jsonc(path)
    except GlimConfigError:
        return warnings
    modules = (data.get("glim_ros") or {}).get("extension_modules") or []
    for module in modules:
        if any(token in str(module).lower() for token in DISPLAY_DEPENDENT_MODULES):
            warnings.append(
                f"config_ros.json loads display-dependent module '{module}'; confirm it starts "
                "headless on this machine (the verified AutoDL config avoids standard_viewer)"
            )
    return warnings


def _format_param(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_ros_node_args(
    config_path: Path,
    *,
    node_params: Mapping[str, Any] | None = None,
    dump_on_unload: bool = True,
) -> list[str]:
    """The ``--ros-args -p k:=v ...`` argument vector for the GLIM node."""
    args = ["--ros-args"]
    params: dict[str, Any] = {"config_path": str(config_path),
                              "dump_on_unload": dump_on_unload}
    for key, value in (node_params or {}).items():
        params[str(key)] = value
    for key, value in params.items():
        args.extend(["-p", f"{key}:={_format_param(value)}"])
    return args


def build_node_argv(node_command: str, args: list[str]) -> list[str]:
    """The node command and its arguments, for audit/reporting only.

    ``node_command`` may contain shell syntax (the default resolves the GLIM
    prefix through ``ros2 pkg prefix``), so this list is *not* executed
    directly: the shell payload built by :func:`build_glim_shell` is.
    """
    if not node_command.strip():
        raise GlimConfigError("runtime.glim.node_command is empty")
    return [node_command, *args]


def build_ros_runtime_shell(
    ros_setup: str,
    ld_library_path: str,
    target: str,
    args: Iterable[str] = (),
    *,
    quote_target: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> str:
    """The one ``bash -lc`` payload used for GLIM *and* the bridge.

    Order matters and is fixed here (docs/ins-glim-dataset-profile.md §9):

    ``source`` the ROS2 environment **first**, then override
    ``LD_LIBRARY_PATH``, then unset ``OMP_NUM_THREADS``, then ``exec`` the real
    program.  Prepending the GTSAM path to the inherited process environment
    would not survive ``setup.bash``, which prepends ROS's own GTSAM 4.2 path and
    re-triggers ``undefined symbol: gtsam::NonlinearFactor::rekey(...)``.

    ``exec`` makes ``target`` the direct child of the adapter, so the process the
    supervisor holds is the real GLIM node (or the real bridge Python) and no
    wrapper is involved.
    """
    if not target.strip():
        raise GlimConfigError("ROS runtime shell target is empty")
    quoted_args = " ".join(_shell_quote(part) for part in args)
    if quote_target:
        rendered_target = f'"{target}"' if target.startswith("$(") else _shell_quote(target)
    else:
        rendered_target = target
    payload = (
        f"source {_shell_quote(ros_setup)}"
        f" && export LD_LIBRARY_PATH={_shell_quote(ld_library_path)}:${{LD_LIBRARY_PATH:-}}"
        " && unset OMP_NUM_THREADS"
    )
    for key, value in (extra_env or {}).items():
        payload += f" && export {key}={_shell_quote(value)}"
    return f"{payload} && exec {rendered_target} {quoted_args}".rstrip()


def build_glim_shell(
    ros_setup: str,
    ld_library_path: str,
    node_command: str,
    args: list[str],
    *,
    extra_env: Mapping[str, str] | None = None,
    quote_node_command: bool | None = None,
) -> str:
    """ROS runtime shell that execs the real ``glim_rosnode``."""
    if not node_command.strip():
        raise GlimConfigError("runtime.glim.node_command is empty")
    if quote_node_command is None:
        # A single command word (path or ``$(ros2 pkg prefix …)/…`` template) is
        # quoted; a multi-word operator command must stay verbatim.
        quote_node_command = " " not in node_command.strip()
    return build_ros_runtime_shell(
        ros_setup, ld_library_path, node_command, args,
        quote_target=quote_node_command, extra_env=extra_env,
    )


def build_bridge_shell(ros_setup: str, ld_library_path: str, argv: list[str]) -> str:
    """ROS runtime shell that execs the bridge through the rosbags interpreter.

    The bridge imports ``rclpy`` and ``sensor_msgs`` itself, so it needs the same
    sourced ROS2 environment as GLIM; the adapter must not assume that whoever
    started the platform already sourced it.
    """
    if not argv:
        raise GlimConfigError("bridge command is empty")
    return build_ros_runtime_shell(ros_setup, ld_library_path, argv[0], argv[1:],
                                   quote_target=True)


def build_prefix_probe_shell(ros_setup: str, ld_library_path: str,
                             package: str = "glim_ros") -> str:
    """Best-effort ``ros2 pkg prefix`` probe, in the same ROS runtime semantics."""
    return build_ros_runtime_shell(
        ros_setup, ld_library_path, "ros2", ["pkg", "prefix", package],
        quote_target=False,
    )


def _shell_quote(value: str) -> str:
    return "'" + str(value).replace("'", "'\\''") + "'"


def build_ros_env(base_env: Mapping[str, str]) -> dict[str, str]:
    """Process environment for the ROS runtime shells.

    ``LD_LIBRARY_PATH`` is deliberately NOT touched here: it is overridden
    *inside* the shell, after ``source`` (see :func:`build_ros_runtime_shell`).
    ``OMP_NUM_THREADS`` is dropped here as well as unset in the shell so an
    inherited value from the platform process cannot leak in.
    """
    env = dict(base_env)
    env.pop("OMP_NUM_THREADS", None)
    return env


def build_bridge_argv(
    python: Path,
    script: Path,
    *,
    bag: Path,
    lidar_topic: str,
    imu_topic: str,
    points_out: str,
    imu_out: str,
    lidar_frame: str,
    imu_frame: str,
    bag_index: Path,
    playback_rate: float,
    max_lidar_frames: int | None = None,
    max_duration_sec: float | None = None,
) -> list[str]:
    argv = [
        str(python), str(script),
        "--bag", str(bag),
        "--lidar-topic", lidar_topic,
        "--imu-topic", imu_topic,
        "--points-out", points_out,
        "--imu-out", imu_out,
        "--lidar-frame", lidar_frame,
        "--imu-frame", imu_frame,
        "--bag-index", str(bag_index),
        "--rate", str(playback_rate),
    ]
    if max_lidar_frames:
        argv.extend(["--max-lidar-frames", str(int(max_lidar_frames))])
    if max_duration_sec:
        argv.extend(["--max-duration-sec", str(max_duration_sec)])
    return argv

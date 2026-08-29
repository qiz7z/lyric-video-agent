# -*- coding: utf-8 -*-
"""视频检查工具：ffprobe 探测 + 抽帧（供视觉 QC / 人工终审）。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .audio import get_ffmpeg


def probe_video(path: str) -> dict:
    ff = get_ffmpeg()
    r = subprocess.run(
        [ff, "-i", path, "-hide_banner"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    info = {"path": path, "streams": []}
    for line in r.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            info["duration"] = round(int(h) * 3600 + int(m) * 60 + float(s), 2)
        if ", video:" in line or line.startswith("Stream") and "Video:" in line:
            info["streams"].append(line)
        if "Streams:" in line or "Audio:" in line and line.startswith("Stream"):
            info["streams"].append(line)
    return info


def extract_frames(video: str, times: list[float], outdir: str,
                   prefix: str = "frame") -> list[str]:
    """按给定时间点抽帧为 PNG，返回路径列表。"""
    ff = get_ffmpeg()
    Path(outdir).mkdir(parents=True, exist_ok=True)
    outs = []
    for i, t in enumerate(times, 1):
        out = str(Path(outdir) / f"{prefix}_{i:03d}_{int(t)}s.png")
        r = subprocess.run(
            [ff, "-y", "-ss", str(t), "-i", video, "-frames:v", "1", out],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and Path(out).exists() and Path(out).stat().st_size > 1000:
            outs.append(out)
    return outs

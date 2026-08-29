# -*- coding: utf-8 -*-
"""ffmpeg 合成：正式片（xfade 拼接 + 烧字幕 + 原曲立体声）与验证片（黑底白字）。

要点（全部来自实战脚本泛化）：
- 段覆盖公式：N×DUR-(N-1)×XF >= 总时长（planner 按此定段数）；
- xfade=fade 0.3s + tpad 尾部 clone 兜底 + -shortest 裁齐；
- 字幕烧录用 subtitles=ASS（相对路径 + cwd=workdir，避免 Windows 盘符转义坑）；
- 编码优先 h264_nvenc（本机 GPU），失败自动回退 libx264；
- 音频用原曲立体声（SOP：不写 -ac 1）。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .audio import get_ffmpeg


def _run(cmd: list[str], cwd: str) -> None:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-600:]}")


def _encode_args(encoder: str, cq: int) -> list[str]:
    if encoder == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", str(cq)]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(cq)]


def _swap_encoder(cmd: list[str], cq: int) -> list[str]:
    """把命令里的 NVENC 参数块整体替换为 libx264 参数块。"""
    nvenc_value_flags = ("-preset", "-rc", "-cq")
    out, i = [], 0
    while i < len(cmd):
        a = cmd[i]
        if a == "h264_nvenc":
            out.extend(["-c:v", "libx264", "-preset", "medium", "-crf", str(cq)])
            i += 1
            while i < len(cmd):
                if cmd[i] in ("p1", "vbr"):                 # 无值参数
                    i += 1
                elif cmd[i] in nvenc_value_flags:           # 带值参数，连同值跳过
                    i += 2
                else:
                    break
            continue
        out.append(a)
        i += 1
    return out


def _encode_with_fallback(cmd: list[str], cwd: str, cq: int) -> None:
    """NVENC 失败（驱动/显存/无卡）时回退 libx264 重跑。"""
    try:
        _run(cmd, cwd)
    except RuntimeError as e:
        if "h264_nvenc" not in " ".join(cmd):
            raise
        print(f"NVENC 失败（{str(e)[:120]}），回退 libx264 重跑...")
        _run(_swap_encoder(cmd, cq), cwd)


def clip_count_for(duration: float, dur: float = 15.06, xf: float = 0.3,
                   tail: float = 2.0) -> int:
    """按覆盖公式求最小段数：N×DUR-(N-1)×XF >= duration+tail。"""
    n = 1
    while n * dur - (n - 1) * xf < duration + tail:
        n += 1
    return n


def compose_verify(audio: str, ass_path: str, out: str, workdir: str,
                   fps: int = 30, encoder: str = "nvenc", cq: int = 20) -> str:
    """验证版：黑底 1920x1080 + 白字字幕 + 原曲（供听感确认，便宜可重渲）。"""
    filt = (f"color=c=black:s=1920x1080:r={fps},format=yuv420p,"
            f"subtitles={Path(ass_path).name}[v]")
    cmd = [get_ffmpeg(), "-y", "-f", "lavfi", "-i", f"color=c=black:s=1920x1080:r={fps}",
           "-i", audio, "-filter_complex", filt, "-map", "[v]", "-map", "1:a",
           *_encode_args(encoder, cq), "-r", str(fps), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", str(Path(out).name)]
    _encode_with_fallback(cmd, workdir, cq)
    return out


def compose_final(clips: list[str], audio: str, ass_path: str, out: str, workdir: str,
                  dur: float = 15.06, xf: float = 0.3, fps: int = 30,
                  encoder: str = "nvenc", cq: int = 20) -> str:
    """正式版：N 段 xfade + 烧 ASS + 原曲立体声。clips 缺失/过小直接报错（续跑保护）。"""
    n = len(clips)
    for c in clips:
        if not (Path(c).exists() and Path(c).stat().st_size > 500_000):
            raise RuntimeError(f"片段缺失/异常: {c}")
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", c]
    inputs += ["-i", audio]

    pre = [f"[{i}:v]trim=duration={dur},setpts=PTS-STARTPTS,"
           f"scale=1920:1088:force_original_aspect_ratio=increase,"
           f"crop=1920:1080,settb=AVTB,fps={fps}[v{i}]" for i in range(n)]
    filters = pre[:]
    prev = "v0"
    for i in range(1, n):
        off = i * (dur - xf)
        out_label = f"x{i}" if i < n - 1 else "vout"
        filters.append(f"[{prev}][v{i}]xfade=transition=fade:duration={xf}:offset={off:.3f}[{out_label}]")
        prev = out_label
    filters.append("[vout]tpad=stop_mode=clone:stop_duration=2[vf]")

    total = n * dur - (n - 1) * xf
    cmd = [get_ffmpeg(), "-y"] + inputs + [
        "-filter_complex", ";".join(filters) + f";[vf]subtitles={Path(ass_path).name}[vsub]",
        "-map", "[vsub]", "-map", f"{n}:a",
        *_encode_args(encoder, cq), "-r", str(fps), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-shortest", str(Path(out).name)]
    print(f"正在合成正式视频（{n} 段，总时长≈{total:.1f}s）...")
    _encode_with_fallback(cmd, workdir, cq)
    size = os.path.getsize(Path(workdir) / Path(out).name) / 1024 / 1024
    print(f"已生成: {out} ({size:.1f} MB)")
    return out

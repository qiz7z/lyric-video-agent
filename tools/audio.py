# -*- coding: utf-8 -*-
"""音频工具：ffmpeg 定位 / 解码 / 探测，demucs 人声分离封装，RMS 能量包络。

demucs 分离是对齐质量的分水岭（SOP 2026-08-13 起的最优对齐法）：
  demucs -n htdemucs -> vocals.wav，对齐比全曲包络可靠得多。
封装要点：
  - 幂等续跑：vocals.wav 已存在直接复用（长音频分离不便宜）；
  - 设备自动选 cuda，失败降级 cpu；
  - demucs 未安装时抛 DemucsUnavailable，由上层决定降级策略。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


class DemucsUnavailable(RuntimeError):
    pass


def get_ffmpeg() -> str:
    """优先 imageio-ffmpeg 自带二进制（版本可控），其次系统 PATH。"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ff = shutil.which("ffmpeg")
        if not ff:
            raise RuntimeError("找不到 ffmpeg：请 pip install imageio-ffmpeg")
        return ff


def probe_duration(path: str) -> float:
    """ffprobe 读时长（秒）。"""
    ff = get_ffmpeg()
    pp = str(Path(ff).with_name(Path(ff).stem).with_suffix(""))  # ffmpeg-win-x86_64-v7.1
    probe = pp + "-probe.exe"
    if not os.path.exists(probe):
        # imageio-ffmpeg 只带 ffmpeg；用 ffmpeg -i 的 stderr 解析兜底
        r = subprocess.run([ff, "-i", path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        for line in r.stderr.splitlines():
            if "Duration:" in line:
                h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
        raise RuntimeError(f"无法探测时长: {path}")
    r = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return float(r.stdout.strip())


def decode_wav(src: str, dst: str, stereo: bool = True) -> str:
    """解码为 wav。SOP 提醒：源音频**不要**写 -ac 1（mono 陷阱会破坏立体声 mux）。"""
    ff = get_ffmpeg()
    cmd = [ff, "-y", "-i", src, "-vn"]
    if not stereo:
        cmd += ["-ac", "1"]
    cmd += [dst]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"解码失败: {r.stderr[-400:]}")
    return dst


def separate_vocals(audio_path: str, workdir: str, device: str = "auto",
                    model: str = "htdemucs") -> str:
    """demucs 人声分离，返回 vocals.wav 绝对路径。已存在则直接复用（续跑）。

    Returns
    -------
    str : vocals.wav 路径
    Raises
    ------
    DemucsUnavailable : demucs 未安装（上层可降级为全曲包络对齐）
    """
    out_dir = Path(workdir) / "separated"
    expected = out_dir / model / Path(Path(audio_path).stem).with_suffix("") / "vocals.wav"
    if expected.exists() and expected.stat().st_size > 100_000:
        return str(expected)

    try:
        import demucs.separate  # noqa: F401
    except ImportError as e:
        raise DemucsUnavailable(str(e)) from e

    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"

    out_dir.mkdir(parents=True, exist_ok=True)
    # Windows 下 PATH 不含 venv Scripts 目录，subprocess 找不到 demucs；
    # 依次尝试 venv 内 exe -> PATH -> python -m demucs
    exe = Path(sys.executable).parent / "demucs.exe"
    if exe.exists():
        cmd = [str(exe), "-n", model, "-d", device, "--shifts", "0",
               "-o", str(out_dir), audio_path]
    elif shutil.which("demucs"):
        cmd = ["demucs", "-n", model, "-d", device, "--shifts", "0",
               "-o", str(out_dir), audio_path]
    else:
        cmd = [sys.executable, "-m", "demucs", "-n", model, "-d", device,
               "--shifts", "0", "-o", str(out_dir), audio_path]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0 or not expected.exists():
        # cuda 跑挂（显存不足等）退 cpu 再试一次
        if device == "cuda":
            return separate_vocals(audio_path, workdir, device="cpu", model=model)
        raise RuntimeError(f"demucs 失败: {r.stderr[-500:]}")
    return str(expected)


def rms_envelope(wav_path: str, sr: int = 22050, hop: int = 512,
                 smooth: int = 11) -> tuple[np.ndarray, np.ndarray]:
    """RMS 能量包络（librosa，帧长 2048 / 帧移 512 / 11 帧滑动平均）。"""
    import librosa
    y, _ = librosa.load(wav_path, sr=sr, mono=True)
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
    rms = np.convolve(rms, np.ones(smooth) / smooth, mode="same")
    times = np.arange(len(rms)) * hop / sr
    return rms, times

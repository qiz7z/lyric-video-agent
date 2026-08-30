# -*- coding: utf-8 -*-
"""Agnes 图片生成客户端（agnes-image-2.x，/v1/images/generations）。

实测行为（2026-08-29 探测）：
- 同步返回 JSON：{data: [{url, b64_json(空), revised_prompt}], task_id}；
- size 传目标比例（如 1080x1440），模型按最近支持分辨率出图
  （实测 3:4 出 864x1152），调用方需自行 lanczos 放大到目标尺寸；
- 产物是 PNG URL，需二次下载。
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests


class ImageGen:
    def __init__(self, api_key: str, base_url: str = "https://apihub.agnes-ai.com/v1",
                 model: str = "agnes-image-2.1-flash", proxies: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.proxies = proxies or {}

    def generate(self, prompt: str, out_path: str, size: str = "1080x1440",
                 timeout: int = 180) -> str:
        """生成一张图并下载到 out_path，返回本地路径。失败抛异常（上层决定降级）。"""
        p = Path(out_path)
        if p.exists() and p.stat().st_size > 50_000:
            return str(p)                      # 幂等：已存在直接复用
        for attempt in range(5):
            try:
                r = requests.post(f"{self.base_url}/images/generations",
                                  headers=self.headers, timeout=timeout,
                                  proxies=self.proxies,
                                  json={"model": self.model, "prompt": prompt,
                                        "n": 1, "size": size})
                if r.status_code in (429, 503):
                    time.sleep(20 + attempt * 15)
                    continue
                r.raise_for_status()
                url = (r.json().get("data") or [{}])[0].get("url")
                if not url:
                    raise ValueError(f"无图片 URL: {str(r.json())[:200]}")
                img = requests.get(url, timeout=120, proxies=self.proxies)
                img.raise_for_status()
                if img.content[:4] not in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1"):
                    raise ValueError(f"非图片内容: {img.content[:8]!r}")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(img.content)
                return str(p)
            except Exception as e:
                print(f"  imagogen retry {attempt}: {type(e).__name__}: {str(e)[:120]}")
                time.sleep(5 + attempt * 5)
        raise RuntimeError(f"图片生成失败（5 次重试后）: {out_path}")


def scale_to(bg_path: str, out_path: str, w: int, h: int) -> str:
    """lanczos 放大 + 居中裁切到目标尺寸（图片模型返回尺寸与请求不一致的兜底）。"""
    from .audio import get_ffmpeg
    import subprocess
    # 相对路径一律先解析为绝对：调用方可能用任意 cwd（含 render_cover 的 cwd=workdir）
    bg_path = str(Path(bg_path).resolve())
    out_path = str(Path(out_path).resolve())
    cmd = [get_ffmpeg(), "-y", "-i", bg_path,
           "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
                  f"crop={w}:{h}",
           out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"scale 失败: {r.stderr[-300:]}")
    return out_path


def frame_to_vertical(frame_path: str, out_path: str, w: int = 1080, h: int = 1440) -> str:
    """横版视频帧 -> 竖版封面背景（居中裁切；图片模型不可用时的纯代码降级路径）。"""
    return scale_to(frame_path, out_path, w, h)

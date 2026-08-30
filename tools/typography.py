"""封面排版渲染：背景图 + 标题/署名 -> 竖版封面（纯代码，不经生成模型）。

设计判断（ARCHITECTURE §5.2）：**模型负责画面，代码负责文字**——
图像模型画中文几乎必乱码，标题/署名一律 ffmpeg drawtext + 本机中文字体渲染。

画布 1080x1440（3:4，抖音主页网格显示比例）；标题落在上部安全区。
drawtext 的 textfile 用相对路径 + cwd=workdir，绕开 Windows 盘符冒号转义坑
（与 subtitles 滤镜同一套路）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .audio import get_ffmpeg

W, H = 1080, 1440
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\STXINGKA.TTF",  # 华文行楷（项目默认）
    r"C:\Windows\Fonts\STXINWEI.TTF",  # 华文新魏
    r"C:\Windows\Fonts\msyh.ttc",
]  # 微软雅黑兜底


def find_font() -> str:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    raise RuntimeError("找不到可用中文字体（STXINGKA/STXINWEI/msyh）")


def render_cover(bg_path: str, title: str, subtitle: str, out_path: str, workdir: str) -> str:
    """合成封面：背景放大裁切到 3:4 -> 主标题（上 1/4，行楷大字描边）->
    署名（底部小字）。textfile 走相对路径避免转义。"""
    font = find_font()
    work = Path(workdir)
    work.mkdir(parents=True, exist_ok=True)
    title_f = work / "cover_title.txt"
    sub_f = work / "cover_sub.txt"
    title_f.write_text(title, encoding="utf-8")
    sub_f.write_text(subtitle, encoding="utf-8")

    # 背景统一处理成 1080x1440；cwd=work 执行 ffmpeg，输入必须是绝对路径
    # （相对路径会以 work 为基准双重拼接——实测踩坑）
    bg_std = (work / "cover_bg_std.png").resolve()
    from .imagogen import scale_to

    scale_to(bg_path, str(bg_std), W, H)

    title_size = 108 if len(title) <= 8 else (88 if len(title) <= 12 else 72)
    # Windows 滤镜转义重灾区：盘符冒号+反斜杠在 filtergraph 里极难逃干净。
    # 最稳解法：字体复制进工作区，用相对文件名（无冒号无反斜杠）。
    font_local = work / "cover_font.ttf"
    if not font_local.exists():
        import shutil

        shutil.copy(font, font_local)
    vf = (
        f"drawtext=fontfile=cover_font.ttf:textfile={title_f.name}"
        f":fontsize={title_size}:fontcolor=white:borderw=6:bordercolor=black@"
        f"0.85:shadowx=3:shadowy=4:shadowcolor=black@0.6"
        f":x=(w-text_w)/2:y=h*0.13,"
        f"drawtext=fontfile=cover_font.ttf:textfile={sub_f.name}"
        f":fontsize=44:fontcolor=white:borderw=4:bordercolor=black@"
        f"0.8:shadowx=2:shadowy=3:shadowcolor=black@0.5"
        f":x=(w-text_w)/2:y=h*0.88"
    )
    out = Path(out_path)
    cmd = [get_ffmpeg(), "-y", "-i", str(bg_std), "-vf", vf, "-frames:v", "1", str(out.name)]
    r = subprocess.run(
        cmd, cwd=str(work), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if r.returncode != 0:
        raise RuntimeError(f"封面合成失败: {r.stderr[-400:]}")
    return str(out)

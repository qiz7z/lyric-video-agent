# -*- coding: utf-8 -*-
"""ASS 字幕生成。

渲染策略（SOP 唯一权威，用户确认过"完美对应"）：
- 极简渲染：只 \\fad(150,180) 淡入淡出 + 永久 \\be1 柔光；
  绝对禁止 \\t 缩放/模糊/旋转动画——即使封在 fade 窗口内也会拉偏
  感知的出现/消失边界（v15/v17 教训）。
- 字体：华文行楷 STXingkai（书法味），备选 STXinwei/STLiti/FZSTK；
  ffmpeg 走 directwrite，中英文家族名都能加载。
- 两套：验证版（黑底白字 72）+ 正式版（黑字 84 + 浅米描边 &H00D7C8A0）。
"""
from __future__ import annotations

from pathlib import Path

OUTLINE_BEIGE = "&H00D7C8A0"   # 冷调浅米：比纯金含蓄（孤寂哀怨风配色验证过）

HEADER = (
    "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    "Style: Default,{font},{fontsize},{primary},&H000000FF,{outline},"
    "&H00000000,1,0,0,0,100,100,0,0,1,4,2,2,40,40,90,134\n\n"
    "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
)


def fmt(t: float) -> str:
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def build_ass(events: list[dict], primary: str, outline: str, fontsize: int,
              font: str = "STXingkai") -> str:
    lines = [HEADER.format(font=font, fontsize=fontsize, primary=primary, outline=outline)]
    for e in events:
        lines.append(
            f"Dialogue: 0,{fmt(e['start'])},{fmt(e['end'])},Default,,0,0,0,,"
            f"{{\\fad(150,180)}}{{\\be1}}{_escape(e['text'])}\n"
        )
    return "".join(lines)


def write_two_versions(events: list[dict], workdir: str,
                       font: str = "STXingkai") -> tuple[str, str]:
    """写验证版 + 正式版两套 ASS，返回路径。"""
    Path(workdir).mkdir(parents=True, exist_ok=True)
    v = build_ass(events, "&H00FFFFFF", OUTLINE_BEIGE, 72, font)   # 黑底视频用
    f = build_ass(events, "&H00000000", OUTLINE_BEIGE, 84, font)   # 纯风景画面用
    vp = f"{workdir}/lyrics_verify.ass"
    fp = f"{workdir}/lyrics_final.ass"
    with open(vp, "w", encoding="utf-8") as fh:
        fh.write(v)
    with open(fp, "w", encoding="utf-8") as fh:
        fh.write(f)
    return vp, fp

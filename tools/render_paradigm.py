#!/usr/bin/env python3
"""渲染"设计范式图"（概念层，三段式布局）。

用法: python tools/render_paradigm.py
生成: docs/paradigm.png

设计原则：范式图只讲范式，不画流水线细节（细节由 architecture_main.png 承担）。
三段自上而下：① 主体骨架 Plan-and-Execute → ② 执行中两个受护栏环 → ③ 跨次反思闭环。
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "paradigm.png")

W, H = 1360, 1050
BG = (255, 255, 255)
INK = (32, 32, 38)
GRAY = (105, 105, 115)
PURPLE = (127, 119, 221)
PURPLE_BG = (240, 238, 253)
ORANGE = (224, 130, 30)
ORANGE_BG = (253, 241, 224)
BLUE = (46, 108, 180)
BLUE_BG = (234, 242, 251)
GREEN = (24, 148, 110)
CODE_BG = (247, 247, 250)
CODE_EDGE = (168, 168, 182)


def F(size):
    return ImageFont.truetype(FONT_PATH, size, index=0)


f_title, f_h2, f_node, f_sm, f_tag = F(30), F(23), F(20), F(17), F(16)


def box(d, xy, fill, edge, r=10, w=2):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=edge, width=w)


def ctext(d, cx, cy, text, font, fill=INK):
    lines = text.split("\n")
    lh = font.size + 7
    y = cy - (len(lines) * lh - 7) / 2
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text((cx - w / 2, y), ln, font=font, fill=fill)
        y += lh


def head(d, p1, p2, color, w=3):
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    L = 12
    a1 = (p2[0] - L * math.cos(ang - 0.42), p2[1] - L * math.sin(ang - 0.42))
    a2 = (p2[0] - L * math.cos(ang + 0.42), p2[1] - L * math.sin(ang + 0.42))
    d.polygon([p2, a1, a2], fill=color)


def arrow(d, pts, color=GRAY, w=3):
    for i in range(len(pts) - 1):
        d.line([pts[i], pts[i + 1]], fill=color, width=w)
    head(d, pts[-2], pts[-1], color, w)


def badge(d, cx, cy, text, fill=GREEN):
    r = 16
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    ctext(d, cx, cy, text, f_tag, (255, 255, 255))


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((44, 30), "设计范式：Plan-and-Execute 变体 + 受护栏 ReAct + 数据驱动反思",
           font=f_title, fill=INK)

    M = 60
    CW = W - 2 * M

    # ===== 第①段：主体骨架 =====
    y0 = 100
    d.text((M, y0), "① 主体骨架 · Plan-and-Execute（计划的是创意参数，执行步骤写死）",
           font=f_h2, fill=INK)
    sy = y0 + 48
    SH = 190

    box(d, [M, sy, M + CW, sy + SH], CODE_BG, CODE_EDGE, r=14, w=2)

    box(d, [M + 30, sy + 45, M + 250, sy + 145], PURPLE_BG, PURPLE, w=3)
    ctext(d, M + 140, sy + 78, "Planner 规划  [LLM]", f_node, PURPLE)
    ctext(d, M + 140, sy + 115, "读歌词情绪 → 出方案\n主题/意象流/16 段 prompt", f_sm)
    box(d, [M + 310, sy + 45, M + 500, sy + 145], ORANGE_BG, ORANGE, w=3)
    ctext(d, M + 405, sy + 78, "确定性校验  [代码]", f_node, ORANGE)
    ctext(d, M + 405, sy + 115, "段数=覆盖公式\n人物词=正则净化", f_sm)
    box(d, [M + 560, sy + 45, M + 930, sy + 145], (255, 255, 255), PURPLE, w=3)
    ctext(d, M + 745, sy + 78, "固定执行流水线  [代码]", f_node)
    ctext(d, M + 745, sy + 115, "对齐 → 验证片 → 人工闸门 → 生片 → 合成\n（顺序写死：可测试·可幂等续跑·成本递增）", f_sm)
    box(d, [M + 990, sy + 45, M + 1230, sy + 145], (255, 255, 255), CODE_EDGE, w=2)
    ctext(d, M + 1110, sy + 78, "产物", f_node)
    ctext(d, M + 1110, sy + 115, "成片 + 封面 + 事件轴\n+ 运行报告", f_sm)

    arrow(d, [(M + 250, sy + 95), (M + 306, sy + 95)])
    arrow(d, [(M + 500, sy + 95), (M + 556, sy + 95)])
    arrow(d, [(M + 930, sy + 95), (M + 986, sy + 95)])

    # ===== 第②段：两个受护栏环 =====
    y1 = sy + SH + 58
    d.text((M, y1), "② 执行中的异常 → 两个受护栏环（LLM 可以试错，门槛保证不会越修越坏）",
           font=f_h2, fill=INK)
    ey = y1 + 48
    EH = 230
    half = (CW - 40) // 2

    # 左：ReAct 修复环
    lx = M
    box(d, [lx, ey, lx + half, ey + EH], (252, 252, 255), PURPLE, r=14, w=3)
    d.text((lx + 22, ey + 16), "ReAct 修复环 · 字幕对不齐时  [LLM]", font=f_node, fill=PURPLE)
    ny = ey + 70
    box(d, [lx + 24, ny, lx + 174, ny + 70], (255, 255, 255), PURPLE, w=2)
    ctext(d, lx + 99, ny + 35, "诊断报告\n偏差/间奏", f_sm)
    box(d, [lx + 204, ny, lx + 354, ny + 70], (255, 255, 255), PURPLE, w=2)
    ctext(d, lx + 279, ny + 35, "function calling\n选修复工具", f_sm)
    arrow(d, [(lx + 174, ny + 35), (lx + 200, ny + 35)])
    mt_w = half - 24 - 384 - 24
    box(d, [lx + 384, ny - 6, lx + 384 + mt_w + 24, ny + 76], ORANGE_BG, ORANGE, w=3)
    ctext(d, lx + 384 + mt_w / 2 + 12, ny + 12, "质量门槛  [代码]", f_node, ORANGE)
    ctext(d, lx + 384 + mt_w / 2 + 12, ny + 48, "Δmax≤3s 且不劣化", f_sm)
    arrow(d, [(lx + 354, ny + 35), (lx + 380, ny + 35)])
    arrow(d, [(lx + 99, ny + 70), (lx + 99, ey + EH - 46)], GREEN)
    ctext(d, lx + 99 + 130, ey + EH - 30, "① 被拒原因回传 · 换招重试（秒级）", f_sm, GREEN)
    arrow(d, [(lx + 384 + mt_w / 2 + 12, ny + 76),
              (lx + 384 + mt_w / 2 + 12, ey + EH - 70)], ORANGE)
    ctext(d, lx + 384 + mt_w / 2 + 12, ey + EH - 52, "通过 → 采纳新结果", f_sm, ORANGE)
    badge(d, lx + 56, ny + 100, "①")

    # 右：QC 批评环
    rx = M + half + 40
    box(d, [rx, ey, rx + half, ey + EH], (252, 252, 255), PURPLE, r=14, w=3)
    d.text((rx + 22, ey + 16), "视觉 QC 批评环 · 画面有人物/变形时  [LLM]", font=f_node, fill=PURPLE)
    box(d, [rx + 24, ny, rx + 174, ny + 70], (255, 255, 255), PURPLE, w=2)
    ctext(d, rx + 99, ny + 35, "多模态审图\n每段抽 2 帧", f_sm)
    box(d, [rx + 204, ny, rx + 354, ny + 70], (255, 255, 255), PURPLE, w=2)
    ctext(d, rx + 279, ny + 35, "输出批评\nrevised_prompt", f_sm)
    arrow(d, [(rx + 174, ny + 35), (rx + 200, ny + 35)])
    box(d, [rx + 384, ny - 6, rx + 384 + mt_w + 24, ny + 76], (255, 255, 255), PURPLE, w=2)
    ctext(d, rx + 384 + mt_w / 2 + 12, ny + 35, "带批评重生成", f_sm)
    arrow(d, [(rx + 354, ny + 35), (rx + 380, ny + 35)])
    arrow(d, [(rx + 99, ny + 70), (rx + 99, ey + EH - 46)], GREEN)
    ctext(d, rx + 99 + 150, ey + EH - 30, "② 批评意见驱动改进（分钟级）", f_sm, GREEN)
    badge(d, rx + 56, ny + 100, "②")

    # 承接虚线
    arrow(d, [(M + 700, sy + SH), (lx + half / 2, ey)], GRAY, 2)
    arrow(d, [(M + 930, sy + 95), (M + 930, ey + 10), (rx + half / 2, ey)], GRAY, 2)
    d.text((M + 714, sy + SH + 14), "对齐异常 ↓", font=f_tag, fill=GRAY)
    d.text((M + 944, sy + SH + 14), "画面异常 ↓", font=f_tag, fill=GRAY)

    # ===== 第③段：跨次反思 =====
    y2 = ey + EH + 64
    d.text((M, y2), "③ 跨次运行反思 · 系统越跑越准", font=f_h2, fill=INK)
    ty = y2 + 48
    TH = 130
    box(d, [M, ty, M + CW, ty + TH], BLUE_BG, BLUE, r=14, w=3)
    ctext(d, M + CW / 2, ty + 38, "lessons.jsonl + playbook.md —— 双层记忆  [反思点 ③ · 天级]", f_node, BLUE)
    ctext(d, M + CW / 2, ty + 82,
          "每次运行结束：路由/偏差/QC 结果自动追加 → 下次规划注入最近 5 条（playbook 为人工维护的长期策略，始终注入）",
          f_sm)

    # 闭环：③ 左侧上回 Planner
    arrow(d, [(M + 30, ty + 30), (30, ty + 30), (30, sy + 95), (M + 26, sy + 95)], BLUE, 3)
    d.text((40, ty - 14), "③ 运行结束写入 → 规划前注入（天级）", font=f_sm, fill=BLUE)
    # 两环经验回流
    arrow(d, [(lx + half / 2, ey + EH), (M + int(CW * 0.3), ty)], GREEN, 2)
    arrow(d, [(rx + half / 2, ey + EH), (M + int(CW * 0.7), ty)], GREEN, 2)

    # ===== 底部 =====
    by = ty + TH + 36
    box(d, [M, by, M + CW, by + 74], (250, 250, 252), GRAY, r=12, w=2)
    ctext(d, M + CW / 2, by + 24,
          "LLM 负责判断 · 代码负责正确性 · 工具让 LLM 能做事 · 闭环让系统能学习", f_node)
    ctext(d, M + CW / 2, by + 56,
          "缺一不可：无决策点 = 纯脚本；无工具调用 = LLM 只是文本处理器；无反馈闭环 = 错了不能自修复", f_sm, GRAY)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()

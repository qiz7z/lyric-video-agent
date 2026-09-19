#!/usr/bin/env python3
"""渲染"设计范式图"：Plan-and-Execute 主体 + 嵌入式受护栏 ReAct + 三个反思点。

用法: python tools/render_paradigm.py
生成: docs/paradigm.png (白底，面试讲解用概念层图)
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
OUT = os.path.join(os.path.dirname(__file__), "..", "docs", "paradigm.png")

W, H = 1560, 1080
BG = (255, 255, 255)
INK = (35, 35, 40)
GRAY = (110, 110, 120)
PURPLE = (127, 119, 221)      # LLM 决策点
PURPLE_BG = (238, 236, 252)
BLUE = (52, 110, 183)         # 记忆/反思
BLUE_BG = (232, 240, 250)
ORANGE = (224, 130, 30)       # 人工/质量门槛
ORANGE_BG = (253, 240, 222)
GREEN = (29, 158, 117)        # 反思点标注
GREEN_BG = (228, 245, 238)
PIPE_BG = (246, 246, 250)
PIPE_EDGE = (170, 170, 185)


def F(size):
    return ImageFont.truetype(FONT_PATH, size, index=0)


f_title, f_node, f_sm, f_tag, f_num = F(30), F(21), F(17), F(16), F(19)


def box(d, xy, fill, edge, r=10, w=2):
    d.rounded_rectangle(xy, radius=r, fill=fill, outline=edge, width=w)


def center_text(d, cx, cy, text, font, fill=INK, lh=None):
    lines = text.split("\n")
    lh = lh or (font.size + 8)
    total = len(lines) * lh - 8
    y = cy - total / 2
    for ln in lines:
        w = d.textlength(ln, font=font)
        d.text((cx - w / 2, y), ln, font=font, fill=fill)
        y += lh


def arrow(d, p1, p2, color=GRAY, w=3, label=None, lcolor=None):
    d.line([p1, p2], fill=color, width=w)
    _head(d, p1, p2, color, w)
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        tw = d.textlength(label, font=f_tag)
        d.rounded_rectangle([mx - tw / 2 - 6, my - 13, mx + tw / 2 + 6, my + 13],
                            radius=6, fill=(255, 255, 255), outline=lcolor or color, width=1)
        d.text((mx - tw / 2, my - 11), label, font=f_tag, fill=lcolor or color)


def _head(d, p1, p2, color, w):
    import math
    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    L = 11 + w
    a1 = (p2[0] - L * math.cos(ang - 0.42), p2[1] - L * math.sin(ang - 0.42))
    a2 = (p2[0] - L * math.cos(ang + 0.42), p2[1] - L * math.sin(ang + 0.42))
    d.polygon([p2, a1, a2], fill=color)


def badge(d, cx, cy, text, fill=GREEN, r=15):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)
    center_text(d, cx, cy, text, f_num, (255, 255, 255))


def main():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((40, 26), "设计范式：Plan-and-Execute 变体 + 嵌入式受护栏 ReAct + 数据驱动反思",
           font=f_title, fill=INK)
    d.text((40, 66), "确定性流水线负责「不会错」· LLM 决策点负责「有判断」· 人工闸门负责「贵的别白花」",
           font=f_sm, fill=GRAY)

    # ── 顶部：Plan-and-Execute 主体 ──
    # Planner
    box(d, [70, 120, 330, 230], PURPLE_BG, PURPLE, w=3)
    center_text(d, 200, 165, "Planner 规划", f_node, PURPLE)
    center_text(d, 200, 196, "出创意参数方案\n主题/意象流/字体", f_sm)

    # 校验菱形（简化为小框）
    box(d, [390, 138, 560, 212], ORANGE_BG, ORANGE, w=3)
    center_text(d, 475, 158, "确定性校验", f_node, ORANGE)
    center_text(d, 475, 188, "段数公式/人物词正则\n不合规直接打回", f_sm)

    # 执行流水线大框
    box(d, [620, 100, 1460, 360], PIPE_BG, PIPE_EDGE, r=14, w=2)
    d.text((640, 112), "固定执行流水线（步骤顺序写死：可测试 · 可幂等续跑）", font=f_sm, fill=GRAY)
    stages = [("对齐\nDP 单调对齐", 660), ("验证片\n≈11MB 几秒", 830),
              ("人工闸门\n确认才继续", 1000), ("Agnes 生片\n25-40 分钟", 1170),
              ("合成\nxfade+字幕", 1340)]
    for txt, x in stages:
        is_gate = "人工" in txt
        box(d, [x, 150, x + 130, 240], ORANGE_BG if is_gate else (255, 255, 255),
            ORANGE if is_gate else PURPLE, w=3 if is_gate else 2)
        center_text(d, x + 65, 195, txt, f_sm)
    for x in (790, 960, 1130, 1300):
        arrow(d, (x - 14, 195), (x + 16, 195))
    d.text((640, 262), "异常发生：字幕对不齐（降级路由）→ 进入修复环；画面有变形/人物 → 进入 QC 环",
           font=f_sm, fill=GRAY)
    arrow(d, (725, 240), (725, 330), ORANGE, 3)
    arrow(d, (1235, 240), (1235, 330), PURPLE, 3)

    # ── 左下：ReAct 修复环 ──
    box(d, [80, 330, 560, 610], (252, 252, 255), PURPLE, r=14, w=3)
    d.text((100, 344), "嵌入式 ReAct 修复环（≤3 轮）", font=f_node, fill=PURPLE)
    r_nodes = [("诊断报告\n路由/偏差/间奏", 110, 400), ("选工具\nre_align/trim", 300, 400),
               ("执行重对齐", 430, 490)]
    for txt, x, y in r_nodes:
        box(d, [x, y, x + 120, y + 76], (255, 255, 255), PURPLE, w=2)
        center_text(d, x + 60, y + 38, txt, f_sm)
    arrow(d, (230, 438), (296, 438))
    arrow(d, (415, 476), (465, 486))
    # 质量门槛
    box(d, [270, 486, 420, 566], ORANGE_BG, ORANGE, w=3)
    center_text(d, 345, 508, "质量门槛", f_node, ORANGE)
    center_text(d, 345, 540, "Δmax≤3s 且不劣化\n否则 REJECTED", f_sm)
    arrow(d, (470, 528), (426, 526))
    # 被拒回传（反思①）
    arrow(d, (266, 545), (170, 500), GREEN, 3)
    d.text((108, 552), "被拒原因回传·换招重试", font=f_tag, fill=GREEN)
    badge(d, 82, 438, "①")
    d.text((95, 580), "① 轮内失败反思：拒绝原因回传 LLM，不原样重试", font=f_sm, fill=GREEN)

    # ── 右下：QC 批评改进环 ──
    box(d, [940, 330, 1460, 610], (252, 252, 255), PURPLE, r=14, w=3)
    d.text((960, 344), "视觉 QC 批评改进环（≤2 轮）", font=f_node, fill=PURPLE)
    q_nodes = [("抽帧\n每段 2 帧", 970, 400), ("多模态审图\n人物/变形/离题", 1120, 400),
               ("带批评重生成\nrevised_prompt", 1290, 490)]
    for txt, x, y in q_nodes:
        box(d, [x, y, x + 130, y + 76], (255, 255, 255), PURPLE, w=2)
        center_text(d, x + 65, y + 38, txt, f_sm)
    arrow(d, (1100, 438), (1116, 438))
    arrow(d, (1250, 476), (1300, 486))
    arrow(d, (1285, 545), (1150, 505), GREEN, 3)
    d.text((1108, 552), "批评意见驱动改进", font=f_tag, fill=GREEN)
    badge(d, 1090, 438, "②")
    d.text((955, 580), "② 生成后批评反思：不只判不合格，还给改法", font=f_sm, fill=GREEN)

    # ── 底部：lessons 跨次反思 ──
    box(d, [300, 720, 1180, 850], BLUE_BG, BLUE, r=14, w=3)
    center_text(d, 740, 760, "lessons.jsonl —— 跨次运行反思（反思点 ③）", f_node, BLUE)
    center_text(d, 740, 800, "每次运行结束：路由/偏差/QC 结果自动追加  →  下次规划时注入最近 5 条",
                f_sm)
    badge(d, 285, 785, "③")
    # 回边：运行结束 -> lessons（走画布最右外侧，不穿 QC 环）
    arrow(d, (1420, 240), (1500, 240), BLUE, 3)
    arrow(d, (1500, 240), (1500, 785), BLUE, 3)
    arrow(d, (1500, 785), (1184, 785), BLUE, 3)
    d.text((1508, 480), "运行结束\n写入经验", font=f_tag, fill=BLUE)
    # 注入边：lessons -> Planner（走画布最左外侧，不穿修复环）
    arrow(d, (296, 800), (30, 800), BLUE, 3)
    arrow(d, (30, 800), (30, 175), BLUE, 3)
    arrow(d, (30, 175), (66, 175), BLUE, 3)
    d.text((6, 460), "两层记忆\n规划前注入", font=f_tag, fill=BLUE)

    # ── 右下角：范式定位标注 ──
    box(d, [940, 900, 1500, 1055], (250, 250, 252), GRAY, r=12, w=2)
    d.text((962, 914), "范式定位", font=f_node, fill=INK)
    d.text((962, 952), "主体 = Plan-and-Execute 变体（计划创意参数而非步骤）", font=f_sm, fill=GRAY)
    d.text((962, 982), "局部 = 受护栏 ReAct（小工具集/轮数上限/门槛否决权）", font=f_sm, fill=GRAY)
    d.text((962, 1012), "反思 = 数据驱动（指标/QC 结论），非 LLM 自我批评", font=f_sm, fill=GRAY)

    # 底部说明
    d.text((40, 930), "三个时间尺度的反思：① 秒级·轮内换招   ② 分钟级·生成后批评   ③ 天级·跨运行沉淀",
           font=f_node, fill=INK)
    d.text((40, 975), "缺任一特征都站不住：无决策点=纯脚本；无工具调用=LLM 只是文本处理器；无反馈闭环=错了不能自修复",
           font=f_sm, fill=GRAY)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()

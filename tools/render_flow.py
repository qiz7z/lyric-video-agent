#!/usr/bin/env python3
"""把 README 里的两张 mermaid 流程图渲染成 PNG（中文友好，零外部依赖，仅 Pillow）。

用法:
    python tools/render_flow.py
生成:
    docs/pipeline_main.png   主流水线
    docs/pipeline_cover.png  封面 Agent 内部流水线
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")

# ---------- 字体 ----------
def load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size, index=0)
    except Exception:
        return ImageFont.load_default()

FONT = load_font(19)
FONT_SM = load_font(16)

# ---------- 颜色 ----------
C_DEFAULT_FILL = (255, 255, 255)
C_DEFAULT_LINE = (90, 90, 100)
C_TEXT = (35, 35, 40)
C_PURPLE = (127, 119, 221)
C_ORANGE = (239, 159, 39)
C_GREEN = (29, 158, 117)
C_NEUTRAL_FILL = (232, 232, 240)
C_EDGE = (110, 110, 120)
C_EDGE_BACK = (200, 90, 90)
C_LABEL_BG = (255, 255, 255)
C_EDGE_DASHED = (29, 158, 117)  # 虚线边（并行支线）用绿色，呼应封面 Agent 绿框

PAD_X = 16
PAD_Y = 12
LINE_H = 25
NODE_W = 250          # 统一盒宽，网格更整齐
ROW_GAP_TD = 64       # TD 行间距（给边留空间）
ROW_GAP_LR = 70
COL_GAP = 46

# ---------- 文本换行（按空格优先保留完整英文单词） ----------
def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if not para:
            out.append("")
            continue
        line = ""
        for ch in para:
            test = line + ch
            if font.getlength(test) > max_w and line:
                # 退到行内最后一个空格处换行（避免把英文单词拆散）
                sp = line.rfind(" ")
                if sp > 0:
                    out.append(line[:sp])
                    line = line[sp + 1:] + ch
                else:
                    out.append(line)
                    line = ch
            else:
                line = test
        out.append(line)
    return out

def measure(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    lines = wrap(text, font, NODE_W - 2 * PAD_X)
    w = max((font.getlength(ln) for ln in lines), default=0)
    h = len(lines) * LINE_H
    return int(w), h, lines

# ---------- 图数据 ----------
def main_nodes():
    return [
        ("A", "源音频 mp3/m4a/flac 用户提供的文件", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("META", "提取 歌名/歌手\n文件名 / ID3 标签", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("B", "1. 音频\nffmpeg 解码为立体声 wav", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("C", "2. 歌词\n内嵌 LRC → LRCLib 兜底", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("D", "3. Planner 规划\n主题/意象流/段数\nprompts×N → 生片\n+ 代码硬校验", "box", C_PURPLE, C_PURPLE, (255, 255, 255), 0),
        ("E", "4. 对齐\ndemucs 人声分离 → onset 切段", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("F", "ratio = 段数 / 行数", "diamond", C_NEUTRAL_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("G", "sequential\nDP 单调对齐", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("H", "lrc_primary\nLRC 主基准 + 近距吸附", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("I", "interp\nLRC 直通", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("J", "修复循环\nLLM function-calling ≤3 轮", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("J1", "质量门槛\ndelta_max ≤ 3s 且不劣化", "diamond", C_PURPLE, C_PURPLE, (255, 255, 255), 0),
        ("K", "events.json + report.json", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("L", "5. 验证片\n黑底白字 ≈10MB 数秒渲完", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("M", "6. 人工听感闸门", "box", C_ORANGE, C_ORANGE, (0, 0, 0), 0),
        ("M1", "终止 · 修正后重跑", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("N", "7. Agnes 生片\n16-21 段 · 25-40 分钟", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("O", "8. 视觉质检\n每段抽 2 帧", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("O1", "人物 / 变形 / 离题", "diamond", C_PURPLE, C_PURPLE, (255, 255, 255), 0),
        ("P", "改写 prompt 重生成 ≤2 轮", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("Q", "9. 合成\nxfade + 烧字幕 NVENC→libx264", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("S", "10. 运行报告 + lessons 记忆回写", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("RC", "封面 Agent 支线\n调研→生图→文案→排版→QC", "box", C_GREEN, C_GREEN, (255, 255, 255), 1),
    ]

def main_edges():
    return [
        ("A", "B", "", False), ("A", "META", "", False), ("B", "C", "", False), ("C", "D", "", False),
        ("META", "D", "标题歌手", False), ("D", "D", "LLM决策点", False), ("D", "E", "", False), ("E", "F", "", False),
        ("F", "G", "1.0~2.0", False), ("F", "H", "ratio>2.0", False), ("F", "I", "ratio<1.0 降级", False),
        ("G", "K", "", False), ("H", "K", "", False), ("I", "J", "", False),
        ("J", "J1", "LLM决策点", False), ("J1", "J", "REJECTED 自动回退", True),
        ("J1", "K", "通过", False),
        ("K", "L", "", False), ("L", "M", "", False),
        ("M", "M1", "否", False), ("M", "N", "是", False),
        ("N", "O", "", False), ("O", "O1", "LLM决策点", False),
        ("O1", "P", "不合格", False), ("P", "O", "", True), ("O1", "Q", "通过", False),
        ("Q", "S", "", False),
        ("META", "RC", "并行生成", False), ("D", "RC", "主题可选", False),
        ("RC", "S", "汇合报告", False),
    ]

def cover_nodes():
    return [
        ("A", "歌名/歌手 取自文件名 / ID3", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("B", "0. 调研\n文本模型 + search_web 工具", "box", C_PURPLE, C_PURPLE, (255, 255, 255), 0),
        ("C", "1. 候选帧抽取", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("D", "2. 选帧\n视觉模型", "box", C_PURPLE, C_PURPLE, (255, 255, 255), 0),
        ("E", "3. 竖版背景\n图片模型", "box", C_PURPLE, C_PURPLE, (255, 255, 255), 0),
        ("F", "4. 文案\n文本模型", "box", C_PURPLE, C_PURPLE, (255, 255, 255), 0),
        ("G", "5. 排版\n代码 drawtext + 行楷", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
        ("H", "6. 封面 QC\n视觉模型", "box", C_PURPLE, C_PURPLE, (255, 255, 255), 0),
        ("I", "cover_final.png\n1080×1440", "box", C_DEFAULT_FILL, C_DEFAULT_LINE, C_TEXT, 0),
    ]

def cover_edges():
    return [
        ("A", "B", "", False), ("B", "C", "", False), ("C", "D", "", False),
        ("D", "E", "", False), ("E", "F", "", False), ("F", "G", "", False),
        ("G", "H", "", False),
        ("H", "I", "通过", False), ("H", "E", "不合格", True),
    ]

# ---------- 边样式 + 路由辅助 ----------
# 并行支线相关的三条虚线边（绿色）：META→RC / D→RC / RC→S
DASHED_EDGES = {("META", "RC"), ("D", "RC"), ("RC", "S")}
RC_EDGES = {("META", "RC"), ("D", "RC"), ("RC", "S")}


def _draw_label(d, mx, my, lbl):
    tw = FONT_SM.getlength(lbl)
    d.rectangle([mx - tw / 2 - 4, my - 10, mx + tw / 2 + 4, my + 12], fill=C_LABEL_BG)
    d.text((mx - tw / 2, my - 8), lbl, font=FONT_SM, fill=(60, 60, 70))


def _draw_dashed(d, pts, color, width=2, dash=(8, 6)):
    """手写虚线（当前 Pillow 版本不支持 line() 的 dash 参数）。"""
    on, off = dash
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        total = math.hypot(b[0] - a[0], b[1] - a[1])
        if total == 0:
            continue
        dx, dy = (b[0] - a[0]) / total, (b[1] - a[1]) / total
        dist, draw_on = 0.0, True
        while dist < total:
            step = on if draw_on else off
            nd = min(dist + step, total)
            if draw_on:
                d.line([(a[0] + dx * dist, a[1] + dy * dist),
                        (a[0] + dx * nd, a[1] + dy * nd)], fill=color, width=width)
            dist, draw_on = nd, (not draw_on)


def _draw_path(d, pts, color, dashed):
    """画折线 + 末端箭头。joint='curve' 让拐角变圆滑（接近 mermaid 正交风格）。"""
    if dashed:
        _draw_dashed(d, pts, color)
    else:
        d.line(pts, fill=color, width=2, joint="curve")
    p0, p1 = pts[-2], pts[-1]
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    L = 11
    a1 = (p1[0] - L * math.cos(ang - 0.4), p1[1] - L * math.sin(ang - 0.4))
    a2 = (p1[0] - L * math.cos(ang + 0.4), p1[1] - L * math.sin(ang + 0.4))
    d.polygon([p1, a1, a2], fill=color)


def _rc_route(a, b, sa, sb, sz_a, sz_b, outer_x, orient):
    """封面支线 RC 的边走图右侧外部通道，避免斜穿主链。"""
    wa, ha = sz_a
    wb, hb = sz_b
    if orient != "TD":
        return (
            [(sa[0] + wa / 2, sa[1] + ha), (sb[0] + wb / 2, sb[1])],
            ((sa[0] + sb[0]) / 2, (sa[1] + sb[1]) / 2),
        )
    if a == "RC":  # 从 RC 出发（RC→S）
        start = (sa[0] + wa / 2, sa[1] + ha)
        gy = start[1] + ROW_GAP_TD / 2
        bx = sb[0] + wb / 2
        by = sb[1]
        pts = [start, (start[0], gy), (outer_x, gy), (outer_x, by), (bx, by)]
        lp = (outer_x + 8, (gy + by) / 2)
    else:  # 接到 RC（META→RC / D→RC）
        start = (sa[0] + wa, sa[1] + ha / 2)
        bx = sb[0] + wb / 2
        by = sb[1]
        pts = [start, (outer_x, start[1]), (outer_x, by), (bx, by)]
        lp = (outer_x + 8, (start[1] + by) / 2)
    return pts, lp

# ---------- 布局 + 绘制 ----------
def layout(nodes, edges, orientation):
    # rank = 最长路径（忽略回边；自环 a==b 也排除，否则 rank 死循环）
    fwd = [(a, b) for a, b, _, back in edges if not back and a != b]
    rank = {n[0]: 0 for n in nodes}
    changed = True
    while changed:
        changed = False
        for a, b in fwd:
            if rank[b] < rank[a] + 1:
                rank[b] = rank[a] + 1
                changed = True
    # RC 强制放到中部偏下，让两条连接线都适中
    if "RC" in rank:
        rank["RC"] = max(rank.values()) // 2 + 1

    by_rank: dict[int, list] = {}
    for nid, *_ in nodes:
        by_rank.setdefault(rank[nid], []).append(nid)

    # 计算每节点尺寸
    sizes = {}
    for nid, label, shape, fill, line, text, lane in nodes:
        _, h, lines = measure(label, FONT)
        sizes[nid] = (max(NODE_W, int(FONT.getlength(label.split(chr(10))[0])) + 2 * PAD_X) if shape != "diamond" else NODE_W,
                      h + 2 * PAD_Y, lines, shape, fill, line, text, lane)

    max_rank = max(rank.values())
    center_max_w = 0
    for ids in by_rank.values():
        n0 = len([i for i in ids if sizes[i][7] == 0])
        w = n0 * NODE_W + (n0 - 1) * COL_GAP if n0 else 0
        center_max_w = max(center_max_w, w)
    right_lane_x = center_max_w + COL_GAP  # 右侧支线 x（TD）
    # 行高（TD 每 rank 高度取该 rank 最高节点 + 间距）
    row_h = {}
    for r, ids in by_rank.items():
        rh = max((sizes[i][1] for i in ids), default=NODE_W) + (ROW_GAP_TD if orientation == "TD" else ROW_GAP_LR)
        row_h[r] = rh

    pos = {}
    if orientation == "TD":
        RC_W = NODE_W + COL_GAP
        total_w = center_max_w + COL_GAP + NODE_W + RC_W + 30
        outer_x = right_lane_x + NODE_W + COL_GAP
        y_cursor = 30
        y_of_rank = {}
        for r in range(max_rank + 1):
            y_of_rank[r] = y_cursor
            y_cursor += row_h.get(r, NODE_W + ROW_GAP_TD)
        for r, ids in by_rank.items():
            lane0 = [i for i in ids if sizes[i][7] == 0]
            lane1 = [i for i in ids if sizes[i][7] == 1]
            n = len(lane0)
            block_w = n * NODE_W + (n - 1) * COL_GAP if n else 0
            start_x = (center_max_w - block_w) / 2
            for k, i in enumerate(lane0):
                x = start_x + k * (NODE_W + COL_GAP)
                pos[i] = (x, y_of_rank[r])
            for i in lane1:
                pos[i] = (right_lane_x, y_of_rank[r])
        W = total_w
        H = y_cursor + 30
    else:  # LR
        max_row_nodes = max((len([i for i in ids if sizes[i][7] == 0]) for ids in by_rank.values()), default=1)
        col_w = NODE_W + COL_GAP
        total_h = max_row_nodes * (NODE_W + COL_GAP)
        x_of_rank = {}
        x_cursor = 30
        for r in range(max_rank + 1):
            x_of_rank[r] = x_cursor
            x_cursor += col_w
        for r, ids in by_rank.items():
            lane0 = [i for i in ids if sizes[i][7] == 0]
            n = len(lane0)
            block_h = n * NODE_W + (n - 1) * COL_GAP if n else 0
            start_y = (total_h - block_h) / 2
            for k, i in enumerate(lane0):
                y = start_y + k * (NODE_W + COL_GAP)
                pos[i] = (x_of_rank[r], y)
        W = x_cursor + 30
        H = total_h + 30
    outer = outer_x if orientation == "TD" else 0
    return pos, sizes, orientation, (W, H), outer

def draw_node(d, nid, x, y, spec):
    _nid, label, shape, fill, line, text, lane = spec
    w, h, lines = sizes_w_h(spec)
    if shape == "diamond":
        cx, cy = x + w / 2, y + h / 2
        pts = [(cx, y), (x + w, cy), (cx, y + h), (x, cy)]
        d.polygon(pts, fill=fill, outline=line)
        anchor = (cx, cy)
    elif shape == "stadium":
        d.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=fill, outline=line)
        anchor = (x + w / 2, y + h / 2)
    else:
        d.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=fill, outline=line, width=2)
        anchor = (x + w / 2, y + h / 2)
    # 文本
    ty = y + (h - len(lines) * LINE_H) / 2
    for ln in lines:
        tw = FONT.getlength(ln)
        tx = x + (w - tw) / 2
        d.text((tx, ty), ln, font=FONT, fill=text)
        ty += LINE_H
    return anchor

def sizes_w_h(spec):
    _, label, shape, fill, line, text, lane = spec
    _, h, lines = measure(label, FONT)
    return NODE_W, h + 2 * PAD_Y, lines

def arrow(d, p1, p2, color, back=False):
    if back:
        # 贝塞尔回边
        ctrl1 = (p1[0] - 60, p1[1])
        ctrl2 = (p2[0] - 60, p2[1])
        d.line([p1, ctrl1, ctrl2, p2], fill=color, width=2, joint="curve")
        tip = p2
    else:
        d.line([p1, p2], fill=color, width=2)
        tip = p2
    # 箭头
    if back:
        ang = math.atan2(p2[1] - ctrl2[1], p2[0] - ctrl2[0])
    else:
        ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    L = 11
    a1 = (tip[0] - L * math.cos(ang - 0.4), tip[1] - L * math.sin(ang - 0.4))
    a2 = (tip[0] - L * math.cos(ang + 0.4), tip[1] - L * math.sin(ang + 0.4))
    d.polygon([tip, a1, a2], fill=color)

def render(name, nodes, edges, orientation, fname):
    pos, sizes, orient, (W, H), outer_x = layout(nodes, edges, orientation)
    img = Image.new("RGB", (int(W), int(H)), (255, 255, 255))
    d = ImageDraw.Draw(img)
    spec_of = {n[0]: n for n in nodes}
    # 先画边
    for a, b, lbl, back in edges:
        if a == b:
            # 自环标记（紫色 LLM 决策点的可视化，与 README 的 D -.->|LLM 决策点| D 对应）
            cx = pos[a][0] + sizes[a][0] / 2
            by = pos[a][1] + sizes[a][1]
            loop_w = 24
            pts = [(cx, by), (cx + loop_w, by + 16), (cx, by + 30), (cx - loop_w, by + 16), (cx, by)]
            d.line(pts, fill=C_EDGE, width=2, joint="curve")
            tip = (cx, by)
            ang = -math.pi / 2
            L = 11
            a1 = (tip[0] - L * math.cos(ang - 0.4), tip[1] - L * math.sin(ang - 0.4))
            a2 = (tip[0] - L * math.cos(ang + 0.4), tip[1] - L * math.sin(ang + 0.4))
            d.polygon([tip, a1, a2], fill=C_EDGE)
            if lbl:
                tw = FONT_SM.getlength(lbl)
                lx = cx + loop_w + 8
                ly = by + 14
                d.rectangle([lx - 4, ly - 10, lx + tw + 4, ly + 12], fill=C_LABEL_BG)
                d.text((lx, ly - 8), lbl, font=FONT_SM, fill=(60, 60, 70))
            continue
        sa = pos[a]
        sb = pos[b]
        wa, ha = sizes[a][0], sizes[a][1]
        wb, hb = sizes[b][0], sizes[b][1]
        sx, sy = sa
        tx, ty = sb
        dashed = (a, b) in DASHED_EDGES
        col = C_EDGE_BACK if back else (C_EDGE_DASHED if dashed else C_EDGE)
        if back:
            # 回边：保留原贝塞尔曲线（红色）
            if orient == "TD":
                p1 = (sx + wa, sy + ha / 2)
                p2 = (tx, ty + hb / 2)
            else:
                p1 = (sx + wa / 2, sy + ha)
                p2 = (tx + wb / 2, ty)
            arrow(d, p1, p2, col, back=True)
            if lbl:
                _draw_label(d, (p1[0] + p2[0]) / 2 - 60, (p1[1] + p2[1]) / 2, lbl)
            continue
        if (a, b) in RC_EDGES:
            pts, lp = _rc_route(a, b, sa, sb, (wa, ha), (wb, hb), outer_x, orient)
        elif orient == "TD":
            p1 = (sx + wa / 2, sy + ha)
            p2 = (tx + wb / 2, ty)
            if abs(p1[0] - p2[0]) < 3:
                pts = [p1, p2]
                lp = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            else:
                gy = p1[1] + ROW_GAP_TD / 2
                pts = [p1, (p1[0], gy), (p2[0], gy), p2]
                lp = ((p1[0] + p2[0]) / 2, gy)
        else:
            p1 = (sx + wa, sy + ha / 2)
            p2 = (tx, ty + hb / 2)
            if abs(p1[1] - p2[1]) < 3:
                pts = [p1, p2]
                lp = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            else:
                gx = p1[0] + ROW_GAP_LR / 2
                pts = [p1, (gx, p1[1]), (gx, p2[1]), p2]
                lp = (gx, (p1[1] + p2[1]) / 2)
        _draw_path(d, pts, col, dashed)
        if lbl and lp:
            _draw_label(d, lp[0], lp[1], lbl)
    # 再画节点（盖住边线）
    for nid, spec in spec_of.items():
        x, y = pos[nid]
        draw_node(d, nid, x, y, spec)
    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, fname)
    img.save(out, "PNG")
    print("saved", out, img.size)

if __name__ == "__main__":
    render("main", main_nodes(), main_edges(), "TD", "pipeline_main.png")
    render("cover", cover_nodes(), cover_edges(), "LR", "pipeline_cover.png")

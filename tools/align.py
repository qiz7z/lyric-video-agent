# -*- coding: utf-8 -*-
"""字幕-人声对齐：整个项目的核心算法（卡拉OK式逐句对齐）。

目标（用户唯一验收标准）：唱一句出一句、唱完即清。

算法骨架（三代实战版本收敛而来，见 ARCHITECTURE.md 的演进史）：
  1. demucs 干净人声 -> RMS 包络 -> 自适应阈值切"演唱段" -> 合并 <0.45s 呼吸段；
  2. 按段数/行数比选路由（映射按 onset 数选路）：
       ratio ≈ 1   -> sequential   顺序装填：行 i 按单调量化认领段，onset 为骨架；
       ratio >> 1  -> lrc_primary  段远多于行（DJ/重复副歌）：信 LRC，
                                     onset 只在 ±1.2s 内微调（贪心最近匹配会
                                     跨副歌吸附、经单调链放大成 3~9s 暴偏——实战教训）；
       ratio < 1   -> interp       段少于行：LRC 直接打底，建议人工锚点校准；
  3. 事件化：start=人声起唱点，end=下一句起点（零空隙零重叠）；
     长间奏（句距 > 10s）end=start+HOLD_AFTER；末句同理——绝不能挂到片尾。

输出 events + report（与历史工作区 events.json / report.json 同构，可对比验收）。
"""
from __future__ import annotations

import numpy as np

# ---- 可调策略参数（默认值即实战收敛值）----
MERGE_GAP = 0.30      # 呼吸段合并阈值（秒）：0.45 会把相邻短句粘死（两首歌
                      # 对比实验收敛值，见 tests/test_align.py 回归）
MIN_SEG = 0.15        # 丢弃短于此的噪声段
GROUP_GAP = 3.5       # >此静音视为乐句组边界
GAP_LONG = 10.0       # 句距超过此值视为长间奏
HOLD_AFTER = 6.0      # 长间奏/末句字幕驻留
MIN_DUR = 1.0         # 单条字幕最短显示
LRC_CORR = 1.2        # lrc_primary 路由的 onset 吸附窗口
SKIP_SEG_COST = 8.0   # DP 对齐中跳过一段（判为噪声）的代价


def detect_segments(rms: np.ndarray, times: np.ndarray, merge_gap: float | None = None,
                    thr_low: float | None = None, thr_high: float | None = None
                    ) -> tuple[list[list[float]], float]:
    """能量包络 -> 演唱段列表 [[start,end],...]。

    阈值 = max(P75*thr_low, 峰值*thr_high)；参数为 None 时用模块默认值
    （修复循环通过覆盖这些旋钮重试不同的分段灵敏度）。
    """
    high = np.percentile(rms, 75)
    thr = max(high * (thr_low if thr_low is not None else 0.45),
              float(rms.max()) * (thr_high if thr_high is not None else 0.10))
    mg = merge_gap if merge_gap is not None else MERGE_GAP
    above = rms > thr
    n = len(above)
    raw: list[list[float]] = []
    i = 0
    while i < n:
        if above[i]:
            j = i
            while j < n and above[j]:
                j += 1
            raw.append([float(times[i]), float(times[j - 1])])
            i = j
        else:
            i += 1
    merged: list[list[float]] = []
    for s in raw:
        if s[1] - s[0] < MIN_SEG:
            continue
        if merged and s[0] - merged[-1][1] < mg:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return merged, float(thr)


def _finalize(events: list[dict], total: float) -> list[dict]:
    """统一后处理：长间奏驻留 / 末句驻留 / 单调钳制 / 最短时长。"""
    for i, ev in enumerate(events):
        next_start = events[i + 1]["start"] if i + 1 < len(events) else total + 1.0
        if next_start - ev["start"] > GAP_LONG:
            ev["end"] = min(ev["start"] + HOLD_AFTER, total)   # 长间奏：驻留即清
        elif i + 1 < len(events):
            ev["end"] = events[i + 1]["start"]                 # 常规：唱完即清
        else:
            ev["end"] = min(ev["start"] + HOLD_AFTER, total)   # 末句：绝不挂片尾
    # 单调 + 越界 + 极短保护
    for i in range(len(events)):
        if i + 1 < len(events) and events[i]["end"] > events[i + 1]["start"]:
            events[i]["end"] = events[i + 1]["start"]
        events[i]["end"] = min(events[i]["end"], total)
        if events[i]["end"] - events[i]["start"] < MIN_DUR:
            events[i]["end"] = min(events[i]["start"] + MIN_DUR, total)
    # 过滤整段被裁掉的事件
    return [e for e in events if e["end"] > e["start"]]


def align(vocals_wav_envelope: tuple[np.ndarray, np.ndarray],
          lyrics: list[tuple[float, str]],
          total: float,
          trim: float = 0.0,
          merge_gap: float | None = None,
          thr_low: float | None = None,
          thr_high: float | None = None) -> tuple[list[dict], dict]:
    """主入口。lyrics=[(LRC秒, 文本)]；trim=前奏裁切秒数（ DJ 版长前奏可裁）。

    merge_gap/thr_low/thr_high 为分段检测旋钮（None=默认值），供修复循环覆盖。

    Returns
    -------
    events : [{"start","end","text","src","lrc","delta"}]
    report : 质量报告（与历史 report.json 同构），供人工/Agent 审阅。
    """
    if not lyrics:
        return [], {"route": "none", "reason": "no lyrics"}
    rms, times = vocals_wav_envelope
    segs, thr = detect_segments(rms, times, merge_gap=merge_gap,
                                thr_low=thr_low, thr_high=thr_high)

    if trim > 0:
        segs = [[s - trim, e - trim] for s, e in segs if e > trim]
        lyrics = [(t - trim, s) for t, s in lyrics if t >= trim - 1.0]
        total = total - trim

    ratio = len(segs) / len(lyrics) if lyrics else 0.0
    if len(segs) >= len(lyrics) and ratio <= 1.7:
        route = "sequential"
    elif ratio > 1.7:
        route = "lrc_primary"
    else:
        route = "interp"

    if route == "sequential":
        events = _align_sequential(segs, lyrics)
    elif route == "lrc_primary":
        events = _align_lrc_primary(segs, lyrics)
    else:
        events = _align_interp(segs, lyrics)

    events = _finalize(events, total)

    deltas = [abs(e["delta"]) for e in events if e.get("delta") is not None]
    long_gaps = [{"after_row": i, "gap": round(events[i + 1]["start"] - events[i]["end"], 2)}
                 for i in range(len(events) - 1)
                 if events[i + 1]["start"] - events[i]["start"] > GAP_LONG]
    report = {
        "route": route,
        "ratio_onset_to_line": round(ratio, 3),
        "n_lyrics": len(lyrics),
        "n_onsets": len(segs),
        "thr": round(thr, 4),
        "params": {"merge_gap": merge_gap if merge_gap is not None else MERGE_GAP,
                   "thr_low": thr_low if thr_low is not None else 0.45,
                   "thr_high": thr_high if thr_high is not None else 0.10},
        "trim": trim,
        "duration": round(total, 2),
        "first_onset": round(segs[0][0], 3) if segs else None,
        "src_counts": _count_src(events),
        "delta_abs_mean": round(float(np.mean(deltas)), 3) if deltas else None,
        "delta_abs_max": round(float(np.max(deltas)), 3) if deltas else None,
        "long_gaps": long_gaps,
    }
    return events, report


def _align_sequential(segs, lyrics):
    """顺序装填（DP 单调对齐）：以 onset 段为骨架，歌词行按出现顺序单调地
    分配到段上，代价 = |段起点-本行LRC| + |段末-下一行LRC|（双向锚定），
    允许以固定罚金跳过噪声段。

    为什么不用均匀量化（行 i 认领第 i*m/n 块段）：一行歌词实际演唱长度差异
    很大（副歌长句可跨 4 段），均匀量化会从第 2 行起逐级漂移（v5 教训的
    算法级复现）。DP 用 LRC 作软锚点求全局最优单调映射，与人工逐行核对
    的映射一致（寂寞沙洲冷回归测试验证）。
    """
    n, m = len(lyrics), len(segs)
    starts = [s[0] for s in segs]
    ends = [s[1] for s in segs]
    lrc = [t for t, _ in lyrics]
    # 下一行 LRC 作行尾锚点；末行的行尾锚点放宽到片尾附近
    lrc_next = lrc[1:] + [max(lrc[-1], segs[-1][1])]
    SKIP = SKIP_SEG_COST   # 判定一段为噪声的代价（高于正常匹配误差）
    INF = float("inf")

    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    take = [[-1] * (m + 1) for _ in range(n + 1)]   # -2=跳过噪声段；>=0=行首段号
    cost[0][0] = 0.0
    for i in range(n):
        for j in range(i, m + 1):
            cur = cost[i][j]
            if cur == INF:
                continue
            if j < m and cur + SKIP < cost[i][j + 1]:
                cost[i][j + 1] = cur + SKIP          # 跳过噪声段
                take[i][j + 1] = -2
            rest_min = n - i - 1                     # 留给后续行每行至少 1 段
            for k in range(j + 1, m - rest_min + 1):
                c = abs(starts[j] - lrc[i]) + abs(ends[k - 1] - lrc_next[i])
                nc = cur + c
                if nc < cost[i + 1][k]:
                    cost[i + 1][k] = nc
                    take[i + 1][k] = j
    for j in range(m):                                # 末行之后剩余段视为噪声
        if cost[n][j] + SKIP < cost[n][j + 1]:
            cost[n][j + 1] = cost[n][j] + SKIP
            take[n][j + 1] = -2
    if cost[n][m] == INF:
        raise RuntimeError("DP 对齐失败：无合法单调映射")

    # 回溯：还原每行认领的段区间 [a, b)
    spans = [None] * n
    j = m
    for i in range(n, 0, -1):
        while j > 0 and take[i][j] == -2:
            j -= 1
        prev = take[i][j]
        if prev < 0:
            raise RuntimeError("DP 回溯失败")
        spans[i - 1] = (prev, j)
        j = prev

    events = []
    for i, (lrc_t, text) in enumerate(lyrics):
        span = spans[i]
        if span is None:
            continue
        a, b = span
        line_segs = segs[a:b]
        parts = [p for p in text.split() if p.strip()]
        if len(parts) == len(line_segs) > 1:
            for (ss, ee), part in zip(line_segs, parts):
                events.append(_ev(ss, ee, part, "onset", lrc_t, delta=ss - lrc_t))
        else:
            events.append(_ev(line_segs[0][0], line_segs[-1][1], text, "onset",
                              lrc_t, delta=line_segs[0][0] - lrc_t))
    return events


def _align_lrc_primary(segs, lyrics):
    """LRC 主基准路由：起点取 LRC；仅当存在 |onset-LRC|<=1.2s 且保持单调的
    onset 时吸附过去（只吸收小漂移，绝不跨段吸附）。"""
    starts = [s[0] for s in segs]
    events, prev = [], -1e9
    for lrc_t, text in lyrics:
        cand = [o for o in starts if abs(o - lrc_t) <= LRC_CORR and o > prev + 0.2]
        if cand:
            ss = min(cand, key=lambda o: abs(o - lrc_t))
            src = "onset"
        else:
            ss = max(lrc_t, prev + 0.2)
            src = "lrc"
        prev = ss
        events.append(_ev(ss, None, text, src, lrc_t, delta=ss - lrc_t))
    return events


def _align_interp(segs, lyrics):
    """段少于行：LRC 直接打底；近处有 onset 就吸附（窗口放宽到 2.5s）。
    报告里提示建议人工锚点。"""
    starts = [s[0] for s in segs]
    events, prev = [], -1e9
    for lrc_t, text in lyrics:
        cand = [o for o in starts if abs(o - lrc_t) <= 2.5 and o > prev + 0.2]
        if cand:
            ss = min(cand, key=lambda o: abs(o - lrc_t))
            src = "onset"
        else:
            ss = max(lrc_t, prev + 0.2)
            src = "interp"
        prev = ss
        events.append(_ev(ss, None, text, src, lrc_t, delta=ss - lrc_t))
    return events


def _ev(start, end, text, src, lrc=None, delta=None):
    return {"start": round(float(start), 3), "end": end, "text": text,
            "src": src, "lrc": None if lrc is None else round(float(lrc), 3),
            "delta": None if delta is None else round(float(delta), 3)}


def _count_src(events):
    counts = {"onset": 0, "interp": 0, "lrc": 0, "mono": 0}
    for e in events:
        counts[e.get("src", "mono")] = counts.get(e.get("src", "mono"), 0) + 1
    return counts

# -*- coding: utf-8 -*-
"""修复循环工具的 JSON Schema（OpenAI function calling 格式）。

工具集刻意保持小而真实：每个工具都是编排器里已有的确定性动作，
LLM 的职责是"诊断报告 -> 选对工具和参数 -> 何时收手"，不是发明新能力。
"""
from __future__ import annotations

RE_ALIGN = {
    "type": "function",
    "function": {
        "name": "re_align",
        "description": "用新的分段参数重跑人声段检测与对齐。段数(n_onsets)与歌词行数"
                       "(n_lyrics)接近时，减小 merge_gap 通常能增加段数、有机会升级路由；"
                       "但路由升级不等于质量提升，系统会用质量门槛把关。",
        "parameters": {
            "type": "object",
            "properties": {
                "merge_gap": {"type": "number",
                              "description": "呼吸段合并阈值(秒)，默认0.30，越小段越碎"},
                "thr_low": {"type": "number",
                            "description": "能量阈值 P75 系数，默认0.45，越小越灵敏"},
                "thr_high": {"type": "number",
                             "description": "能量阈值峰值系数，默认0.10"},
                "reason": {"type": "string", "description": "一句话理由"},
            },
        },
    },
}

SET_TRIM = {
    "type": "function",
    "function": {
        "name": "set_trim",
        "description": "裁掉开头纯音乐前奏后重对齐（秒）。适用于长前奏/前奏人声稀疏"
                       "导致检测混乱的情况。",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "裁切秒数 0-60"},
                "reason": {"type": "string"},
            },
            "required": ["seconds"],
        },
    },
}

ACCEPT = {
    "type": "function",
    "function": {
        "name": "accept",
        "description": "接受当前对齐结果并结束修复循环（进入人工听感闸门）。",
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "接受理由"},
            },
            "required": ["reason"],
        },
    },
}

SEARCH_WEB = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "网页搜索：查歌曲的背景故事/创作主题/收录专辑/相关意象。"
                       "返回 [{title, body, href}] 摘要列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索词"},
            },
            "required": ["query"],
        },
    },
}

REPAIR_TOOLS = [RE_ALIGN, SET_TRIM, ACCEPT]

SYSTEM_PROMPT = """你是歌词视频 Agent 的对齐修复器。当前对齐走了降级路由 interp
（人声段少于歌词行数，部分字幕只能直接使用 LRC 时间，精度受限）。

报告字段含义：
- route: sequential(顺序装填,最优) / lrc_primary / interp(降级)
- n_onsets/n_lyrics: 检测到的演唱段数 / 歌词行数
- delta_abs_mean/max: 字幕起点与 LRC 估计的偏差均值/最大值（秒）
- long_gaps: 长间奏位置

策略：
1. 若 n_onsets 已接近 n_lyrics（比值>=0.85），可用 re_align 减小 merge_gap
   （如 0.22~0.26）争取升级路由；
2. 若前奏很长（first_onset 大），可 set_trim 裁掉前奏再对齐；
3. 每轮只调用一个工具，读完观察结果再决定下一步；
4. 系统有质量门槛：候选结果 delta_abs_max>3.0 或整体变差会被 REJECTED 并自动回退；
5. 最多 {max_rounds} 轮动作，之后必须 accept 并给出理由。
不要追求路由升级而不顾质量——被拒绝过的参数不要原样重试。"""

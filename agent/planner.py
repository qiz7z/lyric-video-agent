"""Planner：LLM 依据策略手册与歌曲元信息产出结构化制作计划。

为什么 Planner 输出后还要"确定性校验"（validate_plan）：
  LLM 负责创意与判断（意象、情绪、风格），数值约束交给代码——段数必须满足
  覆盖公式、prompt 必须过内容安全检查。这层"生成-校验"闭环让规划既灵活又
  不会算错段数导致视频比歌短。
"""

from __future__ import annotations

import json
import re

from tools.compose import clip_count_for

from .memory import load_lessons, load_playbook

SYSTEM_PROMPT = """你是歌词视频制作 Agent 的规划器。根据【策略手册】与歌曲信息，输出制作计划的 JSON。

硬性规则（来自长期实践，违反会直接导致成品不可用）：
1. 画面默认纯风景，任何 prompt 不得包含人物/人物部位/具体人物动作意象。
2. 每段 prompt 用英文书写，具体、有画面感、含 1-2 个记忆点意象；16 段左右的
   意象要形成情绪弧线（跟随歌词情绪推进），避免段与段意象重复。
3. negative_prompt 固定排除人物与文字水印。
4. 输出必须是单个合法 JSON 对象，不要包裹 markdown 代码块。

JSON 字段：
{{
  "theme": "一句话主题",
  "mood": "情绪关键词（英文）",
  "font": "STXingkai|STXinwei|STLiti|FZSTK 之一",
  "trim_intro_seconds": 数字（纯音乐前奏过长时可裁，一般 0）,
  "prompts": ["英文 prompt", ...共 {n_clips} 条],
  "notes": "给后续环节的备注"
}}"""


def build_plan(
    client, title: str, artist: str, duration: float, lyrics_preview: str, n_lines: int
) -> dict:
    """调 LLM 产出计划，并做确定性校验/修补。"""
    n_clips = clip_count_for(duration)
    lessons = load_lessons(5)
    user = json.dumps(
        {
            "task": "plan",
            "song": {
                "title": title,
                "artist": artist,
                "duration_sec": round(duration, 1),
                "n_lyric_lines": n_lines,
            },
            "lyrics_preview": lyrics_preview,
            "n_clips_required": n_clips,
            "recent_lessons": lessons,
            "playbook": load_playbook(),
        },
        ensure_ascii=False,
    )

    msg = client.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT.format(n_clips=n_clips)},
            {"role": "user", "content": user},
        ]
    )
    plan = _extract_json(msg.get("content") or "")
    plan = validate_plan(plan, n_clips, duration)
    return plan


def _extract_json(text: str) -> dict:
    """从可能带 markdown 围栏的回复里抠 JSON。"""
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"planner 未返回 JSON: {text[:200]}")
    return json.loads(m.group(0))


_FORBIDDEN = re.compile(
    r"\b(people|person|man|woman|girl|boy|child|face|portrait|hand|figure|"
    r"character|human|silhouette|body|crowd|girl)s?\b",
    re.I,
)


def validate_plan(plan: dict, n_clips: int, duration: float) -> dict:
    """确定性校验：段数、prompt 数量、内容安全（禁人物词）。"""
    plan.setdefault("theme", "lyric video scenery")
    plan.setdefault("mood", "cinematic")
    plan.setdefault("font", "STXingkai")
    plan["font"] = (
        plan["font"]
        if plan["font"] in ("STXingkai", "STXinwei", "STLiti", "FZSTK")
        else "STXingkai"
    )
    plan["trim_intro_seconds"] = max(0.0, min(float(plan.get("trim_intro_seconds") or 0), 60.0))

    prompts = [p for p in plan.get("prompts", []) if isinstance(p, str) and p.strip()]
    if len(prompts) != n_clips:
        plan["notes"] = (
            plan.get("notes") or ""
        ) + f" [WARN: planner gave {len(prompts)} prompts, need {n_clips}]"
    prompts = (prompts + _fallback_prompts(n_clips))[:n_clips]
    # 内容安全：禁人物词，命中则替换为中性风景（不重新调 LLM，省时省钱）
    plan["prompts"] = [_sanitize(p) for p in prompts]
    plan["n_clips"] = n_clips
    plan["duration"] = round(duration, 2)
    return plan


def _sanitize(p: str) -> str:
    if _FORBIDDEN.search(p):
        return "Serene natural landscape, vast sky and soft light, no people, cinematic, ultra detailed"
    return p


def _fallback_prompts(n: int) -> list[str]:
    base = [
        "Golden sunrise over misty mountains, hopeful morning light, cinematic, ultra detailed",
        "Vast calm lake reflecting dawn sky, mirror water surface, serene, 4k",
        "Wildflower field under blue sky with soft wind, joyful and bright, 4k",
        "Sunbeams breaking through clouds after rain, hopeful rays, cinematic",
        "Endless road to the horizon across open plains, vast sky, cinematic",
        "Milky way and stars over quiet meadow, dreamy long exposure, 4k",
        "Warm golden sunset over peaceful valley, serene and fulfilling, 4k",
        "Snow mountain range under starry night sky, majestic and quiet, cinematic",
    ]
    return [base[i % len(base)] for i in range(n)]

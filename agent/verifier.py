"""视觉自检（Vision QC）：抽帧 -> 视觉模型逐帧审 -> 生成修复任务。

这一环是全自动流水线补上的最大断点：过去"人物变形无法自动判定，只能靠
用户终审"。现在视觉模型对每段抽帧回答三个问题——
  1) 画面里有没有人物/动物（纯风景政策）？
  2) 有没有明显变形/畸变/AI 痕迹？
  3) 画面是否离题（与 prompt 意象不符）？
不合格的段进入修复循环：改写 prompt（加负面反馈）重新生成，最多 REGEN_ROUNDS 轮。
若 vision 模型未配置，返回空结果并提示人工终审（优雅降级，不阻塞流程）。
"""

from __future__ import annotations

import json
import re

REGEN_ROUNDS = 2
QC_PROMPT = """你是歌词视频的画面质检员。以下是同一段视频按时间顺序抽取的帧（该段的画面）。
逐帧检查并输出 JSON：
{"frames": [{"index": <从0开始>, "verdict": "ok"|"regen", "reason": "<=20字", "revised_prompt": "仅 regen 时给出改写后的英文风景 prompt"}]}
检查项：
1. 出现人物、动物、肢体 → regen（本项目默认纯风景）
2. 明显变形/畸变/扭曲的物体 → regen
3. 画面与"该段意象"完全无关 → regen
只输出 JSON，不要 markdown。"""


def qc_clips(
    client, frames_by_clip: dict[str, list[str]], prompts_by_clip: dict[str, str] | None = None
) -> list[dict]:
    """frames_by_clip: {clip_path: [png,...]}。返回 [{clip, verdict, reason, revised_prompt}]。

    frames_by_clip 里的键顺序即段顺序；无 vision 客户端时返回 []。
    """
    if client is None:
        return []
    prompts_by_clip = prompts_by_clip or {}
    results = []
    for clip, frames in frames_by_clip.items():
        if not frames:
            continue
        raw = client.vision(QC_PROMPT, frames, max_tokens=1024)
        verdicts = _parse(raw)
        bad = [v for v in verdicts if v.get("verdict") == "regen"]
        results.append(
            {
                "clip": clip,
                "verdict": "regen" if bad else "ok",
                "reason": "; ".join(v.get("reason", "") for v in bad)[:200],
                "revised_prompt": (bad[0].get("revised_prompt") or "").strip(),
                "prompt": prompts_by_clip.get(clip, ""),
            }
        )
    return results


def needs_regen(qc_results: list[dict]) -> list[dict]:
    return [r for r in qc_results if r.get("verdict") == "regen"]


def _parse(raw: str) -> list[dict]:
    m = re.search(r"\{.*\}", re.sub(r"```(?:json)?|```", "", raw), re.S)
    if not m:
        return []
    try:
        return json.loads(m.group(0)).get("frames", [])
    except Exception:
        return []

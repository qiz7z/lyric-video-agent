"""CoverAgent —— 封面 Agent（多 Agent 协同的第二主角）。

与视频 Agent 的分工（面试三立论，详见 ARCHITECTURE §5）：
  模态不同（视频 vs 图+文）、QC 闭环不同（人物/变形 vs 文字可读性/竖版构图）、
  生命周期不同（可独立对已有视频补跑，无需重新生片）。

流水线（每步都有降级路径，任何配置缺失都不阻塞）：
  1. 候选帧抽取   正片每段抽 1 帧（或整片均匀 6 帧）
  2. 选帧 [视觉]  视觉模型按"代表性/构图/标题留白"打分选代表帧；无视觉→取中段帧
  3. 封面背景     图片模型按正片意象生成竖版海报背景；无 key→选中帧居中裁成 3:4
  4. 文案 [文本]  文本模型写主标题(≤12字)+署名；无 LLM→歌名/歌手兜底
  5. 排版渲染     纯代码 drawtext（模型负责画面，代码负责文字）
  6. 封面QC [视觉] 文字可读性/构图检查；不合格带反馈重生成背景一次

设计判断：中文文字绝不交给图像模型画（必乱码）——背景归模型，文字归代码。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tools.imagogen import ImageGen, frame_to_vertical
from tools.inspect import extract_frames
from tools.schemas import SEARCH_WEB
from tools.typography import render_cover

PICK_PROMPT = """你是短视频封面选帧师。以下是同一支歌词视频的候选帧（按顺序编号，从0开始）。
选一张最适合做封面主页缩略图的：主题代表性最强、构图最完整、上部有留白可放标题。
只输出 JSON：{"index": <编号>, "reason": "<=20字"}"""

RESEARCH_SYSTEM = """你是封面调研员。任务：在生成封面之前，先搞清这首歌的背景与主题，
让封面"言之有物"而不是看歌词猜意象。
你手上有：歌名/歌手、预取的结构化信息（MusicBrainz/本地元数据，可能为空）、
和一个网页搜索工具。
流程：
1. 先消化已给信息；不足以判断主题就用 search_web 补（1~2 次，关键词自己定，
   如"歌名 歌手 背景"、"歌名 专辑 主题"），读完结果再决定是否还要搜；
2. 信息足够后输出最终 JSON（不要 markdown、不要再调工具）：
{"background": "一句话歌曲背景(中文≤40字)",
 "visual_concept": "封面视觉概念(中文≤30字，抽象意象)",
 "image_prompt": "英文生图提示词：竖版海报构图、纯风景/静物、无文字无人物，把歌曲真实主题转译为视觉语言",
 "title_hint": "给文案的一句话启发(中文≤15字)"}
硬约束：image_prompt 禁止出现具体人物/艺人/IP角色/歌词原文，遵守纯风景政策；
搜索结果仅供参考，不得把未证实的事实写进封面。"""

COPY_PROMPT = """你是短视频封面文案师。根据歌曲信息与画面主题写封面文字。
要求：主标题是情绪短句（不超过12个汉字，不用书名号/引号，可化用歌词但不要整句照抄）；
署名格式"《歌名》 歌手"。若提供了歌曲背景/文案启发，标题应与之呼应。
只输出 JSON：{"title": "<主标题>", "subtitle": "<署名>"}"""

QC_PROMPT = """你是封面质检员。检查这张竖版封面：
1) 文字清晰可读、无乱码、无截断；2) 构图完整、无明显变形；3) 无人脸/人物特写。
只输出 JSON：{"ok": true/false, "issues": ["问题", ...], "background_feedback": "仅 ok=false 时给背景图的改写建议"}"""

COVER_W, COVER_H = 1080, 1440


class CoverAgent:
    def __init__(
        self,
        title: str,
        artist: str = "",
        workdir: str = "",
        llm=None,
        vision=None,
        imagegen: ImageGen | None = None,
        plan: dict | None = None,
        research_fn=None,
        search_fn=None,
    ):
        self.title, self.artist = title, artist
        self.work = Path(workdir)
        self.work.mkdir(parents=True, exist_ok=True)
        self.llm, self.vision, self.imagegen, self.plan = llm, vision, imagegen, plan or {}
        # 调研：research_fn=信息源聚合(结构化元数据/web预取)，search_fn=网页搜索工具
        self.research_fn, self.search_fn = research_fn, search_fn
        self.research: dict = {"mode": "skipped"}
        self.decisions: dict = {"agent": "cover", "title": title, "steps": {}}

    # ---- 主流程 ----
    def run(self, video_path: str | None = None, clips: list[str] | None = None) -> dict:
        """兼容入口：headless 主链 + 可选帧源。

        video_path/clips 只是「帧源」：有图片模型时主链完全不需要它，
        仅帧降级路径（无 key / 生图失败）消费选帧结果。
        """
        return self.run_headless(frame_source=video_path, clips=clips)

    def run_headless(self, frame_source: str | None = None, clips: list[str] | None = None) -> dict:
        """零视频依赖的封面主链：调研 → (可选选帧) → 背景 → 文案 → 排版 → QC。

        并行化关键：不传帧源时照常产出——背景走图片模型主路径（prompt 来自
        调研产出），与正片是否存在无关。唯一无法出图的组合是「无图片模型
        且 无帧源」，此时抛错由编排器在正片就绪后兜底。
        """
        self._step_research()
        frames = self._step_candidates(frame_source, clips) if (frame_source or clips) else []
        picked = self._step_pick(frames) if frames else ""
        bg = self._step_background(picked)
        copy = self._step_copy()
        cover = self._step_render(bg, copy)
        self._step_qc(cover, bg, copy)
        self.decisions["cover"] = cover
        (self.work / "cover_decision.json").write_text(
            json.dumps(self.decisions, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"[cover] 完成: {cover}")
        return self.decisions

    # ---- 0. 调研 [LLM决策点：文本+工具循环] ----
    def _step_research(self) -> None:
        """歌名 → 搜背景 → 视觉概念 → 英文生图提示词（先理解这首歌，再决定画什么）。"""
        if self.llm is None or (self.research_fn is None and self.search_fn is None):
            self.decisions["steps"]["research"] = {
                "mode": "skipped",
                "note": "未配置调研源，走 plan.theme",
            }
            return
        pkg = {}
        if self.research_fn:
            try:
                pkg = self.research_fn() or {}
            except Exception as e:
                print(f"[research] 信息源聚合失败: {str(e)[:80]}")
        messages = [
            {"role": "system", "content": RESEARCH_SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "cover_research",
                        "title": self.title,
                        "artist": self.artist,
                        "plan_theme": self.plan.get("theme", ""),
                        "sources": pkg,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        searches: list[str] = []
        try:
            for _ in range(4):  # 工具循环上限（含最终答复轮）
                msg = self.llm.chat(messages, tools=[SEARCH_WEB])
                calls = msg.get("tool_calls") or []
                if not calls:
                    final = json.loads(
                        re.search(r"\{.*\}", msg.get("content") or "{}", re.S).group(0)
                    )
                    self.research = {"mode": "llm", "searches": searches, **final}
                    self.decisions["steps"]["research"] = {
                        "mode": "llm",
                        "searches": searches,
                        "background": final.get("background", "")[:60],
                        "visual_concept": final.get("visual_concept", "")[:40],
                    }
                    print(f"[research] 背景: {final.get('background', '')[:50]}")
                    print(f"[research] 概念: {final.get('visual_concept', '')}")
                    return
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.get("content") or None,
                        "tool_calls": calls,
                    }
                )
                query = json.loads(calls[0]["function"].get("arguments") or "{}").get("query", "")
                results = self.search_fn(query) if self.search_fn else []
                searches.append(query)
                print(f"[research] 搜索: {query} -> {len(results)} 条")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": calls[0].get("id") or "call_0",
                        "content": json.dumps(results, ensure_ascii=False)[:2000],
                    }
                )
            self.research = {"mode": "llm", "searches": searches}  # 轮次耗尽无终答
        except Exception as e:
            print(f"[research] 调研失败（{str(e)[:80]}），降级 plan.theme")
            self.research = {"mode": "error", "note": str(e)[:120]}
        self.decisions["steps"]["research"] = {
            "mode": self.research.get("mode"),
            "searches": searches,
        }

    # ---- 1. 候选帧 ----
    def _step_candidates(self, video_path, clips) -> list[str]:
        out = self.work / "cover_frames"
        if clips:
            frames = []
            for i, c in enumerate(clips, 1):
                if Path(c).exists():
                    frames += extract_frames(c, [8.0], str(out), prefix=f"cand{i:02d}")
        else:
            frames = (
                extract_frames(video_path, [30, 60, 90, 120, 150, 180], str(out), prefix="cand")
                if video_path
                else []
            )
        self.decisions["steps"]["candidates"] = len(frames)
        print(f"[cover] 候选帧 {len(frames)}")
        return frames

    # ---- 2. 选帧 [LLM决策点：视觉] ----
    def _step_pick(self, frames: list[str]) -> str:
        if not frames:
            raise RuntimeError("无候选帧可选取（视频与 clips 均缺失）")
        if self.vision and len(frames) > 1:
            try:
                raw = self.vision.vision(PICK_PROMPT, frames, max_tokens=200)
                m = re.search(r"\{.*\}", raw, re.S)
                idx = int(json.loads(m.group(0))["index"]) if m else 0
                idx = max(0, min(idx, len(frames) - 1))
                self.decisions["steps"]["pick"] = {"mode": "vision", "index": idx}
                print(f"[cover] 视觉选帧 #{idx}")
                return frames[idx]
            except Exception as e:
                print(f"[cover] 视觉选帧失败（{str(e)[:80]}），用启发式")
        pick = frames[len(frames) // 2]  # 启发式：中段帧（多为副歌附近）
        self.decisions["steps"]["pick"] = {"mode": "heuristic", "frame": Path(pick).name}
        return pick

    # ---- 3. 背景（图模型 / 帧降级）----
    def _step_background(self, picked_frame: str) -> str:
        bg_out = self.work / "cover_bg.png"
        if self.imagegen is None:
            if not picked_frame:
                raise RuntimeError(
                    "封面降级需要帧源（无图片模型 key 且无正片/clips），等正片就绪后重跑封面即可"
                )
            print("[cover] 无图片模型 key：用选中帧裁竖版做背景（降级）")
            self.decisions["steps"]["background"] = {"mode": "frame_fallback"}
            return frame_to_vertical(picked_frame, str(bg_out), COVER_W, COVER_H)
        # 调研产出的生图提示词优先（先理解这首歌，再决定画什么）；否则用 plan 主题
        if self.research.get("mode") == "llm" and self.research.get("image_prompt"):
            base = self.research["image_prompt"]
            mood = self.research.get("visual_concept", self.plan.get("mood", "cinematic"))
        else:
            base = self.plan.get("theme", "serene cinematic scenery")
            mood = self.plan.get("mood", "cinematic")
        prompt = (
            f"Vertical poster background art, no text, no people: {base}. "
            f"Mood: {mood}. Composition: soft upper area left clean for a title, "
            f"rich detail in the middle, cinematic lighting, ultra detailed, 4k"
        )
        try:
            # 幂等键 = 提示词内容哈希：调研产出新提示词时自动失效旧缓存
            prompt_hash = __import__("hashlib").md5(prompt.encode("utf-8")).hexdigest()[:8]
            raw_bg = self.imagegen.generate(
                prompt,
                str(self.work / f"cover_bg_raw_{prompt_hash}.png"),
                size=f"{COVER_W}x{COVER_H}",
            )
            from tools.imagogen import scale_to

            print("[cover] 图片模型生成竖版背景")
            self.decisions["steps"]["background"] = {"mode": "image_model", "prompt": prompt[:160]}
            return scale_to(raw_bg, str(bg_out), COVER_W, COVER_H)
        except Exception as e:
            print(f"[cover] 图片模型失败（{str(e)[:80]}）：降级用选中帧")
            self.decisions["steps"]["background"] = {
                "mode": "frame_fallback",
                "reason": str(e)[:120],
            }
            if not picked_frame:
                # headless 无视频场景：图片模型失败且无帧源可降级，
                # 抛出清晰错误由外层（run_headless 调用方 / 编排器 join 兜底）捕获
                raise RuntimeError(
                    "图片模型生成失败且无帧源可降级（headless 无视频场景）："
                    "等正片就绪后重跑封面即可"
                ) from None
            return frame_to_vertical(picked_frame, str(bg_out), COVER_W, COVER_H)

    # ---- 4. 文案 [LLM决策点：文本] ----
    def _step_copy(self) -> dict:
        user = json.dumps(
            {
                "task": "cover_copy",
                "title": self.title,
                "artist": self.artist,
                "theme": self.plan.get("theme", ""),
                "background": self.research.get("background", ""),
                "title_hint": self.research.get("title_hint", ""),
            },
            ensure_ascii=False,
        )
        if self.llm is not None:
            try:
                msg = self.llm.chat(
                    [{"role": "system", "content": COPY_PROMPT}, {"role": "user", "content": user}]
                )
                copy = json.loads(re.search(r"\{.*\}", msg.get("content") or "{}", re.S).group(0))
                title = str(copy.get("title") or self.title).strip()[:14]
                subtitle = str(copy.get("subtitle") or f"《{self.title}》 {self.artist}").strip()[
                    :30
                ]
                self.decisions["steps"]["copy"] = {"mode": "llm", "title": title}
                print(f"[cover] 文案: {title} / {subtitle}")
                return {"title": title, "subtitle": subtitle}
            except Exception as e:
                print(f"[cover] 文案生成失败（{str(e)[:80]}），用歌名兜底")
        copy = {"title": self.title[:14], "subtitle": f"《{self.title}》 {self.artist}".strip()}
        self.decisions["steps"]["copy"] = {"mode": "fallback", "title": copy["title"]}
        return copy

    # ---- 5. 排版（纯代码）----
    def _step_render(self, bg: str, copy: dict) -> str:
        out = self.work / "cover_final.png"
        render_cover(bg, copy["title"], copy["subtitle"], str(out), str(self.work))
        self.decisions["steps"]["render"] = {"output": out.name}
        return str(out)

    # ---- 6. 封面QC [LLM决策点：视觉] ----
    def _step_qc(self, cover: str, bg: str, copy: dict) -> None:
        if self.vision is None:
            self.decisions["steps"]["qc"] = {
                "mode": "skipped",
                "note": "未配置视觉模型，请人工终审",
            }
            print("[cover] 未配置视觉模型：请人工终审封面")
            return
        try:
            raw = self.vision.vision(QC_PROMPT, [cover], max_tokens=300)
            m = re.search(r"\{.*\}", raw, re.S)
            verdict = json.loads(m.group(0)) if m else {"ok": True}
            self.decisions["steps"]["qc"] = {"mode": "vision", **verdict}
            print(f"[cover] QC: ok={verdict.get('ok')} issues={verdict.get('issues')}")
            if not verdict.get("ok") and self.imagegen is not None:
                feedback = verdict.get("background_feedback") or "cleaner composition"
                bg2 = self.work / f"cover_bg_repair_{abs(hash(feedback)) % 99999}.png"
                prompt = (
                    f"Vertical poster background, no text, no people: "
                    f"{self.plan.get('theme', 'cinematic scenery')}. "
                    f"Fix: {feedback}. Cinematic, ultra detailed"
                )
                raw_bg = self.imagegen.generate(prompt, str(bg2), size=f"{COVER_W}x{COVER_H}")
                from tools.imagogen import scale_to
                from tools.typography import render_cover as rc

                bg_std = scale_to(raw_bg, str(self.work / "cover_bg_std_v2.png"), COVER_W, COVER_H)
                cover2 = rc(
                    bg_std,
                    copy["title"],
                    copy["subtitle"],
                    str(self.work / "cover_final.png"),
                    str(self.work),
                )
                self.decisions["steps"]["qc"]["repaired"] = True
                self.decisions["cover"] = cover2
                print("[cover] QC 不合格已重生成一次")
        except Exception as e:
            self.decisions["steps"]["qc"] = {"mode": "error", "note": str(e)[:150]}

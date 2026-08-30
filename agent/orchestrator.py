# -*- coding: utf-8 -*-
"""Orchestrator：确定性流水线骨架 + LLM 决策点（混合式 Agent 架构）。

流水线（每级幂等，文件已存在即跳过 => 天然支持断点续跑）：
  Stage 1 歌词      内嵌 LRC 优先 -> LRCLib 兜底
  Stage 2 规划  [LLM决策点1] 主题/意象/风格/段数（Planner + 确定性校验）
  Stage 3 分离      demucs 人声（不可用则降级全曲包络并记入报告）
  Stage 4 对齐      三路路由 -> events.json + report.json
  Stage 5 验证片    黑底白字（便宜可重渲，先确认对齐）
  Stage 6 人工闸门  听感确认后才进入昂贵环节（默认开，--yes 跳过）
  Stage 7 生片  [昂贵]  Agnes 逐段生成（限流/续传全封装）
  Stage 8 视觉自检  [LLM决策点2] 抽帧 -> 视觉模型 -> 修复循环（≤2轮）
  Stage 9 合成      xfade + 烧字幕 + 原曲立体声（NVENC，失败回退 libx264）
  Stage 10 沉淀     run report + lessons 追加（记忆回写）

为什么不全用 LLM 循环驱动（ReAct free-loop）？见 ARCHITECTURE.md——
成本、延迟、确定性三重考虑；LLM 只出现在需要判断力的两个决策点。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from tools import align as align_mod
from tools import ass as ass_mod
from tools import audio as audio_mod
from tools import compose as compose_mod
from tools import inspect as inspect_mod
from tools import lyrics as lyrics_mod
from tools import videogen as videogen_mod
from . import memory as mem
from . import planner as planner_mod
from . import verifier as verifier_mod

CLIP_DUR, XF, FPS = 15.06, 0.3, 30


class Orchestrator:
    def __init__(self, title: str, audio: str, artist: str = "",
                 mock: bool = False, yes: bool = False, skip_generate: bool = False,
                 skip_qc: bool = False, skip_repair: bool = False,
                 skip_cover: bool = False, trim: float | None = None):
        self.title, self.artist = title, artist
        self.audio = str(Path(audio).resolve())
        self.mock, self.yes = mock, yes
        self.skip_generate, self.skip_qc = skip_generate, skip_qc
        self.skip_repair, self.skip_cover = skip_repair, skip_cover
        self.trim_override = trim
        self.cfg = None if mock else _load_cfg()
        self.llm = self._make_llm()
        self.vision = self._make_vision()
        self.work = mem.run_dir(title)
        self.stage_results: dict = {}

    # ---------- 各决策点 ----------
    def _make_llm(self):
        if self.mock:
            from .llm import MockLLM
            return MockLLM()
        llm_cfg = (self.cfg or {}).get("llm", {})
        if not llm_cfg.get("api_key"):
            print(">> 未配置 LLM key，自动切换 mock 模式（--mock 可显式指定）")
            self.mock = True
            from .llm import MockLLM
            return MockLLM()
        from .llm import LLMClient
        return LLMClient(llm_cfg["base_url"], llm_cfg["api_key"], llm_cfg["model"])

    def _make_vision(self):
        if self.mock:
            from .llm import MockLLM
            return MockLLM()
        v = (self.cfg or {}).get("vision", {})
        if not v.get("model") or not v.get("api_key"):
            return None
        from .llm import LLMClient
        return LLMClient(v["base_url"], v["api_key"], v["model"])

    # ---------- 主流程 ----------
    def run(self) -> dict:
        t0 = time.time()
        print(f"=== 歌词视频 Agent：{self.title} ===")
        print(f"工作区: {self.work}")
        audio = self._stage_audio()
        ly = self._stage_lyrics(audio)
        plan = self._stage_plan(ly, audio["duration"])
        env = self._stage_align(audio, ly, plan)
        verify = self._stage_verify(audio, env)
        self._stage_gate(verify)
        clips = self._stage_generate(plan)
        clips = self._stage_qc(plan, clips)
        final = self._stage_compose(audio, plan, env, clips)
        cover = self._stage_cover(plan, final, clips)
        report = self._stage_report(plan, env, clips, final, cover, time.time() - t0)
        return report

    # Stage 0
    def _stage_audio(self) -> dict:
        duration = audio_mod.probe_duration(self.audio)
        src = self.work / "source.wav"
        if not (src.exists() and src.stat().st_size > 100_000):
            audio_mod.decode_wav(self.audio, str(src), stereo=True)
        print(f"[audio] {duration:.1f}s, source.wav 就绪")
        return {"duration": duration, "wav": str(src)}

    # Stage 1
    def _stage_lyrics(self, audio: dict):
        raw = self.work / "lyrics_raw.txt"
        if raw.exists():
            lines = []
            for line in raw.read_text(encoding="utf-8").splitlines():
                if "\t" in line and not line.startswith("#"):
                    t, s = line.split("\t", 1)
                    lines.append((float(t), s))
            ly = lyrics_mod.Lyrics(self.title, self.artist, lines, "cached")
            print(f"[lyrics] 复用缓存 {len(lines)} 句")
            return ly
        ly = lyrics_mod.load_lyrics(self.audio, self.title, self.artist, audio["duration"])
        if not ly.lines:
            raise SystemExit("拿不到歌词：无内嵌 LRC 且 LRCLib 未命中，请手动放置 lyrics_raw.txt")
        lyrics_mod.save_raw(ly, str(raw))
        print(f"[lyrics] source={ly.source}, {len(ly.lines)} 句")
        return ly

    # Stage 2 [LLM决策点1]
    def _stage_plan(self, ly, duration: float) -> dict:
        plan_file = self.work / "plan.json"
        if plan_file.exists():
            plan = json.loads(plan_file.read_text(encoding="utf-8"))
            print(f"[plan] 复用已有计划: theme={plan.get('theme')}, n_clips={plan.get('n_clips')}")
            return plan
        preview = "\n".join(s for _, s in ly.lines[:12])
        plan = planner_mod.build_plan(self.llm, self.title, self.artist, duration,
                                      preview, len(ly.lines))
        plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"[plan] theme={plan['theme']} | {plan['n_clips']} 段 | 字体 {plan['font']}"
              f" | 裁前奏 {plan['trim_intro_seconds']}s")
        for i, p in enumerate(plan["prompts"][:3], 1):
            print(f"   prompt{i}: {p[:70]}...")
        return plan

    # Stage 3 + 4
    def _stage_align(self, audio: dict, ly, plan: dict) -> dict:
        ev_file = self.work / "events.json"
        if ev_file.exists():
            events = json.loads(ev_file.read_text(encoding="utf-8"))
            report = json.loads((self.work / "report.json").read_text(encoding="utf-8"))
            print(f"[align] 复用已有对齐（route={report.get('route')}）")
            return {"events": events, "report": report}
        trim = self.trim_override if self.trim_override is not None \
            else float(plan.get("trim_intro_seconds") or 0)
        try:
            vocals = audio_mod.separate_vocals(audio["wav"], str(self.work))
            env = audio_mod.rms_envelope(vocals)
            print(f"[separate] demucs vocals 就绪")
        except Exception as e:
            print(f"[separate] demucs 不可用（{str(e)[:80]}），降级全曲包络")
            env = audio_mod.rms_envelope(audio["wav"])
        events, report = align_mod.align(env, ly.lines, audio["duration"], trim=trim)

        # 修复循环 [LLM决策点2]：降级路由时 LLM 通过 function calling 决策修复动作
        if report.get("route") == "interp" and not self.skip_repair:
            events, report = self._stage_repair(env, ly, audio, events, report, trim)

        (self.work / "events.json").write_text(
            json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")
        (self.work / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        # 对齐重算 => 验证片/成片是派生产物，作废防止复用过期缓存
        for pattern in ("*_字幕验证版.mp4", "*_歌词视频.mp4"):
            for stale in self.work.glob(pattern):
                stale.unlink()
                print(f"[align] 已作废过期产物: {stale.name}")
        print(f"[align] route={report['route']} ratio={report['ratio_onset_to_line']} "
              f"n={report['n_lyrics']}/{report['n_onsets']} "
              f"delta_mean={report.get('delta_abs_mean')}s max={report.get('delta_abs_max')}s")
        return {"events": events, "report": report}

    # Stage 5
    def _stage_repair(self, env, ly, audio: dict, events, report, trim):
        """[LLM决策点2] function-calling 修复循环：诊断 -> 选工具 -> 质量门槛把关。"""
        from .repair import RepairLoop

        def realign(merge_gap=None, thr_low=None, thr_high=None, trim=None):
            t = self.trim_override if self.trim_override is not None \
                else (trim if trim is not None else 0.0)
            return align_mod.align(env, ly.lines, audio["duration"], trim=t,
                                   merge_gap=merge_gap, thr_low=thr_low, thr_high=thr_high)

        loop = RepairLoop(self.llm, realign, max_rounds=3)
        events, report, history = loop.run(events, report)
        for h in history:
            cand = h.get("candidate")
            extra = f" -> {cand['route']} dmax={cand['delta_abs_max']}" if cand else ""
            print(f"[repair] r{h['round']}: {h['action']} {h.get('args', '')}"
                  f"{extra} [{h.get('result', h.get('note', ''))}]")
        print(f"[repair] 最终 route={report['route']}")
        return events, report

    def _stage_verify(self, audio: dict, env: dict) -> str:
        out = self.work / f"{mem.safe_name(self.title)}_字幕验证版.mp4"
        vp, _ = ass_mod.write_two_versions(env["events"], str(self.work),
                                           font=self._font())
        if out.exists() and out.stat().st_size > 100_000:
            print(f"[verify] 复用已有验证片: {out.name}")
        else:
            compose_mod.compose_verify(audio["wav"], vp, str(out), str(self.work),
                                       fps=FPS, encoder="nvenc")
        print(f"[verify] {out.name} ({out.stat().st_size / 1048576:.1f} MB) "
              f"-> 请听感确认字幕对齐")
        return str(out)

    def _font(self) -> str:
        plan_file = self.work / "plan.json"
        if plan_file.exists():
            return json.loads(plan_file.read_text(encoding="utf-8")).get("font", "STXingkai")
        return "STXingkai"

    # Stage 6 人工闸门
    def _stage_gate(self, verify: str) -> None:
        if self.yes:
            print("[gate] --yes：跳过人工确认")
            return
        if not sys.stdin.isatty():
            print("[gate] 非交互环境，默认继续（正式运行请人工听感确认验证片）")
            return
        ans = input(f"\n>> 请先观看 {verify}\n>> 听感对齐是否通过？[y/N] ").strip().lower()
        if ans != "y":
            raise SystemExit("已暂停：调整锚点/重跑对齐后再次运行（已有产物会自动复用）。")

    # Stage 7 [昂贵]
    def _stage_generate(self, plan: dict) -> list[str]:
        clips_dir = self.work / "clips"
        existing = self._collect_clips(clips_dir, plan["n_clips"])
        if self.skip_generate:
            print(f"[generate] --skip-generate：使用已有 {len(existing)}/{plan['n_clips']} 段")
            return existing
        key = ((self.cfg or {}).get("agnes") or {}).get("api_key") or \
            _read_legacy_key()
        if not key:
            print("[generate] 未配置 Agnes key：跳过生片，仅输出验证片。")
            return existing
        proxies = ((self.cfg or {}).get("agnes") or {}).get("proxies")
        gen = videogen_mod.VideoGen(key, proxies)
        print(f"[generate] {plan['n_clips']} 段，每段 ~15s@1080p，幂等续传")
        for i, prompt in enumerate(plan["prompts"], 1):
            gen.generate(prompt, str(clips_dir / f"clip{i:02d}.mp4"),
                         num_frames=241, frame_rate=16)
        return self._collect_clips(clips_dir, plan["n_clips"])

    @staticmethod
    def _collect_clips(clips_dir: Path, n: int) -> list[str]:
        return [str(clips_dir / f"clip{i:02d}.mp4")
                for i in range(1, n + 1)
                if (clips_dir / f"clip{i:02d}.mp4").exists()]

    # Stage 8 [LLM决策点2] 视觉自检 + 修复循环
    def _stage_qc(self, plan: dict, clips: list[str]) -> list[str]:
        if self.skip_qc:
            print("[qc] --skip-qc：跳过视觉自检（请人工终审画面）")
            return clips
        if self.vision is None:
            print("[qc] 未配置视觉模型：跳过自动质检，请人工终审画面变形/人物")
            return clips
        clips_dir = self.work / "clips"
        key = ((self.cfg or {}).get("agnes") or {}).get("api_key") or _read_legacy_key()
        for round_no in range(1, verifier_mod.REGEN_ROUNDS + 1):
            frames_by_clip, prompts_by_clip = {}, {}
            for i, clip in enumerate(clips, 1):
                if not Path(clip).exists():
                    continue
                frames = inspect_mod.extract_frames(clip, [5, 11], str(self.work / "qc"),
                                                    prefix=f"clip{i:02d}")
                frames_by_clip[clip] = frames
                prompts_by_clip[clip] = plan["prompts"][i - 1] if i - 1 < len(plan["prompts"]) else ""
            qc = verifier_mod.qc_clips(self.vision, frames_by_clip, prompts_by_clip)
            bad = verifier_mod.needs_regen(qc)
            print(f"[qc] round{round_no}: {len(qc)} 段受检, {len(bad)} 段需重生成")
            if not bad:
                break
            if not key:
                print("[qc] 无 Agnes key，无法自动重生成，请人工处理")
                break
            proxies = ((self.cfg or {}).get("agnes") or {}).get("proxies")
            gen = videogen_mod.VideoGen(key, proxies)
            for r in bad:
                clip = r["clip"]
                new_prompt = r.get("revised_prompt") or \
                    f"{r.get('prompt','pure landscape scenery')}, strict no people, stable geometry, no distortion"
                print(f"[qc] 重新生成 {Path(clip).name}: {r['reason']}")
                Path(clip).unlink(missing_ok=True)   # 强制重生成（幂等保护先移除）
                gen.generate(new_prompt, clip, num_frames=241, frame_rate=16)
        return clips

    # Stage 9
    def _stage_compose(self, audio: dict, plan: dict, env: dict, clips: list[str]) -> str:
        out = self.work / f"{mem.safe_name(self.title)}_歌词视频.mp4"
        if out.exists() and out.stat().st_size > 1_000_000:
            print(f"[compose] 复用已有正式片: {out.name}")
            return str(out)
        if len(clips) < plan["n_clips"]:
            msg = f"片段不齐（{len(clips)}/{plan['n_clips']}）"
            if self.skip_generate:
                print(f"[compose] {msg} 且 --skip-generate：跳过正式合成（验证片已可确认对齐）")
                return ""
            raise SystemExit(f"{msg}，先补齐 clips 再合成。")
        _, fp = ass_mod.write_two_versions(env["events"], str(self.work),
                                           font=plan.get("font", "STXingkai"))
        compose_mod.compose_final(clips, audio["wav"], fp, str(out), str(self.work),
                                  dur=CLIP_DUR, xf=XF, fps=FPS, encoder="nvenc")
        return str(out)

    # Stage 9.5 封面 Agent（多 Agent 协同：视频 Agent 产出 -> 封面 Agent 接力）
    def _stage_cover(self, plan: dict, final: str, clips: list[str]) -> dict | None:
        if self.skip_cover:
            print("[cover] --skip-cover：跳过封面 Agent")
            return None
        from .cover import CoverAgent
        from tools.imagogen import ImageGen

        agnes = (self.cfg or {}).get("agnes") or {}
        key = agnes.get("api_key") or _read_legacy_key()
        # mock 模式强制禁用图片生成（离线测试绝不花钱），走帧降级路径
        imagegen = None
        if key and not self.mock:
            imagegen = ImageGen(key, base_url=agnes.get("base_url",
                                                        "https://apihub.agnes-ai.com/v1"),
                                model=agnes.get("image_model", "agnes-image-2.1-flash"),
                                proxies=agnes.get("proxies"))
        # 调研函数（真实模式才挂网：信息源聚合 + 网页搜索工具）
        research_fn = search_fn = None
        if not self.mock:
            from tools import research as research_mod
            proxies = agnes.get("proxies")
            research_fn = lambda: research_mod.research_package(
                self.title, self.artist, audio_path=self.audio, proxies=proxies)
            search_fn = lambda q: research_mod.search_web(q, proxies=proxies)
        agent = CoverAgent(title=self.title, artist=self.artist, workdir=str(self.work),
                           llm=self.llm, vision=self.vision, imagegen=imagegen, plan=plan,
                           research_fn=research_fn, search_fn=search_fn)
        real_clips = [c for c in clips if Path(c).exists()]
        try:
            if final and Path(final).exists():
                return agent.run(video_path=final)
            if real_clips:
                return agent.run(clips=real_clips)
        except Exception as e:
            print(f"[cover] 封面 Agent 失败（{str(e)[:100]}），不阻塞主流程")
            return None
        print("[cover] 无视频/clips 源，跳过封面")
        return None

    # Stage 10 沉淀
    def _stage_report(self, plan, env, clips, final, cover, elapsed) -> dict:
        info = inspect_mod.probe_video(final) if final and Path(final).exists() else {}
        report = {
            "title": self.title,
            "plan_theme": plan.get("theme"),
            "n_clips": plan.get("n_clips"),
            "clips_ready": len([c for c in clips if Path(c).exists()]),
            "align": env["report"],
            "final_video": final,
            "final_probe": {k: info.get(k) for k in ("duration",)},
            "cover": (cover or {}).get("cover"),
            "elapsed_sec": round(elapsed, 1),
            "mock": self.mock,
        }
        (self.work / "run_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        mem.append_lesson({
            "song": self.title,
            "route": env["report"].get("route"),
            "delta_mean": env["report"].get("delta_abs_mean"),
            "delta_max": env["report"].get("delta_abs_max"),
            "n_clips": plan.get("n_clips"),
            "note": plan.get("notes", ""),
        })
        print(f"[done] {final}")
        return report


def _load_cfg() -> dict:
    from .llm import load_config
    return load_config()


def _read_legacy_key() -> str:
    """兼容老工作区：项目根或上一级（抖音投稿目录）的 api-key.txt，不进 git。"""
    here = Path(__file__).resolve().parent
    for p in (here / "api-key.txt", here.parent / "api-key.txt"):
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip()
            except Exception:
                continue
    return ""

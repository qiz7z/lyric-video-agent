"""ASS 生成 + 编排器离线冒烟（MockLLM 规划链路 + 校验规则）。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_ass():
    from tools import ass as ass_mod

    events = [
        {"start": 23.394, "end": 25.174, "text": "奔跑在{人群}里面"},
        {"start": 210.0, "end": 216.0, "text": "幸福终点"},
    ]
    vp, fp = ass_mod.write_two_versions(events, str(ROOT / "runs" / "_test"))
    v = Path(vp).read_text(encoding="utf-8")
    f = Path(fp).read_text(encoding="utf-8")
    assert "\\fad(150,180)" in v and "\\be1" in v, "必须只含 fad+be 渲染"
    assert "\\t(" not in v, "禁止 \\t 动画（SOP 硬规则）"
    assert "0:00:23.39" in v, "时间格式错误"
    assert "\\{人群\\}" in v, "花括号须转义"
    assert "STXingkai,84" in f and "STXingkai,72" in v, "两套字号"
    print("PASS test_ass")


def test_planner_mock():
    from agent.llm import MockLLM
    from agent.planner import build_plan
    from tools.compose import clip_count_for

    duration = 231.59
    n_expect = clip_count_for(duration)
    assert n_expect == 16, f"覆盖公式: 231.59s 应 16 段, got {n_expect}"

    plan = build_plan(MockLLM(), "测试歌", "测试歌手", duration, "歌词预览\n第二句", 62)
    assert plan["n_clips"] == 16, f"段数: {plan['n_clips']}"
    assert len(plan["prompts"]) == 16, f"prompt 数: {len(plan['prompts'])}"
    assert plan["font"] in ("STXingkai", "STXinwei", "STLiti", "FZSTK")

    # 内容安全：含人物词的 prompt 必须被替换
    plan["prompts"][0] = "A girl walking in the rain, cinematic"
    from agent.planner import validate_plan

    plan = validate_plan(plan, 16, duration)
    assert "girl" not in plan["prompts"][0].lower(), "人物词必须被净化"
    print("PASS test_planner_mock")


def test_compose_smoke():
    """用《梦的光点》真实片段+音频做 2 段小样合成（NVENC 链路）。"""
    src = Path(r"C:\Users\liuqi\Desktop\抖音投稿\梦的光点\工作区")
    clips_src = src / "mgd_clips"
    audio = src / "source.wav"
    if not (clips_src / "mgd1.mp4").exists() or not audio.exists():
        print("SKIP: 梦的光点工作区数据缺失")
        return
    from tools import audio as audio_mod
    from tools import compose as compose_mod

    work = ROOT / "runs" / "_test"
    work.mkdir(parents=True, exist_ok=True)
    short_wav = work / "short.wav"
    if not short_wav.exists():
        audio_mod.decode_wav(str(audio), str(short_wav))
        # 截前 30s，缩短编码时间
        import subprocess

        from tools.audio import get_ffmpeg

        subprocess.run(
            [get_ffmpeg(), "-y", "-i", str(short_wav), "-t", "30", str(work / "short30.wav")],
            capture_output=True,
        )
        short_wav.unlink()
        (work / "short30.wav").replace(short_wav)

    # 验证片：黑底白字
    events = [
        {"start": 1.0, "end": 6.0, "text": "对齐冒烟测试"},
        {"start": 8.0, "end": 14.0, "text": "唱完即清"},
    ]
    from tools import ass as ass_mod

    vp, _ = ass_mod.write_two_versions(events, str(work))
    vout = work / "smoke_验证版.mp4"
    compose_mod.compose_verify(str(short_wav), vp, str(vout), str(work), fps=30, encoder="nvenc")
    assert vout.stat().st_size > 100_000, "验证片过小"

    # 正式片小样：2 段 xfade（用验证版 ASS 便于肉眼比对）
    fout = work / "smoke_正式版.mp4"
    compose_mod.compose_final(
        [str(clips_src / "mgd1.mp4"), str(clips_src / "mgd2.mp4")],
        str(short_wav),
        vp,
        str(fout),
        str(work),
        dur=3.0,
        xf=0.3,
        fps=30,
        encoder="nvenc",
    )
    assert fout.stat().st_size > 500_000, "正式小样过小"
    print(
        f"PASS test_compose_smoke (验证 {vout.stat().st_size // 1024}KB, "
        f"正式 {fout.stat().st_size // 1024}KB)"
    )


def test_repair_loop():
    """修复循环：MockLLM 剧本 = re_align(被质量门槛拒绝) -> accept。
    用合成包络构造 interp 场景（5 段 vs 8 行），不依赖任何外部数据。"""
    import contextlib
    import io

    import numpy as np

    from agent.llm import MockLLM
    from agent.repair import RepairLoop
    from tools import align as align_mod

    sr_hop = 512 / 22050
    times = np.arange(0, 30, sr_hop)
    rms = np.zeros_like(times)
    for start in (2.0, 7.0, 12.0, 17.0, 22.0):  # 5 个清晰演唱段
        mask = (times > start) & (times < start + 1.8)
        rms[mask] = 1.0
    lines = [(2.0 + i * 3.2, f"第{i}句歌词") for i in range(8)]  # 8 行 > 5 段

    events0, report0 = align_mod.align((rms, times), lines, 30.0)
    assert report0["route"] == "interp", f"应构造出 interp: {report0['route']}"

    def realign(merge_gap=None, thr_low=None, thr_high=None, trim=None):
        return align_mod.align(
            (rms, times),
            lines,
            30.0,
            trim=trim or 0.0,
            merge_gap=merge_gap,
            thr_low=thr_low,
            thr_high=thr_high,
        )

    with contextlib.redirect_stdout(io.StringIO()):
        events, report, history = RepairLoop(MockLLM(), realign).run(events0, report0)
    assert len(history) == 2, f"剧本应为 re_align->accept 两步: {history}"
    assert history[0]["action"] == "re_align" and history[0]["result"].startswith("REJECTED"), (
        f"merge_gap=0.22 应被门槛拒绝: {history[0]}"
    )
    assert history[1]["action"] == "accept"
    assert report["repair_history"], "决策历史必须落进报告"
    starts = [e["start"] for e in events]
    assert all(b >= a for a, b in zip(starts, starts[1:], strict=False)), "回退后事件须保持单调"
    print("PASS test_repair_loop")


def main():
    test_ass()
    test_planner_mock()
    test_repair_loop()
    test_compose_smoke()
    print("PASS test_orchestrator (all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

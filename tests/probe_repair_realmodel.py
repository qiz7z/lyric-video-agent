"""真模型修复循环探针（需要 LLM key + 已交付歌曲的中间产物）。

与 tests/ 下其他脚本一致：数据或 key 缺失时自动 SKIP，不阻塞 CI。
用途：验证 repair 的 LLM 决策路径在真实模型下的行为——这是 MockLLM
覆盖不到的部分（工具选择偏好、参数抖动、对拒绝反馈的反应）。

跑法：
    .venv/Scripts/python tests/probe_repair_realmodel.py

产出：runs/梦的光点/repair_real_trajectory.json（模型名 + 决策历史 + 终态报告）
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WORK = Path(__file__).resolve().parent.parent / "runs" / "梦的光点"

# 缺数据 -> SKIP（CI 友好，与项目其他测试一致）
if not (WORK / "lyrics_raw.txt").exists() or not (WORK / "source.wav").exists():
    print("SKIP probe_repair_realmodel: 缺少 runs/梦的光点 中间产物")
    sys.exit(0)

from agent import llm as llm_mod  # noqa: E402
from agent.repair import RepairLoop  # noqa: E402
from tools import align as align_mod  # noqa: E402
from tools import audio as audio_mod  # noqa: E402

cfg = llm_mod.load_config()
if not cfg.get("llm", {}).get("api_key"):
    print("SKIP probe_repair_realmodel: 未配置 LLM key（config.json 或 LVA_LLM_API_KEY）")
    sys.exit(0)


# 1) 歌词（复用缓存）
lines = []
for line in (WORK / "lyrics_raw.txt").read_text(encoding="utf-8").splitlines():
    if "\t" in line and not line.startswith("#"):
        t, s = line.split("\t", 1)
        lines.append((float(t), s))
print(f"[lyrics] 复用缓存 {len(lines)} 句")

# 2) 时长（沿用上一次运行的真实值）
duration = json.loads((WORK / "report.mock_backup.json").read_text(encoding="utf-8"))["duration"]
print(f"[audio] duration={duration}s")

# 3) 人声包络（复用 demucs 产物）
vocals = audio_mod.separate_vocals(str(WORK / "source.wav"), str(WORK))
env = audio_mod.rms_envelope(vocals)
print("[separate] vocals 包络就绪")

# 4) 对齐
events, report = align_mod.align(env, lines, duration, trim=0.0)
print(
    f"[align] route={report['route']} ratio={report['ratio_onset_to_line']} "
    f"n={report['n_lyrics']}/{report['n_onsets']} "
    f"delta_mean={report.get('delta_abs_mean')}s max={report.get('delta_abs_max')}s"
)

if report["route"] != "interp":
    print("[skip] 未走降级路由，修复循环不会触发")
    sys.exit(0)

# 5) 真模型修复循环
print(f"[llm] {cfg['llm']['model']} @ {cfg['llm']['base_url']}")
client = llm_mod.LLMClient(cfg["llm"]["base_url"], cfg["llm"]["api_key"], cfg["llm"]["model"])


def realign(merge_gap=None, thr_low=None, thr_high=None, trim=None):
    return align_mod.align(
        env,
        lines,
        duration,
        trim=0.0,
        merge_gap=merge_gap,
        thr_low=thr_low,
        thr_high=thr_high,
    )


loop = RepairLoop(client, realign, max_rounds=3)
events, report, history = loop.run(events, report)

print("\n=== 真模型修复轨迹 ===")
for h in history:
    cand = h.get("candidate")
    extra = ""
    if cand:
        extra = f" -> {cand['route']} dmean={cand['delta_abs_mean']} dmax={cand['delta_abs_max']}"
    print(f"r{h['round']}: {h['action']} {h.get('args', '')}{extra}")
    print(f"      {h.get('result') or h.get('note', '')}")
print(f"\n最终 route={report['route']} delta_mean={report.get('delta_abs_mean')}s")

out = WORK / "repair_real_trajectory.json"
out.write_text(
    json.dumps(
        {"model": cfg["llm"]["model"], "history": history, "final": report},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"轨迹已保存 -> {out}")

# 写回工作区产物：让 events/report 反映真模型运行的最终结果
(WORK / "events.json").write_text(
    json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8"
)
(WORK / "report.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
)
print("已写回 events.json / report.json（真模型终态）")

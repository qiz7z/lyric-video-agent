# -*- coding: utf-8 -*-
"""对齐核心回归测试：用《寂寞沙洲冷》的真实产物做基准。

数据源（已交付歌曲的工作区，测试若缺失会自动 SKIP）：
  - vocals.wav   : demucs 分离好的人声（v6 定稿版所用）
  - 寂寞沙洲冷.lrc: 实际使用的歌词
  - _jm_events.json: 逐行人工校验过的 LINE_SEG 映射产物（地面真值）
断言：路由应为 sequential；事件单调、不越界、末句驻留 <= HOLD+1s；
      与地面真值逐行起点中位偏差 < 4s（自动量化映射 vs 人工逐行核对，
      允许个别行偏差，但整体必须收敛）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JM = Path(r"C:\Users\liuqi\Desktop\抖音投稿\寂寞沙洲冷\工作区")


def main():
    vocals = JM / "vocals.wav"
    lrc = JM / "寂寞沙洲冷.lrc"
    gt = JM / "_jm_events.json"
    if not vocals.exists():
        print("SKIP: 找不到寂寞沙洲冷工作区数据")
        return 0

    from tools import align as align_mod
    from tools import audio as audio_mod
    from tools import lyrics as lyrics_mod

    lines = lyrics_mod.parse_lrc(lrc.read_text(encoding="utf-8"))
    lines = [(t, lyrics_mod._t2s(s)) for t, s in lines]   # 真值为简体
    print(f"歌词 {len(lines)} 句，前2句: {lines[:2]}")
    rms, times = audio_mod.rms_envelope(str(vocals))
    total = 274.60   # 与 v4 定稿一致
    events, report = align_mod.align((rms, times), lines, total)

    print(f"report: {json.dumps(report, ensure_ascii=False)}")
    assert report["route"] == "sequential", f"路由应为 sequential, got {report['route']}"
    assert report["n_onsets"] >= report["n_lyrics"], "顺序装填前提：段数>=行数"
    assert len(events) >= len(lines), f"事件数 {len(events)} 不应少于行数 {len(lines)}"

    starts = [e["start"] for e in events]
    assert all(b >= a for a, b in zip(starts, starts[1:])), "起点必须单调"
    assert all(e["end"] <= total + 0.01 for e in events), "不得越过片尾"
    last = events[-1]
    assert last["end"] <= last["start"] + align_mod.HOLD_AFTER + 1.0, \
        f"末句挂死片尾: {last}"

    if gt.exists():
        gt_events = json.loads(gt.read_text(encoding="utf-8"))
        diffs = []
        for e in events:
            ds = [abs(e["start"] - g["start"]) for g in gt_events
                  if e["text"][:6] == g["text"][:6]]
            if ds:
                diffs.append(min(ds))
        diffs.sort()
        median = diffs[len(diffs) // 2] if diffs else 999
        print(f"与人工校验真值可比对 {len(diffs)} 句，起点偏差中位数 {median:.2f}s "
              f"(max {diffs[-1]:.2f}s)")
        assert median < 4.0, f"与地面真值偏差过大: median={median:.2f}s"

    print("PASS test_align")
    return 0


if __name__ == "__main__":
    sys.exit(main())

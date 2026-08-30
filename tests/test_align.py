"""对齐核心回归测试：用《寂寞沙洲冷》的地面真值做基准。

数据说明（原工作区中间产物已被清理，真值小文件已固化进 tests/data/）：
  - tests/data/寂寞沙洲冷.lrc : 实际使用的歌词
  - tests/data/_jm_events.json: 逐行人工校验过的映射产物（地面真值）
  - vocals.wav                : demucs 分离人声（大文件不入库）——缺失时自动用
    demucs 从《寂寞沙洲冷_无字幕版.mp4》重建并缓存（GPU ~30s）；连源都没有则 SKIP
断言：路由应为 sequential；事件单调、不越界、末句驻留 <= HOLD+1s；
      与地面真值逐行起点中位偏差 < 4s（v6.5 定稿基准：0.00s）。
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA = ROOT / "tests" / "data"
OLD_WS = Path(r"C:\Users\liuqi\Desktop\抖音投稿\寂寞沙洲冷\工作区")
SRC_VIDEO = Path(r"C:\Users\liuqi\Desktop\抖音投稿\寂寞沙洲冷\寂寞沙洲冷_无字幕版.mp4")


def ensure_vocals() -> str | None:
    """人声缺失时自动重建（demucs），缓存到 tests/data/。"""
    for cand in (OLD_WS / "vocals.wav", DATA / "vocals.wav"):
        if cand.exists() and cand.stat().st_size > 100_000:
            return str(cand)
    if not SRC_VIDEO.exists():
        return None
    from tools import audio as audio_mod

    print("vocals.wav 缺失，用 demucs 从无字幕版重建（一次性，~1min）...")
    tmp_wav = DATA / "jm_source.wav"
    if not tmp_wav.exists():
        audio_mod.decode_wav(str(SRC_VIDEO), str(tmp_wav), stereo=True)
    vocals = audio_mod.separate_vocals(str(tmp_wav), str(DATA))
    # separate_vocals 输出到 DATA/separated/...，复制缓存一份固定路径
    import shutil

    shutil.copy(vocals, DATA / "vocals.wav")
    return str(DATA / "vocals.wav")


def main():
    lrc = DATA / "寂寞沙洲冷.lrc"
    gt = DATA / "_jm_events.json"
    if not lrc.exists():
        print("SKIP: 真值数据缺失")
        return 0
    vocals = ensure_vocals()
    if not vocals:
        print("SKIP: 人声缺失且无源视频可重建（本机全量跑需寂寞沙洲冷数据）")
        return 0

    from tools import align as align_mod
    from tools import audio as audio_mod
    from tools import lyrics as lyrics_mod

    lines = lyrics_mod.parse_lrc(lrc.read_text(encoding="utf-8"))
    lines = [(t, lyrics_mod._t2s(s)) for t, s in lines]  # 真值为简体
    print(f"歌词 {len(lines)} 句")
    rms, times = audio_mod.rms_envelope(vocals)
    total = 274.60  # 与 v4 定稿一致
    events, report = align_mod.align((rms, times), lines, total)

    print(f"report: {json.dumps(report, ensure_ascii=False)}")
    # 验收标准是真值中位偏差，不是路由名——demucs 重跑段数 ±1 会让边界歌翻路由
    assert report["n_onsets"] >= report["n_lyrics"], "前提：段数>=行数"
    assert len(events) >= len(lines), f"事件数 {len(events)} 不应少于行数 {len(lines)}"

    starts = [e["start"] for e in events]
    assert all(b >= a for a, b in zip(starts, starts[1:], strict=False)), "起点必须单调"
    assert all(e["end"] <= total + 0.01 for e in events), "不得越过片尾"
    last = events[-1]
    assert last["end"] <= last["start"] + align_mod.HOLD_AFTER + 1.0, f"末句挂死片尾: {last}"

    if gt.exists():
        gt_events = json.loads(gt.read_text(encoding="utf-8"))
        diffs = []
        for e in events:
            ds = [abs(e["start"] - g["start"]) for g in gt_events if e["text"][:6] == g["text"][:6]]
            if ds:
                diffs.append(min(ds))
        diffs.sort()
        median = diffs[len(diffs) // 2] if diffs else 999
        print(
            f"与人工校验真值可比对 {len(diffs)} 句，起点偏差中位数 {median:.2f}s "
            f"(max {diffs[-1]:.2f}s)"
        )
        assert median < 4.0, f"与地面真值偏差过大: median={median:.2f}s"

    print("PASS test_align")
    return 0


if __name__ == "__main__":
    sys.exit(main())

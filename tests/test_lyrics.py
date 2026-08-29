# -*- coding: utf-8 -*-
"""歌词获取测试：用真实交付 mp3（爱情码头 / 牧马城市）验证内嵌 LRC 读取、
元数据/base64 过滤、时间有序。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CANDIDATES = [
    Path(r"C:\Users\liuqi\Desktop\抖音投稿\爱情码头\爱情码头 - 郑源.mp3"),
    Path(r"C:\Users\liuqi\Desktop\抖音投稿\牧马城市\牧马城市 - 毛不易.mp3"),
    Path(r"C:\Users\liuqi\Desktop\抖音投稿\刚好遇见你\刚好遇见你 - 李玉刚.mp3"),
]


def main():
    from tools import lyrics as lyrics_mod
    from tools import audio as audio_mod

    checked = 0
    for mp3 in CANDIDATES:
        if not mp3.exists():
            continue
        checked += 1
        dur = audio_mod.probe_duration(str(mp3))
        # title 直接传文件名 stem（含 " - 歌手"），验证智能拆分
        ly = lyrics_mod.load_lyrics(str(mp3), title=mp3.stem, duration=dur)
        print(f"{mp3.name}: source={ly.source}, {len(ly.lines)} 句")
        assert ly.lines, f"{mp3.name}: 应能读到歌词"
        assert ly.lines[0][0] < 90, "第一句应在 90s 内"
        for t, s in ly.lines:
            assert s.strip(), f"空行: {t}"
            assert len(s) < 200, f"疑似 base64/脏数据未滤净: {s[:50]}"
        assert all(b[0] >= a[0] for a, b in zip(ly.lines, ly.lines[1:])), "时间须有序"
        print("  样例:", ly.lines[0], ly.lines[1])
    if not checked:
        print("SKIP: 没找到测试 mp3")
        return 0
    print("PASS test_lyrics")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""封面 Agent 离线测试：真实成品视频抽帧 + MockLLM + 帧降级背景 -> 真实 PNG 产物。

不花一分钱（mock 模式禁用图片生成），但选帧与排版渲染是真实的 ffmpeg 链路。
数据依赖梦的光点成品视频，缺失自动 SKIP。
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FINAL = Path(r"C:\Users\liuqi\Desktop\抖音投稿\梦的光点\梦的光点_歌词视频.mp4")


def main():
    if not FINAL.exists():
        print("SKIP: 梦的光点成品视频缺失")
        return 0

    from agent.cover import CoverAgent
    from agent.llm import MockLLM
    from tools.audio import get_ffmpeg

    work = ROOT / "runs" / "_test_cover"
    agent = CoverAgent(title="梦的光点", artist="王心凌", workdir=str(work),
                       llm=MockLLM(), vision=MockLLM(), imagegen=None,
                       plan={"theme": "励志阳光风景", "mood": "hopeful"},
                       # 离线调研源（MockLLM 不调工具直接给终答）
                       research_fn=lambda: {"web": [{"title": "mock", "body": "mock",
                                                     "href": ""}],
                                            "musicbrainz": None, "local": {}},
                       search_fn=lambda q: [])
    decisions = agent.run(video_path=str(FINAL))

    cover = Path(decisions["cover"])
    assert cover.exists() and cover.stat().st_size > 50_000, "封面产物缺失/过小"

    # 尺寸必须是 1080x1440
    r = subprocess.run([get_ffmpeg(), "-i", str(cover), "-hide_banner"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    dims = [l for l in r.stderr.splitlines() if "1080x1440" in l or ("png" in l.lower() and "1080" in l)]
    assert any("1080x1440" in l for l in r.stderr.splitlines()), \
        f"封面应为 1080x1440: {[l.strip()[:100] for l in r.stderr.splitlines() if 'png' in l.lower()]}"

    steps = decisions["steps"]
    assert steps["background"]["mode"] == "frame_fallback", "无 key 应走帧降级"
    assert steps["copy"]["mode"] == "llm", "MockLLM 存在时文案应走 llm 模式"
    assert steps["pick"]["mode"] == "vision", "MockLLM 视觉存在时应走 vision 选帧"
    assert steps["research"]["mode"] == "llm", "调研步应走 llm 模式"
    assert steps["research"]["background"], "调研应产出背景摘要"
    assert (work / "cover_decision.json").exists(), "决策记录必须落盘"
    print(f"PASS test_cover ({cover.name}, {cover.stat().st_size // 1024}KB, "
          f"copy='{steps['copy']['title']}')")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""命令行入口。

用法（在项目根目录）：
  # 全流程（推荐先 --mock 走一遍，确认后再真跑）
  .venv/Scripts/python -m agent.cli "梦的光点" --audio "C:/path/梦的光点 - 王心凌.mp3"

  常用选项：
    --mock            离线假 LLM（规划/质检用固定结果，不花钱，验证链路用）
    --yes             跳过 Stage6 人工听感闸门
    --skip-generate   跳过 Agnes 生片（只出验证片 / 用已有 clips 合成）
    --skip-qc         跳过视觉自检
    --trim 50         覆盖规划器：裁掉前 50s 前奏
    --artist NAME     歌手名（LRCLib 检索更准）
"""

from __future__ import annotations

import argparse
import sys


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="lyric-video-agent", description="歌词视频制作 Agent")
    ap.add_argument("title", help="歌曲标题")
    ap.add_argument("--audio", required=True, help="源音频路径（mp3/m4a/flac/wav）")
    ap.add_argument("--artist", default="", help="歌手名")
    ap.add_argument("--mock", action="store_true", help="离线 mock LLM")
    ap.add_argument("--yes", action="store_true", help="跳过人工听感闸门")
    ap.add_argument("--skip-generate", action="store_true", help="跳过 AI 生片")
    ap.add_argument("--skip-qc", action="store_true", help="跳过视觉自检")
    ap.add_argument("--skip-repair", action="store_true", help="跳过对齐修复循环")
    ap.add_argument("--skip-cover", action="store_true", help="跳过封面 Agent")
    ap.add_argument("--trim", type=float, default=None, help="裁掉前奏秒数")
    args = ap.parse_args(argv)

    from .orchestrator import Orchestrator

    orch = Orchestrator(
        title=args.title,
        audio=args.audio,
        artist=args.artist,
        mock=args.mock,
        yes=args.yes,
        skip_generate=args.skip_generate,
        skip_qc=args.skip_qc,
        skip_repair=args.skip_repair,
        skip_cover=args.skip_cover,
        trim=args.trim,
    )
    report = orch.run()
    print("\n=== 运行摘要 ===")
    print(
        f"路由: {report['align'].get('route')}  对齐均值: {report['align'].get('delta_abs_mean')}s"
    )
    print(f"片段: {report['clips_ready']}/{report['n_clips']}  用时: {report['elapsed_sec']}s")
    print(f"成品: {report['final_video']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

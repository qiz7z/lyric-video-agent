"""封面 Agent 离线测试（不花钱，全离线确定性）。

两个场景，分别回归封面的两条调用路径：

  1. headless + 帧降级（默认、离线必跑）：MockLLM + 无图片 key，从成品视频抽帧
     → 真实抽帧/选帧/排版链路 → 断言 1080×1440 PNG 与决策记录。
     对应 cover.py 的 `run_headless(frame_source=...)` 入口。

  2. headless + 无视频产物（离线确定性、必跑）：MockLLM + MockImageGen，仅歌名/
     歌手/plan。验证"封面不依赖正片也能出"——直接回归并行支线立论（§6.1 之
     "生命周期不同"），以及 orchestrator 并行封面支线（plan 后即启动）在
     `--skip-generate` 下能产出封面的同一段代码。

真 Agnes 图片模型验证见 `tests/probe_cover_headless.py`（需 key + 联网，手动跑、
留证到 runs/_probe_cover_headless），不进入 CI 门禁。

数据依赖梦的光点成品视频，缺失自动 SKIP（仅场景 1 需要视频；场景 2 纯 headless）。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FINAL = Path(r"C:\Users\liuqi\Desktop\抖音投稿\梦的光点\梦的光点_歌词视频.mp4")


class MockImageGen:
    """离线确定性图片模型：用 PIL 写一张渐变 PNG（>50KB，ffmpeg 可放大）。"""

    def generate(self, prompt: str, out_path: str, size: str = "1080x1440") -> str:
        from PIL import Image

        w, h = (int(x) for x in size.split("x"))
        img = Image.new("RGB", (w, h))
        px = img.load()
        for y in range(h):
            for x in range(w):
                px[x, y] = ((x * 255) // w, (y * 255) // h, ((x + y) * 128) // (w + h))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, "PNG")
        return out_path


def _research_canned() -> dict:
    """离线调研产物（与真调研同构的字段，让 image_prompt 主路径可达）。"""
    return {
        "mode": "llm",
        "background": "一首关于追逐梦想、温暖向上的流行歌",
        "image_prompt": "sunlit flower field at dawn, soft golden light, hopeful cinematic scenery",
        "visual_concept": "hopeful",
        "title_hint": "梦的光点",
        "web": [{"title": "mock", "body": "mock", "href": ""}],
        "musicbrainz": None,
        "local": {},
    }


def _assert_cover(decisions: dict, work: Path) -> Path:
    """断言封面产物存在、尺寸 1080×1440、决策记录落盘，返回封面路径。"""
    from tools.audio import get_ffmpeg

    cover = Path(decisions["cover"])
    assert cover.exists() and cover.stat().st_size > 50_000, "封面产物缺失/过小"
    r = subprocess.run(
        [get_ffmpeg(), "-i", str(cover), "-hide_banner"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert any("1080x1440" in ln for ln in r.stderr.splitlines()), (
        f"封面应为 1080x1440: "
        f"{[ln.strip()[:100] for ln in r.stderr.splitlines() if 'png' in ln.lower()]}"
    )
    assert (work / "cover_decision.json").exists(), "决策记录必须落盘"
    return cover


def test_headless_frame_fallback() -> int:
    """默认离线场景：MockLLM + 无图片 key，从成品视频抽帧做帧降级背景。

    验证 `run_headless` 入口在「有帧源、无图片模型」时的降级路径——与重构前
    `run(video_path=...)` 行为一致。
    """
    if not FINAL.exists():
        print("SKIP test_headless_frame_fallback: 梦的光点成品视频缺失")
        return 0

    from agent.cover import CoverAgent
    from agent.llm import MockLLM

    work = ROOT / "runs" / "_test_cover"
    agent = CoverAgent(
        title="梦的光点",
        artist="王心凌",
        workdir=str(work),
        llm=MockLLM(),
        vision=MockLLM(),
        imagegen=None,
        plan={"theme": "励志阳光风景", "mood": "hopeful"},
        # 离线调研源（MockLLM 不调工具直接给终答）
        research_fn=lambda: {
            "web": [{"title": "mock", "body": "mock", "href": ""}],
            "musicbrainz": None,
            "local": {},
        },
        search_fn=lambda q: [],
    )
    # headless 入口：frame_source 即「帧源」（视频或 clips 皆可），无帧源时为纯 headless
    decisions = agent.run_headless(frame_source=str(FINAL))

    cover = _assert_cover(decisions, work)
    steps = decisions["steps"]
    assert steps["background"]["mode"] == "frame_fallback", "无 key 应走帧降级"
    assert steps["copy"]["mode"] == "llm", "MockLLM 存在时文案应走 llm 模式"
    assert steps["pick"]["mode"] == "vision", "MockLLM 视觉存在时应走 vision 选帧"
    assert steps["research"]["mode"] == "llm", "调研步应走 llm 模式"
    assert steps["research"]["background"], "调研应产出背景摘要"
    print(
        f"PASS headless_frame_fallback ({cover.name}, {cover.stat().st_size // 1024}KB, "
        f"copy='{steps['copy']['title']}')"
    )
    return 0


def test_headless_without_video() -> int:
    """离线确定性场景：仅歌名/歌手/plan，无视频产物也能出封面（MockImageGen）。

    直接回归并行支线立论——封面背景来自调研产出的生图提示词，与正片是否存在无关。
    这也是 orchestrator 并行封面支线（plan 后即启动）在 `--skip-generate`
    下能产出封面的同一段代码。全离线、确定性，进入 CI 门禁。

    真 Agnes 图片模型验证见 `tests/probe_cover_headless.py`（需 key + 联网）。
    """
    from agent.cover import CoverAgent
    from agent.llm import MockLLM

    work = ROOT / "runs" / "_test_cover_headless"
    agent = CoverAgent(
        title="梦的光点",
        artist="王心凌",
        workdir=str(work),
        llm=MockLLM(),
        vision=MockLLM(),
        imagegen=MockImageGen(),
        plan={"theme": "励志阳光风景", "mood": "hopeful"},
        research_fn=_research_canned,
        search_fn=lambda q: [],
    )
    # 关键：不传 frame_source / clips —— 纯 headless，无正片也能出封面
    decisions = agent.run_headless()

    cover = _assert_cover(decisions, work)
    steps = decisions["steps"]
    assert steps["background"]["mode"] == "image_model", "有图片模型应走图片模型主路径"
    assert steps["copy"]["mode"] == "llm", "MockLLM 文案应走 llm 模式"
    assert steps["research"]["mode"] == "llm", "调研步应走 llm 模式"
    print(
        f"PASS headless_without_video ({cover.name}, {cover.stat().st_size // 1024}KB, "
        f"bg_mode={steps['background']['mode']}, copy='{steps['copy']['title']}')"
    )
    return 0


if __name__ == "__main__":
    rc = 0
    for fn in (test_headless_frame_fallback, test_headless_without_video):
        try:
            rc |= fn()
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
            rc = 1
        except Exception as e:  # 兜底：任何异常标记 ERROR 且不崩
            print(f"ERROR {fn.__name__}: {e}")
            rc = 1
    sys.exit(rc)

"""真模型封面「无正片出封面」探针（需要 Agnes 图片 key + LLM key）。

与 tests/probe_repair_realmodel.py 同款定位：验证封面 Agent 在「仅歌名/歌手/plan、
没有任何视频产物」时仍能产出竖版封面——直接回归并行支线立论（ARCHITECTURE §6.1
之"生命周期不同"，已在 orchestrator 中代码兑现）。

这等价于 orchestrator 在 `--skip-generate` 下 plan 后即启动的封面并行支线：
封面主链 `run_headless()` 不接收 frame_source / clips，背景 prompt 来自调研产出。

跑法：
    .venv/Scripts/python tests/probe_cover_headless.py

产出：runs/_probe_cover_headless/cover_decision.json（模型名 + 每步决策 + 封面路径）
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import llm as llm_mod
from agent.cover import CoverAgent
from tools import research as research_mod
from tools.imagogen import ImageGen

cfg = llm_mod.load_config()
agnes = (cfg or {}).get("agnes") or {}
key = agnes.get("api_key")
llm_cfg = (cfg or {}).get("llm") or {}
if not key:
    print("SKIP probe_cover_headless: 未配置 Agnes 图片 key（config.json 或 LVA_AGNES_API_KEY）")
    sys.exit(0)
if not llm_cfg.get("api_key"):
    print("SKIP probe_cover_headless: 未配置 LLM key")
    sys.exit(0)

TITLE, ARTIST = "梦的光点", "王心凌"
base_url = agnes.get("base_url", "https://apihub.agnes-ai.com/v1")
imagegen = ImageGen(
    key,
    base_url=base_url,
    model=agnes.get("image_model", "agnes-image-2.1-flash"),
    proxies=agnes.get("proxies"),
)
llm_client = llm_mod.LLMClient(llm_cfg["base_url"], llm_cfg["api_key"], llm_cfg["model"])
proxies = agnes.get("proxies")

print(f"[llm] {llm_cfg['model']} @ {llm_cfg['base_url']}")
print(f"[image] {agnes.get('image_model', 'agnes-image-2.1-flash')} @ {base_url}")

work = Path(__file__).resolve().parent.parent / "runs" / "_probe_cover_headless"


def _safe_research():
    """真实调研 + 失败兜底：web 搜索（brave/grokipedia）偶发 503/超时，
    不应阻塞"无正片出封面"这条核心验证——调研失败就退回 plan 主题。"""
    try:
        pkg = research_mod.research_package(TITLE, ARTIST, proxies=proxies)
        if pkg:
            return pkg
    except Exception as e:
        print(f"[research] 信息源聚合失败（{str(e)[:80]}），退回静态兜底")
    return {
        "web": [],
        "musicbrainz": None,
        "local": {
            "background": "王心凌演唱的励志动画主题曲，关于追逐梦想与勇气",
            "visual_concept": "破晓晨光穿透云层，光点汇聚成希望的脉络",
            "image_prompt": "golden sunrise breaking through clouds, tiny light points "
            "gathering into a hopeful stream, vertical poster, no text, no people",
            "title_hint": "追着那束光出发",
        },
    }


agent = CoverAgent(
    title=TITLE,
    artist=ARTIST,
    workdir=str(work),
    llm=llm_client,
    vision=llm_client,
    imagegen=imagegen,
    plan={"theme": "励志阳光风景", "mood": "hopeful"},
    # search_fn=None：不让 LLM 驱动额外 web 搜索（上游搜索 API 抖动大，
    # 且与"无正片出封面"无关）；调研只走 research_fn 的聚合结果。
    research_fn=_safe_research,
    search_fn=None,
)

# 关键：不传 frame_source / clips —— 纯 headless，验证无正片也能出封面
print("[cover] 启动 run_headless()（无视频帧源）...")
try:
    decisions = agent.run_headless()
except Exception:
    import traceback

    traceback.print_exc()
    sys.exit(1)

cover = Path(decisions["cover"])
steps = decisions["steps"]
assert cover.exists() and cover.stat().st_size > 50_000, "封面产物缺失/过小"
assert steps["background"]["mode"] == "image_model", "有图片 key 应走图片模型主路径"

print("\n=== 封面无正片出图轨迹 ===")
print(f"背景: {decisions['steps']['research'].get('background', '')}")
print(f"概念: {decisions['steps']['research'].get('visual_concept', '')}")
print(f"背景模式: {steps['background']['mode']}")
print(f"文案: {steps['copy'].get('title')} / {steps['copy'].get('subtitle')}")
print(f"封面: {cover} ({cover.stat().st_size // 1024}KB)")

out = work / "cover_decision.json"
out.write_text(
    json.dumps(
        {
            "model": llm_cfg["model"],
            "image_model": agnes.get("image_model", "agnes-image-2.1-flash"),
            "had_video_product": False,
            "steps": steps,
            "cover": str(cover),
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(f"\n轨迹已保存 -> {out}")
print("PASS probe_cover_headless: 无正片产物仍成功产出封面")

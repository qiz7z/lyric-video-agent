"""记忆层：策略手册（playbook）+ 经验沉淀（lessons）。

两类记忆，生命周期不同：
- playbook.md   静态策略：人工维护的领域 SOP（字幕渲染禁令、纯风景默认、
                路由选择、限流参数……），每次规划前整篇注入 Planner 上下文；
- lessons.jsonl 动态经验：每次运行结束由 Orchestrator 追加（对齐质量、
                QC 发现、修复动作），下次规划时取最近 K 条作为 few-shot。
这就是本项目的 agent memory 设计：策略 = 长期规则，经验 = 近期反馈。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_playbook() -> str:
    p = PROJECT_ROOT / "policy" / "playbook.md"
    return p.read_text(encoding="utf-8")


def lessons_path() -> Path:
    return PROJECT_ROOT / "memory" / "lessons.jsonl"


def load_lessons(k: int = 5) -> list[dict]:
    f = lessons_path()
    if not f.exists():
        return []
    lines = [s for s in f.read_text(encoding="utf-8").splitlines() if s.strip()]
    out = []
    for line in lines[-k:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def append_lesson(record: dict) -> None:
    f = lessons_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    record = {"date": datetime.now().strftime("%Y-%m-%d"), **record}
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def safe_name(title: str) -> str:
    """歌名 -> 安全目录名。"""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_") or "song"


def run_dir(title: str) -> Path:
    d = PROJECT_ROOT / "runs" / safe_name(title)
    d.mkdir(parents=True, exist_ok=True)
    return d

"""修复循环：真正的 function-calling tool-use 环节。

触发条件：对齐走了降级路由 interp（演唱段 < 歌词行数，字幕只能直用 LRC 时间）。
LLM 通过 function calling 在工具箱（re_align / set_trim / accept）里自主决策，
编排器执行工具并回填观察结果，直到 accept 或轮数上限。

两道防线（都来自实测教训）：
- 质量门槛：merge_gap 调小能把 interp 升级成 sequential，但实测会把 delta_max
  从 2.5s 拉爆到 15s（《梦的光点》）——路由升级 ≠ 质量提升。候选结果必须通过
  delta_abs_max <= 3.0 且整体不劣化才被采纳，否则 REJECTED 并自动回退；
- 轮数上限（默认 3）：防修复循环本身失控烧钱。

被拒绝的参数会作为观察结果回传给 LLM（"被拒绝过的参数不要原样重试"）。
"""

from __future__ import annotations

import json
import re

from tools.schemas import REPAIR_TOOLS, SYSTEM_PROMPT

DELTA_MAX_OK = 3.0  # 质量门槛：最大偏差超过此值直接拒绝
ROUTE_RANK = {"sequential": 2, "lrc_primary": 1, "interp": 0}


def _quality(report: dict) -> tuple:
    """路由优先、偏差次之的字典序质量分。"""
    dmean = report.get("delta_abs_mean")
    return (ROUTE_RANK.get(report.get("route"), 0), -(dmean if dmean is not None else 99.0))


class RepairLoop:
    def __init__(self, llm, realign_fn, max_rounds: int = 3):
        """realign_fn(merge_gap/thr_low/thr_high/trim) -> (events, report)
        由编排器注入（闭包持有包络、歌词、总时长等上下文）。"""
        self.llm = llm
        self.realign_fn = realign_fn
        self.max_rounds = max_rounds

    def run(self, events: list[dict], report: dict) -> tuple[list[dict], dict, list[dict]]:
        """返回 (最终events, 最终report含repair_history, 决策历史)。"""
        history: list[dict] = []
        best_events, best_report = events, dict(report)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(max_rounds=self.max_rounds)},
            {
                "role": "user",
                "content": json.dumps({"task": "repair", "report": report}, ensure_ascii=False),
            },
        ]
        for rnd in range(1, self.max_rounds + 1):
            msg = self.llm.chat(messages, tools=REPAIR_TOOLS)
            calls = msg.get("tool_calls") or []
            if not calls:
                history.append(
                    {
                        "round": rnd,
                        "action": "accept_text",
                        "note": (msg.get("content") or "")[:120],
                    }
                )
                break
            call = calls[0]  # 每轮只执行第一个工具调用
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except Exception:
                args = {}
            args.pop("reason", None)

            if name == "accept":
                history.append({"round": rnd, "action": "accept", "args": args})
                break
            if name == "re_align":
                candidate = self.realign_fn(
                    **{k: v for k, v in args.items() if k in ("merge_gap", "thr_low", "thr_high")}
                )
            elif name == "set_trim":
                seconds = max(0.0, min(float(args.get("seconds", 0)), 60.0))
                candidate = self.realign_fn(trim=seconds)
            else:
                observation = f"UNKNOWN TOOL {name}, 可用: re_align/set_trim/accept"
                history.append({"round": rnd, "action": name, "result": "unknown"})
                messages.append(self._tool_msg(call, observation))
                continue

            verdict, adopted = self._gate(candidate, best_events, best_report)
            history.append(
                {
                    "round": rnd,
                    "action": name,
                    "args": args,
                    "result": verdict,
                    "candidate": {
                        "route": candidate[1].get("route"),
                        "n_onsets": candidate[1].get("n_onsets"),
                        "delta_abs_mean": candidate[1].get("delta_abs_mean"),
                        "delta_abs_max": candidate[1].get("delta_abs_max"),
                    },
                }
            )
            if adopted:
                best_events, best_report = candidate
                history[-1]["note"] = "已采纳"
                break
            observation = (
                f"{verdict}（已自动回退到当前最优结果）。"
                f"候选: route={candidate[1].get('route')} "
                f"delta_max={candidate[1].get('delta_abs_max')}。"
                f"不要原样重试相同参数。"
            )
            messages.append(self._tool_msg(call, observation))
        else:
            history.append(
                {"round": self.max_rounds, "action": "accept", "note": "达到轮数上限，自动接受"}
            )
        best_report["repair_history"] = history
        return best_events, best_report, history

    @staticmethod
    def _gate(candidate: tuple[list[dict], dict], cur_events, cur_report) -> tuple[str, bool]:
        """质量门槛：通过且更优才采纳。"""
        _, creport = candidate
        dmax = creport.get("delta_abs_max")
        if dmax is not None and dmax > DELTA_MAX_OK:
            return f"REJECTED: delta_abs_max={dmax}s 超过门槛 {DELTA_MAX_OK}s", False
        if _quality(creport) > _quality(cur_report):
            return "ACCEPTED: 路由/偏差改善", True
        return "REJECTED: 整体质量未优于当前结果", False

    @staticmethod
    def _tool_msg(call: dict, content: str) -> dict:
        return {"role": "tool", "tool_call_id": call.get("id") or "call_0", "content": content}


def extract_tool_call(message: dict) -> tuple[str, dict] | None:
    """从 assistant 消息里取第一个工具调用（供测试/调试）。"""
    calls = message.get("tool_calls") or []
    if not calls:
        return None
    fn = calls[0]["function"]
    try:
        args = json.loads(re.sub(r"```(?:json)?|```", "", fn.get("arguments") or "{}"))
    except Exception:
        args = {}
    return fn["name"], args

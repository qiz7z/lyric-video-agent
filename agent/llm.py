# -*- coding: utf-8 -*-
"""LLM 客户端：OpenAI 兼容协议（/chat/completions + tools），与具体厂商解耦。

任何 OpenAI 兼容端点都能用：DeepSeek / GLM / Qwen(DashScope) / Moonshot / OpenAI /
vLLM / Ollama。配置读 config.json 或环境变量（详见 config.example.json）。

MockLLM：无需 key 的离线实现，供 --mock 模式与单元测试使用——它按消息里的
任务标记返回固定的规划/质检结果，用于不花钱验证整条编排链路的正确性。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    """config.json 优先级低于环境变量；都缺失时返回空 dict（mock 模式仍可用）。"""
    cfg = {}
    f = PROJECT_ROOT / "config.json"
    if f.exists():
        cfg = json.loads(f.read_text(encoding="utf-8"))
    env = os.environ
    llm = cfg.setdefault("llm", {})
    llm.setdefault("base_url", env.get("LVA_LLM_BASE_URL", "https://api.deepseek.com/v1"))
    llm.setdefault("api_key", env.get("LVA_LLM_API_KEY", ""))
    llm.setdefault("model", env.get("LVA_LLM_MODEL", "deepseek-chat"))
    vision = cfg.setdefault("vision", {})
    vision.setdefault("base_url", env.get("LVA_VISION_BASE_URL", llm["base_url"]))
    vision.setdefault("api_key", env.get("LVA_VISION_API_KEY", llm["api_key"]))
    vision.setdefault("model", env.get("LVA_VISION_MODEL", ""))  # 空则跳过视觉 QC
    agnes = cfg.setdefault("agnes", {})
    agnes.setdefault("api_key", env.get("LVA_AGNES_API_KEY", ""))
    if env.get("LVA_USE_PROXY"):
        agnes.setdefault("proxies", {"http": "http://127.0.0.1:7890",
                                     "https": "http://127.0.0.1:7890"})
    return cfg


class LLMClient:
    """OpenAI 兼容 chat completions 客户端（仅实现本项目需要的最小面）。"""

    def __init__(self, base_url: str, api_key: str, model: str, temperature: float = 0.4):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int = 4096) -> dict:
        import requests
        body = {"model": self.model, "messages": messages,
                "temperature": self.temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        r = requests.post(f"{self.base_url}/chat/completions",
                          headers={"Authorization": f"Bearer {self.api_key}"},
                          json=body, timeout=180)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]

    # ---- 视觉（多模态 message，OpenAI 兼容 image_url/base64 格式）----
    def vision(self, prompt: str, image_paths: list[str], max_tokens: int = 2048) -> str:
        content = [{"type": "text", "text": prompt}]
        for p in image_paths:
            import base64
            b64 = base64.b64encode(Path(p).read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"}})
        msg = self.chat([{"role": "user", "content": content}], max_tokens=max_tokens)
        return msg.get("content") or ""


class MockLLM(LLMClient):
    """离线假 LLM：按任务标记回固定 JSON。让编排链路在没有 API key 时也能测通。"""

    def __init__(self):
        super().__init__("mock://", "mock", "mock")

    def chat(self, messages, tools=None, max_tokens=4096):
        task, payload = self._task_of(messages)
        if task == "plan":
            return {"content": json.dumps(_MOCK_PLAN, ensure_ascii=False)}
        if task == "qc":
            return {"content": json.dumps({"frames": []}, ensure_ascii=False)}
        if task == "repair":
            return self._repair_step(messages)
        if task == "cover_pick":
            return {"content": json.dumps({"index": 0, "reason": "mock"}, ensure_ascii=False)}
        if task == "cover_copy":
            song = str(payload.get("title", "歌名"))
            return {"content": json.dumps(
                {"title": song, "subtitle": f"《{song}》 {payload.get('artist', '')}".strip()},
                ensure_ascii=False)}
        if task == "cover_qc":
            return {"content": json.dumps({"ok": True, "issues": []}, ensure_ascii=False)}
        return {"content": "ok"}

    @staticmethod
    def _repair_step(messages) -> dict:
        """修复剧本：第1轮 re_align(merge_gap=0.22)（实测会被质量门槛拒绝），
        见过工具结果后 accept——覆盖'尝试-被拒-回退-接受'完整路径。"""
        seen_tool_result = any(m.get("role") == "tool" for m in messages)
        if not seen_tool_result:
            return {"tool_calls": [{"id": "mock_1", "type": "function",
                                    "function": {"name": "re_align",
                                                 "arguments": json.dumps(
                                                     {"merge_gap": 0.22,
                                                      "reason": "提高分段灵敏度争取升级路由"})}}]}
        return {"tool_calls": [{"id": "mock_2", "type": "function",
                                "function": {"name": "accept",
                                             "arguments": json.dumps(
                                                 {"reason": "候选被质量门槛拒绝，"
                                                            "接受当前 interp 结果"})}}]}

    @staticmethod
    def _task_of(messages) -> tuple[str, dict]:
        """从消息里解析出任务标记（user content 是 JSON 字符串）。"""
        for m in messages:
            c = m.get("content")
            if isinstance(c, str) and c.strip().startswith("{"):
                try:
                    payload = json.loads(c)
                    return payload.get("task", ""), payload
                except Exception:
                    continue
        return "", {}

    def vision(self, prompt, image_paths, max_tokens=2048):
        # 按任务语境返回对应格式的假结论
        if "选帧" in prompt:
            return json.dumps({"index": 0, "reason": "mock"}, ensure_ascii=False)
        if "封面质检" in prompt:
            return json.dumps({"ok": True, "issues": []}, ensure_ascii=False)
        return json.dumps({"frames": [{"index": i, "verdict": "ok", "reason": "mock"}
                                      for i in range(len(image_paths))]})


_MOCK_PLAN = {
    "theme": "mock励志阳光风景", "mood": "hopeful",
    "font": "STXingkai",
    "trim_intro_seconds": 0,
    "notes": "mock plan for offline test",
}

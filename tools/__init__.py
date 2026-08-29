# -*- coding: utf-8 -*-
"""工具层：歌词获取 / 音频处理 / 字幕对齐 / ASS 渲染 / AI 生图生视频 / 合成 / 检查。

设计原则：
- 每个函数都是纯确定性函数，不依赖 LLM —— Agent 层通过 schema（tools/schemas.py）
  把它们注册为 function calling 工具；
- 全部可独立运行、可单测（tests/ 目录有离线冒烟测试）；
- Windows / GBK 控制台安全：所有文件 IO 显式 encoding="utf-8"。
"""

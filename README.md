# Lyric Video Agent

**输入一首歌，Agent 自动完成：歌词获取 → 人声对轴 → AI 生成风景画面 → 视觉自检修复 → 合成成片。**

这是从 25 首实际交付抖音歌词视频的生产流水线中提炼出来的 Agent 项目：底层工具全部经过
真实交付验证，Agent 层负责其中需要"判断力"的决策，并补上了人工流程里最大的断点——
画面质检。

```
听歌              对轴                        生画面            自检            成片
 mp3 ──► 歌词+demucs人声 ──────────────► Agnes 视频 API ──► 视觉模型审帧 ──► ffmpeg 合成
          │        │                         （限流/续传）      （不合格重生成）    （xfade+字幕）
          │   DP 单调对齐                                                ▲
          │        ▼                                                     │
          │  降级路由(interp)? ──► [修复循环] LLM function-calling        │
          │        │            自主选工具(调参/裁前奏) + 质量门槛把关     │
          └── 黑底验证版 → 人工听感闸门（昂贵环节前的成本闸门）────────────┘
```

## 为什么值得看

- **真实生产背景**：不是玩具 demo。对齐算法、限流封装、续传逻辑全部来自 25 首已交付
  歌曲的实战迭代（对齐方案演进过 6 版），回归测试用人工逐行校验过的地面真值验证。
- **混合式 Agent 架构**：确定性流水线骨架 + LLM 决策点，而不是 LLM 自由循环。
  权衡分析见 [ARCHITECTURE.md](ARCHITECTURE.md)。
- **真 function-calling 修复循环**：对齐走降级路由时，LLM 自主诊断报告、选择修复工具
  （调分段参数 / 裁前奏）、根据执行观察决定下一步；质量门槛拒绝"路由升级但偏差劣化"
  的候选并自动回退（《梦的光点》实测拦截 delta_max 15.1s 的劣化升级）。
- **补上了人工流程最大断点**：过去"人物变形无法自动判定，只能用户终审"；
  现在视觉模型逐帧质检 → 自动改写 prompt 重生成（≤2 轮修复循环）。
- **记忆设计**：`policy/playbook.md`（长期策略，人工维护的领域 SOP）+
  `memory/lessons.jsonl`（短期经验，每次运行自动追加，下次规划时注入）。
- **工程细节**：API 限流退避（429/503/SSL 抖动）、CDN 断点续传（Range + ftyp 校验）、
  NVENC 失败回退 libx264、全流程幂等可续跑、离线 MockLLM 测试模式。

## 对齐基准（已交付歌曲回归）

| 歌曲 | 路由 | 段/行 | 对比基准 | 起点偏差中位数 |
|---|---|---|---|---|
| 寂寞沙洲冷 | sequential | 34/20 | 人工逐行校验真值 | **0.00s** |
| 樱花草 | sequential | 86/64 | 生产版 events（用户验收） | **0.03s** |
| 梦的光点 | interp | 56/62 | LRC 估计 | 0.56s（修复循环实测拦截劣化升级） |

复现：`.venv/Scripts/python tests/test_align.py`

## 快速开始

```bash
# 1. 环境（建议复用已有 torch 以省几 GB）
python -m venv --system-site-packages .venv
.venv/Scripts/pip install -r requirements.txt -r requirements-demucs.txt

# 2. 配置 LLM（任何 OpenAI 兼容端点：DeepSeek / GLM / Qwen / OpenAI...）
copy config.example.json config.json   # 填入 api_key；或用环境变量 LVA_LLM_API_KEY

# 3. 先离线走一遍链路（MockLLM，不花一分钱）
.venv/Scripts/python -m agent.cli "梦的光点" --audio "C:/path/梦的光点 - 王心凌.mp3" --mock --yes

# 4. 正式运行（人工听感闸门在验证片之后，确认对齐才开始生片）
.venv/Scripts/python -m agent.cli "梦的光点" --audio "C:/path/梦的光点 - 王心凌.mp3"
```

没有 LLM key 也能跑：不配置时自动降级 mock 模式（规划用默认策略）。
没有 demucs 也能跑：对齐自动降级全曲包络（质量下降，报告会标注）。

## 目录

```
agent/                 # Agent 层
  cli.py               #   命令行入口
  orchestrator.py      #   10 级流水线编排（含 3 个 LLM 决策点 + 人工闸门）
  planner.py           #   [决策点1] 制作规划（LLM 生成 + 确定性校验）
  repair.py            #   [决策点2] function-calling 修复循环（诊断→选工具→质量门槛）
  verifier.py          #   [决策点3] 视觉质检 + 修复循环
  llm.py               #   OpenAI 兼容客户端 + MockLLM（离线测试）
  memory.py            #   playbook（长期策略）+ lessons（运行经验）
tools/                 # 工具层（纯确定性函数，可独立单测）
  lyrics.py            #   内嵌 LRC / LRCLib / 繁简转换 / 脏数据过滤
  audio.py             #   ffmpeg / demucs 封装 / RMS 包络
  align.py             #   ★ 字幕-人声对齐（三路路由 + DP 单调对齐，参数可覆盖）
  ass.py               #   ASS 字幕渲染（fad-only 极简策略）
  videogen.py          #   Agnes API 客户端（限流/续传/校验全封装）
  compose.py           #   xfade 合成 + NVENC（失败回退 libx264）
  inspect.py           #   ffprobe / 抽帧
  schemas.py           #   function calling 工具 Schema
policy/playbook.md     # 领域 SOP（Agent 规划时整篇注入）
memory/lessons.jsonl   # 运行经验（自动沉淀）
tests/                 # 离线冒烟测试（用已交付歌曲真实数据做回归）
runs/<歌名>/            # 每次运行的工作区（events/report/plan/成片）
```

## 一条命令的产出

`runs/<歌名>/` 下会得到：

| 文件 | 说明 |
|---|---|
| `lyrics_raw.txt` | 歌词（秒↔文本，已过滤脏数据） |
| `plan.json` | Agent 制作计划（主题/意象流/字体/段数） |
| `events.json` + `report.json` | 逐句字幕时间轴 + 对齐质量报告 |
| `<歌名>_字幕验证版.mp4` | 黑底白字验证片（人工听感闸门） |
| `clips/clip01..N.mp4` | AI 生成的风景片段 |
| `<歌名>_歌词视频.mp4` | 正式成片（1080p，烧录字幕 + 原曲立体声） |
| `run_report.json` | 本次运行完整报告 |

## 测试

```bash
.venv/Scripts/python tests/test_lyrics.py        # 内嵌LRC/LRCLib/过滤（真实mp3）
.venv/Scripts/python tests/test_align.py         # 对齐回归（寂寞沙洲冷地面真值）
.venv/Scripts/python tests/test_orchestrator.py  # ASS/规划/修复循环/NVENC合成小样
```

# Lyric Video Agent

**输入一首歌，多 Agent 协同产出一条可发布的抖音歌词视频：正片（歌词对轴 + AI 风景 + 视觉自检）+ 竖版封面（选帧 + AI 背景 + AI 文案 + 行楷排版）。**

![tests](https://github.com/qiz7z/lyric-video-agent/actions/workflows/tests.yml/badge.svg)

从 25 首实际交付抖音歌词视频的生产流水线提炼而来的多 Agent 项目：底层工具全部经过
真实交付验证，LLM 在固定决策点出场，并补上了人工流程里最大的断点——画面质检。

```
视频管线：成本递增，人工闸门卡住昂贵环节
 ┌─────────────────────────────────────────────────────────┐
 │ mp3                                                     │
 │  │                                                      │
 │  ▼                                                      │
 │  ffmpeg 解码 wav ─────────────────────────────────────┐ │
 │                                                       │ │
 │  ├─► 歌词 (内嵌LRC / LRCLib)                          │ │
 │  │                                                    │ │
 │  ├─► 人声分离 (demucs) ◄─────────────────────────────┤ │
 │  │      │ 降级: 全曲包络                               │ │
 │  │                                                    │ │
 │  ├─► 对齐 (DP单调对齐)                                │ │
 │  │      │ 降级路由?                                    │ │
 │  │      ▼                                              │ │
 │  │  [修复循环] LLM function-calling                   │ │
 │  │      │ 质量门槛拦截劣化 ──► 回退当前最优            │ │
 │  │      ▼                                              │ │
 │  │  对齐完成                                           │ │
 │  │                                                    │ │
 │  ├─► 验证片 (黑底白字, ≈11MB) ◄───────────────────────┤ │
 │  │      几秒渲完，便宜可重渲                            │ │
 │  │                                                    │ │
 │  │  ┌─────────────────────────────────────────────┐   │ │
 │  │  │  【人工听感闸门】 ◄── 关键阻塞点            │   │ │
 │  │  │  确认对齐？                                   │   │ │
 │  │  │  ├── 否 ──► 终止（可重跑对齐）              │   │ │
 │  │  │  └── 是 ──► 进入昂贵环节                    │   │ │
 │  │  └─────────────────────────────────────────────┘   │ │
 │  │                                                   │ │
 │  ├─► 生片 (Agnes API, 贵) ──► 25-40分钟/首          │ │
 │  │      限流退避 / 断点续传                           │ │
 │  │                                                   │ │
 │  ├─► 视觉QC ──► 不合格? ──► 重生成 (≤2轮)          │ │
 │  │      │ 轮尽→人工兜底                              │ │
 │  │                                                   │ │
 │  └─► 合成 (xfade+字幕, NVENC→libx264回退)          │ │
 │                                                       │ │
 │  产出: plan.json + clips + 正式片 + 事件轴            │ │
 └─────────────────────────────────────────────────────────┘
         │
         │ (消费上游产物: plan + clips/正式片)
         ▼
```

```
封面 Agent：调研先行，每步带降级路径
歌名/歌手 ──► [调研步] LLM + search_web工具(≤4轮)
               搜背景/主题 ──► 输出: 视觉概念+生图提示词+文案启发
                         │
                         ▼
  ┌─────────────────────────────────────────┐
  │ 候选帧 ──► 选帧（多模态模型） ──► 降级: 中段帧  │
  │                 (有源视频时)            │
  │                  │                      │
  │                  ▼                      │
  │  生图（视频模型） ──► 降级: 帧裁竖版(代码)    │
  │       │                                 │
  │       ▼                                 │
  │  文案（文本模型） ──► 降级: 歌名兜底           │
  │       │                                 │
  │       ▼                                 │
  │  排版(代码: drawtext+行楷)              │
  │       │                                 │
  │       ▼                                 │
  │  QC(LLM) ──► 不合格? ──► 重生成背景×1  │
  └─────────────────────────────────────────┘
                         │
                         ▼
                  cover_final.png
               (1080×1440, 可直接发布)

**为什么封面是独立 Agent（面试三立论）**：
- **模态不同**：视频 Agent 驱动视频模型；封面 Agent 协同图片模型 + 文本模型 + 视觉模型，工具箱与失效模式完全不同
- **QC 闭环不同**：正片查人物/变形/离题；封面查文字可读性/竖版构图/截断——检查项、失败原因、修复动作均不相同
- **生命周期不同**：封面 Agent 可独立对任意已有视频补跑（`--skip-generate` 也能出封面），不需要重新生片——它是消费上游产物的独立服务，不是流水线的一个阶段

## 为什么是 Agent（不是调了 LLM 的脚本）

这个项目能成为 Agent 项目，靠三个核心特征，缺任何一个都只是"用了 LLM 的工具"：

| 特征 | 具体体现 | 面试可讲的细节 |
|---|---|---|
| **决策点（Decision Points）** | LLM 只在需要**判断力**的环节出场，其余全是确定性代码 | 规划/修复/质检三个决策点；规则写得完的用代码（段数=覆盖公式、人物词=正则），规则写不完的用 LLM |
| **工具调用（Tool Use）** | LLM 通过 **function calling** 自主选择工具、读观察、迭代决策 | 修复循环里 LLM 在 re_align/set_trim/accept 中选；封面调研 LLM 自主定关键词搜 1~4 轮 |
| **反馈闭环（Feedback Loop）** | 质量门槛自动拒绝劣化候选 + 记忆回写 lessons | 15.1s 劣化被拦截；每次运行沉淀经验，下次规划注入 |

缺哪个都站不住：没决策点 = 纯脚本；没工具调用 = LLM 只当文本处理器；没反馈闭环 = 错了就错了，不能自修复。

---

## 为什么值得看

- **真实生产背景**：不是玩具 demo。对齐算法、限流封装、续传逻辑全部来自 25 首已交付
  歌曲的实战迭代（对齐方案演进过 6 版），回归测试用人工逐行校验过的地面真值验证。
- **混合式 Agent 架构**：确定性流水线骨架 + LLM 决策点，而不是 LLM 自由循环。
  权衡分析见 [ARCHITECTURE.md](ARCHITECTURE.md) §1。
- **真 function-calling 修复循环**（ARCHITECTURE.md §4）：对齐走降级路由时，LLM 自主
  诊断报告、选择修复工具、根据执行观察决定下一步；质量门槛拒绝"路由升级但偏差劣化"
  的候选并自动回退——**E2E 实测拦截了一次 delta_max 15.1s 的劣化升级**。
- **双 Agent 协同**（ARCHITECTURE.md §6）：视频 Agent × 封面 Agent，模态/QC 闭环/
  生命周期三重不同。封面链路已用 Agnes 三真模型端到端实测——**封面先调研**：
  文本模型带着搜索工具自主查歌的背景（《梦的光点》搜出"动画《神兵小将》主题曲、
  林俊杰作曲"），再综合成视觉概念与英文生图提示词，文案从"看歌词猜"升级为
  "懂这首歌"（成品："追着那束光出发"）：

  ![封面样例](docs/cover_example.png)
- **核心算法有量化结果**：DP 单调对齐（LRC 软锚点 + 单调性约束 + 噪声段罚金），
  取代均匀量化方案（后者在回归中精确复现了历史上的"逐级漂移"事故）。
- **补上人工流程最大断点**：过去"人物变形无法自动判定，只能用户终审"；现在视觉模型
  逐帧质检 → 自动改写 prompt 重生成（≤2 轮修复循环）。
- **双层记忆**：`policy/playbook.md`（长期策略：领域 SOP，规划时整篇注入）+
  `memory/lessons.jsonl`（短期经验：每次运行自动沉淀，下次规划注入）。
- **成本与可靠性工程**：API 限流退避（429/503/SSL 抖动）、CDN 断点续传（Range +
  ftyp 校验）、NVENC 失败回退 libx264、全流程幂等可续跑、离线 MockLLM 测试模式。

## 对齐基准（已交付歌曲回归）

| 歌曲 | 路由 | 段/行 | 对比基准 | 起点偏差中位数 |
|---|---|---|---|---|
| 寂寞沙洲冷 | sequential | 34/20 | 人工逐行校验真值 | **0.00s** |
| 樱花草 | sequential | 86/64 | 生产版 events（用户验收） | **0.03s** |
| 梦的光点 | interp | 56/62 | LRC 估计 | 0.56s（修复循环实测拦截劣化升级） |

复现：`.venv/Scripts/python tests/test_align.py`

## 修复循环实测（真实歌曲，非演示）

对齐走降级路由（56 段 vs 62 行）时，修复循环在《梦的光点》上的真实执行轨迹：

```
[repair] r1: re_align {'merge_gap': 0.22} -> sequential dmax=15.138
         [REJECTED: delta_abs_max=15.138s 超过门槛 3.0s]   ← 系统自动回退
[repair] r2: accept                                       ← LLM 读到拒绝观察后收手
[repair] 最终 route=interp
```

教训与设计：把分段阈值调碎确实能让路由"升级"，但偏差被拉爆 6 倍——
**路由升级 ≠ 质量提升**。所以候选必须通过 `delta_abs_max ≤ 3s` 且整体不劣化的门槛，
拒绝原因回传给 LLM 并提示不要原样重试。

## 无 key 降级矩阵（每个环节都可独立降级，不阻塞）

| 缺失配置 | 行为 |
|---|---|
| 无 LLM key | 自动 mock 模式：规划用默认策略，全链路照常可跑（测试友好） |
| 无视觉模型 | 跳过自动质检，明确提示人工终审 |
| 无 demucs | 对齐降级全曲包络，报告标注（质量下降可见） |
| 无 Agnes key | 只产出验证片，生片环节跳过 |
| 无网络/搜索失败 | 封面调研步自动跳过，退回 plan 主题（背景/文案照常产出） |
| NVENC 不可用 | 自动回退 libx264 重编码 |

## 快速开始

```bash
# 1. 环境（建议复用已有 torch 以省几 GB）
python -m venv --system-site-packages .venv
.venv/Scripts/pip install -r requirements.txt -r requirements-demucs.txt

# 2. 配置 LLM（任何 OpenAI 兼容端点：DeepSeek / GLM / Qwen / Agnes / OpenAI...）
#    实测 Agnes 的 agnes-2.5-flash 同时支持文本与视觉（读图），可全栈免费：
copy config.example.json config.json   # 填入 api_key；或用环境变量 LVA_LLM_API_KEY

# 3. 先离线走一遍链路（MockLLM，不花一分钱，~25s）
.venv/Scripts/python -m agent.cli "梦的光点" --audio "C:/path/梦的光点 - 王心凌.mp3" --mock --yes --skip-generate

# 4. 正式运行（人工听感闸门在验证片之后，确认对齐才开始生片）
.venv/Scripts/python -m agent.cli "梦的光点" --audio "C:/path/梦的光点 - 王心凌.mp3"
```

常用选项：`--skip-generate` 跳过生片 / `--skip-qc` 跳过视觉质检 /
`--skip-repair` 跳过修复循环 / `--trim 50` 裁掉 50s 前奏 / `--artist` 提高 LRCLib 命中率。

## 目录

```
agent/                 # Agent 层
  cli.py               #   命令行入口
  orchestrator.py      #   流水线编排（视频 Agent + 封面 Agent + 人工闸门）
  planner.py           #   [决策点] 制作规划（LLM 生成 + 确定性校验闭环）
  repair.py            #   [决策点] function-calling 修复循环（诊断→选工具→质量门槛）
  verifier.py          #   [决策点] 视觉质检 + 重生成循环
  cover.py             #   [决策点] 封面 Agent（调研/选帧/背景/文案/排版/QC）
  llm.py               #   OpenAI 兼容客户端 + MockLLM（离线测试）
  memory.py            #   playbook（长期策略）+ lessons（运行经验）
tools/                 # 工具层（纯确定性函数，可独立单测）
  lyrics.py            #   内嵌 LRC / LRCLib / 繁简转换 / 脏数据过滤
  audio.py             #   ffmpeg / demucs 封装 / RMS 包络
  research.py          #   歌曲调研（ddgs 网页搜索 + MusicBrainz + 本地元数据）
  align.py             #   ★ 字幕-人声对齐（三路路由 + DP 单调对齐，参数可覆盖）
  ass.py               #   ASS 字幕渲染（fad-only 极简策略）
  videogen.py          #   Agnes 视频 API 客户端（限流/续传/校验全封装）
  imagogen.py          #   Agnes 图片 API 客户端 + 竖版裁切
  typography.py        #   封面排版（drawtext + 中文字体，模型画图代码写字）
  compose.py           #   xfade 合成 + NVENC（失败回退 libx264）
  inspect.py           #   ffprobe / 抽帧
  schemas.py           #   function calling 工具 Schema
policy/playbook.md     # 领域 SOP（Agent 规划时整篇注入）
memory/lessons.jsonl   # 运行经验（自动沉淀）
tests/                 # 离线冒烟测试（用已交付歌曲真实数据做回归）
docs/                  # 成品样例（封面等）
runs/<歌名>/            # 每次运行的工作区（events/report/plan/成片/封面）
pyproject.toml         # 项目元数据 + ruff 配置
LICENSE                # MIT
```

## 工程规范

- **Lint/Format**：ruff 双关卡（CI 强制）。`pyproject.toml` 里的每条豁免都附理由：
  如 `BLE001`（盲捕获）在重试密集的网络代码里是有意设计（见 ARCHITECTURE §7 故障矩阵）。
- **语义化修复示例**：`zip` 显式 `strict` 按语义二选——段↔子句配对处 `strict=True`
  （长度已校验相等，防静默截断），单调性检查处 `strict=False`（两边长度差一）。
- 本地自检命令：

```bash
.venv/Scripts/python -m ruff check .      # lint
.venv/Scripts/python -m ruff format .     # format
```

## 一条命令的产出

`runs/<歌名>/` 下会得到：

| 文件 | 说明 |
|---|---|
| `lyrics_raw.txt` | 歌词（秒↔文本，已过滤脏数据） |
| `plan.json` | Agent 制作计划（主题/意象流/字体/段数） |
| `events.json` + `report.json` | 逐句字幕时间轴 + 对齐质量报告（含修复决策历史） |
| `<歌名>_字幕验证版.mp4` | 黑底白字验证片（人工听感闸门，≈11MB/3.5min歌） |
| `clips/clip01..N.mp4` | AI 生成的风景片段 |
| `<歌名>_歌词视频.mp4` | 正式成片（1080p，烧录字幕 + 原曲立体声） |
| `cover_final.png` | 封面 Agent 产物（1080×1440 竖版，可直接发布） |
| `cover_decision.json` | 封面 Agent 每步决策记录（选帧/背景模式/文案/QC） |
| `run_report.json` | 本次运行完整报告 |

## 测试

```bash
.venv/Scripts/python tests/test_lyrics.py        # 内嵌LRC/LRCLib/过滤（真实mp3）
.venv/Scripts/python tests/test_align.py         # 对齐回归（寂寞沙洲冷地面真值）
.venv/Scripts/python tests/test_orchestrator.py  # ASS/规划/修复循环/NVENC合成小样
.venv/Scripts/python tests/test_cover.py         # 封面Agent离线链（真实抽帧+排版）
```

数据依赖型测试使用已交付歌曲的本机文件，缺失时自动 SKIP——CI（GitHub Actions）
上跑纯离线部分。测试刻意保持"零依赖独立脚本"形态而非 pytest 参数化：
CI 免装额外框架，且每个脚本可单独运行。

## 设计文档

[ARCHITECTURE.md](ARCHITECTURE.md) 覆盖：为什么不用 LLM 自由循环、规划器生成-校验闭环、
DP 对齐算法与三路路由、修复循环与质量门槛、视觉质检、成本/可靠性工程、记忆设计、
以及诚实的[已知边界](ARCHITECTURE.md#9-已知边界诚实声明)。

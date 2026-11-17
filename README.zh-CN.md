<img src="assets/readme-banner.png" alt="EvolveMemory — 面向 AI 助手的可治理记忆" width="100%" />

# EvolveMemory

**让 AI 在长期相处中形成、修正对人的理解，并自然适配对话的记忆运行时。**

<p align="center">
  <a href="README.md">English</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="docs/runtime-reference.zh-CN.md">文档</a> ·
  <a href="#状态与路线">路线</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-ff5aa5" alt="Python 3.11+" />
  <a href="https://github.com/2sao7sao/EvolveMemory/actions/workflows/ci.yml"><img src="https://github.com/2sao7sao/EvolveMemory/actions/workflows/ci.yml/badge.svg" alt="CI 工作流状态" /></a>
  <img src="https://img.shields.io/badge/stage-research_prototype-b8eee4" alt="研究原型" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-ff5aa5" alt="MIT 许可证" /></a>
</p>

**真实试验更新：**[Draft PR #17](https://github.com/2sao7sao/EvolveMemory/pull/17)已接通真实 DeepSeek 宿主。24轮试验能恢复旧项目决定，但偏好纠正出现内部反向强化；[实际对话与P0缺陷](https://github.com/2sao7sao/EvolveMemory/blob/feat/live-project-continuation-20261116/docs/live-evaluation-results.md)和工程测试结果分开记录。PR #17尚未合并；下文无provider等表述属于PR #16历史基线。

## 为什么做 EvolveMemory

长期协作需要的不只是记住事实：助手应逐渐理解稳定偏好、变化与情境，在被纠正后改变，并把理解自然融入回答。EvolveMemory 用可检查的证据、记忆更新与控制来探索这种体验。项目任务续接是首个验证场景，长期协作、陪伴与知己式体验是愿景。

| 能力 | 当前范围 |
| --- | --- |
| 形成与修正理解 | 根据独立来源 turn 自动适配画像，并支持证据更新与纠错；U0 规则/API 切片本地通过，实际体验尚未验收。 |
| 治理写入 | 规则抽取或真实模型提案，通过 `llm_payload` 校验；创建、合并、按设置审查、拒绝或仅保留本轮。 |
| 控制用途 | 将记忆编译为事实、风格、事件提示、约束、澄清、摘要或抑制。 |
| 纠错与复现 | 本地 JSON / SQLite、review、删除、forget-all、审计及确定性回归。 |
| 真实对话验证 | 有限历史窗口的 DeepSeek 宿主，记录实际请求、回答与记忆决策，并保留近期上下文对照组。 |

当前研究原型已包含真实 DeepSeek provider 和有限历史窗口的多轮宿主，同时保留离线规则运行时。2026-11-16 用户取代了“画像确认后才适配”的旧选择：普通偏好证据充分时自动适配，弱证据暂存或不使用，不默认逐条询问。设置、scope、来源有效性与关闭记忆继续生效。真实模型项目续接正在评估；广泛的稳定/变化/情境判断和自然体验尚未验收。

## 快速开始

需要 Python 3.11+。回放在本地运行，不需要模型 API Key。

```bash
git clone https://github.com/2sao7sao/EvolveMemory.git
cd EvolveMemory
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m memory_system.demo
```

预期输出包含 `status: PASS`、`accepted_candidates: 4/4` 与 `gate_eval: 8/8`。这些是固定回放检查，不是生产质量分数。

启动原型 API：

```bash
python -m uvicorn app:app --reload
```

在 `http://127.0.0.1:8000/docs` 查看接口。SQLite 配置与 Python 用法见[运行时参考](docs/runtime-reference.zh-CN.md#developer-surface)。

### 真实 DeepSeek 对话

安装依赖后，可运行 24 轮**合成用户脚本 + 真实 `deepseek-flash` 回答**。脚本会自行启动本地 API，对比记忆组与仅近期上下文组：

```bash
python examples/run_live_conversation.py \
  --api-key-file /absolute/private/path/deepseek-key.txt \
  --model deepseek-flash \
  --output data/live-runs/run-01
```

指向已有私有密钥文件，不把密钥复制进仓库或命令文本。输出目录必须不存在或为空。默认限制为 **150 次逻辑 provider 调用**与 **2 美元估算费用保护**，不等于 provider 账单硬上限；重试和失败调用也可能收费。这条命令会发起付费外部模型调用。可选参数、边界与产物见[真实运行契约](docs/runtime-reference.zh-CN.md#live-deepseek-conversation)。

运行后打开 `data/live-runs/run-01/transcript.html` 或 `transcript.md`。逐轮 JSON、`provider_calls.jsonl` 和 `manifest.json` 保留实际交付上下文、原始回答、失败、用量与费用估算。运行完成只证明执行过，不代表自然理解已通过验收。

## 工作流程

```text
用户输入 → 候选记忆 → 写入治理 → 本地存储
当前问题 → 检索 → 使用门控 → 回答策略 → Prompt 上下文
反馈 → 纠错 / 退役 → 审计
```

<img src="assets/runtime_contract_map_v2.svg" alt="记忆运行模式：观察、写入、检索、适配、纠错与审计" width="100%" />

使用门控决定什么可以进入 Prompt；检索分数本身不授予使用权限。真实宿主只保留最近两组用户/助手对话，切换 session 时清空；抽取候选并校验证据与保留期限，经 v2 治理写入后获取最多 50 条受控候选，让模型选择最多 10 个 ID，再通过同一查询与 Prompt 治理路径复核后回答。这不读取过去会话全文；初始候选排序仍使用确定性哈希 embedding 替身。详见[评分与接口](docs/runtime-reference.zh-CN.md)、[门控规则](docs/gate-decision-rules.md)和[架构方案](docs/next-development-spec.md)。

## 复现实例

回放写入两条合成用户输入，在不同任务中查询，最后执行纠错：

| 输入 | 期望行为 |
| --- | --- |
| “我最近准备面试”与“先给结论” | 分别保存事件与沟通偏好。 |
| 询问如何准备面试 | 将事件作为追问线索，并应用风格偏好。 |
| 只做 Python review，明确不要提面试 | 抑制面试信息，保留允许的风格指导。 |
| 要求不再记住焦虑 | 退役敏感状态及其派生画像信号。 |

这段既有回放使用独立 session runtime；其中追问示例不代表 v2 事件追问已经开启。v2 默认逐事件关闭，详见[v2 接口](docs/runtime-reference.zh-CN.md)。

```bash
python examples/replay_adaptive_memory.py
python -m unittest discover -s tests -p 'test_*.py'
python -m evals.runner --suite all
```

已合并的 [PR #15](https://github.com/2sao7sao/EvolveMemory/pull/15) 基线通过 115 个本地测试（另有 72 个 pytest subtest）、11 个确定性评估套件、独立 replay 和[远端 CI](https://github.com/2sao7sao/EvolveMemory/actions/runs/43906016401)。这些结果属于此前控制/scope 切片，包含如今被取代的画像确认规则。随后 **PR #16 的 U0 基线通过 157 个本地测试（另有 101 个 pytest subtest）、11 个确定性套件与 replay PASS**，使用独立临时数据目录，未调用 provider，见 [PR #16](https://github.com/2sao7sao/EvolveMemory/pull/16)。这些历史检查不验证新增真实宿主，也不代表 U01–U08 体验已验收；真实运行的对话与请求记录须单独评估召回、纠错及自然适配，详见[维护证据](docs/maintenance.md)。

最新真实试验：24 轮×两组完整回答，旧决定与纠正后的试点范围可恢复，但偏好否定被误读并形成错误画像，状态字段也未正确写入。**项目事实续接有收益，偏好纠正未通过**。最终代码通过 205 tests / 165 subtests 与 11 个确定性套件；[实际对话节选、全部试验结果和优先缺陷](docs/live-evaluation-results.md)单独记录，不能用工程测试代替体验验收。

## 状态与路线

**朝长期、可修正的理解推进，先在项目协作中验证。**

| 阶段 | 下一步 | 完成证据 |
| --- | --- | --- |
| U0 — 本地通过 | 证据驱动的自动画像适配 | 规则/API 回归通过；远端发布与用户体验验收分别记录。 |
| S1-a / S0-c — 评估中 | 真实 provider 有限窗口宿主、临时保留校验及受控模型选择已实现 | 检查实际交付输入和后续回答是否遵守当前要求、纠错与 scope；实现不等于体验验收。 |
| S1 体验 | 有用的项目任务续接 | 回查旧决定，被纠正后改变，不反复提醒记忆或提及无关旧事。 |
| S2–S4 | 长期理解与真实模型纵向评测 | 区分稳定偏好、持续变化与情境例外，长期测量帮助程度与纠正成本。 |

[Draft PR #12](https://github.com/2sao7sao/EvolveMemory/pull/12)记录修正后的方向与剩余协议。首个项目场景不把产品愿景缩减为任务跟踪。愿景、实现与未验证行为的区别见[定位](docs/positioning.md)、[开发路线](docs/next-development-spec.md)和[体验验收 U01–U08](docs/next-development-spec.md#fixed-experience-acceptance)。

## 文档与素材

| 入口 | 内容 |
| --- | --- |
| [对话记忆协议](docs/conversation-memory-invocation-spec.md) | 自主理解、来源与范围边界、交付捕获和固定体验验收；完整协议尚未完成。 |
| [运行时参考](docs/runtime-reference.zh-CN.md) | 检索数学、激活、因果相关性、写入治理、Python 与 HTTP 接口。 |
| [回放说明](examples/adaptive_memory_replay.md) | 输入、输出与固定检查能够证明的范围。 |
| [维护记录](docs/maintenance.md) | 当前证据、优先级待办及展示素材清单。 |
| [产品定位](docs/positioning.md) · [Phase 2 设计](docs/phase2-optimization-spec.md) | 使用范围与后续架构；目标值不是实测结果。 |

## 贡献与相关项目

参见 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [SECURITY.md](SECURITY.md)。使用合成样例，不提交真实对话、本地存储、凭据和含隐私的调试导出。许可证为 [MIT](LICENSE)。

相关项目：[Agent Peak Bench](https://github.com/2sao7sao/agent-peak-bench) 用于 Agent 评估，[EvolveKB](https://github.com/2sao7sao/EvolveKB) 用于知识工作流，[Video Analysis Skills](https://github.com/2sao7sao/video-analysis-skills) 用于结构化视频分析。它们是独立仓库，不代表已经集成为同一产品。

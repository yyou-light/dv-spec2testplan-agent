# DV Spec2Testplan Agent

DV Spec2Testplan Agent 是一个面向数字 IC 验证工作的 Spec 解析工具。它读取 Markdown 格式的硬件规范，调用大模型提取验证测试点，并导出结构化 CSV。

项目采用 Maker-Checker 流程：

- Maker 从 Spec 中提取测试点。
- Critic 可选开启，用于检查是否存在漏测。
- Cluster 将测试点按接口、功能、场景、异常、上报、corner 等维度归类。
- Skills 根据 AXI、SRAM、反压等关键词注入验证经验。

## 兼容性说明

默认运行方式保持原版行为：使用用户提供的 OpenAI-compatible API Key。已有用户继续按原方式配置 `.env` 即可。

Codex CLI 后端是可选能力。只有显式传入 `--backend codex`，或在 `.env` 中设置 `DV_LLM_BACKEND="codex"`，才会使用本机 Codex/ChatGPT 账号额度。

## 快速开始

安装依赖：

```powershell
pip install -r requirements.txt
```

复制配置文件：

```powershell
copy .env.example .env
```

默认 API 模式配置：

```env
DV_LLM_API_KEY="your_api_key_here"
DV_LLM_BASE_URL="https://api.deepseek.com"
DV_LLM_MODEL_NAME="deepseek-chat"
```

交互式运行：

```powershell
python planner.py
```

命令行运行：

```powershell
python planner.py --input example_spec.md --output out.csv --audit
```

使用 Codex CLI 后端：

```powershell
python planner.py --backend codex --input example_spec.md --output out.csv --no-audit
```

## 用户手册

完整说明见 [docs/USER_MANUAL.md](docs/USER_MANUAL.md)，包括：

- 安装与配置
- 项目基本架构
- API 模式和 Codex CLI 模式
- 命令行参数
- CSV 输出列说明
- Skills 扩展方式
- 常见问题处理
- 结果质量检查建议

用户最常维护的是 `prompts/skills/`。如果要让工具更懂某类协议或接口，不要先改 Python 代码，优先维护对应 skill 文件。手册里的 [Skills 在哪里，怎么维护](docs/USER_MANUAL.md#7-skills-在哪里怎么维护) 说明了文件结构、规则写法和验证流程。

## 主要文件

- `planner.py`：主入口，负责切块规划、提取闭环、建树和 CSV 导出。
- `codex_client.py`：可选 Codex CLI 后端，提供 OpenAI chat 兼容包装。
- `extractor.py`：Maker，负责测试点提取。
- `critic.py`：Checker，负责漏测审计。
- `cluster.py`：标签归类和测试点树构建。
- `chunker.py`：根据切块规划执行 Markdown 物理切块。
- `schemas.py`：Pydantic 数据结构约束。
- `prompts/`：Prompt 分层配置。
- `prompts/skills/`：协议和验证经验技能库。
- `AI_HANDOFF.md`：给后续 AI 或维护者的交接说明。

## 验证命令

```powershell
python -m compileall -q planner.py codex_client.py extractor.py cluster.py critic.py schemas.py chunker.py
```

## 维护原则

不要为了适配某个模型修改原版 Prompt、Schema 或测试点生成语义。当前 Codex CLI 能稳定输出可用结果的前提，是保留原版生成逻辑，只替换调用通道。

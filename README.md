# DV Spec2Testplan Agent

DV Spec2Testplan Agent 是一个面向数字 IC 验证工作的命令行工具。它读取硬件 Spec，调用大模型生成 DV 测试点，并导出结构化 CSV，方便验证工程师继续评审、补充和落地到 testplan。

这个项目适合做三件事：

- 从 IP/模块 Spec 生成初版测试点列表。
- 按接口、功能、场景、异常、上报、corner 等维度归类测试点。
- 通过 `prompts/skills/` 沉淀团队的协议和验证经验。

它不替代人工评审。最终 testplan 仍需要验证工程师确认覆盖是否完整、测试点是否有意义、是否存在误判或重复。

## 支持的输入

当前支持本地文件输入：

| 格式 | 扩展名 | 说明 |
| --- | --- | --- |
| Markdown | `.md`、`.markdown` | 推荐格式，标题结构保留最完整 |
| 文本 | `.txt`、`.text` | 会根据编号、中文章节、Setext 标题等规则推断章节 |
| Word | `.docx` | 会读取标题样式、段落和表格 |
| PDF | `.pdf` | 会提取文本并推断章节 |

网页 URL 和 HTML 文件暂不作为直接输入。需要处理网页 Spec 时，先保存或转换为 Markdown/文本文件，再作为 `--input` 传入。

## 快速开始

安装依赖：

```powershell
pip install -r requirements.txt
```

复制配置文件：

```powershell
copy .env.example .env
```

默认 API 模式使用 OpenAI-compatible API。编辑 `.env`：

```env
DV_LLM_API_KEY="your_api_key_here"
DV_LLM_BASE_URL="https://api.deepseek.com"
DV_LLM_MODEL_NAME="deepseek-chat"
```

运行示例：

```powershell
python planner.py --input example_spec.md --output out.csv --audit
```

输出文件是 CSV，使用 UTF-8 with BOM，通常可以直接用 Excel 打开。

## 推荐工作流

1. 先检查输入适配结果，尤其是 Word、PDF、非标准文本：

```powershell
python planner.py --input spec.docx --dump-normalized-spec normalized.md --normalize-only
```

2. 快速试跑，确认链路和输出风格：

```powershell
python planner.py --input spec.docx --output draft.csv --no-audit
```

3. 正式生成时开启审计，减少漏测：

```powershell
python planner.py --input spec.docx --output final.csv --audit
```

4. 人工评审 CSV。重点看测试点是否有明确验证意图、是否能反查原文、是否覆盖异常和边界场景。

5. 如果某类协议输出不够好，优先维护 `prompts/skills/`，不要先改 Python 代码。

## 模型后端

默认后端保持原版行为：使用用户提供的 OpenAI-compatible API Key。

```powershell
python planner.py --backend openai --input example_spec.md --output out.csv --audit
```

也可以显式使用本机 Codex CLI 后端。这会消耗当前 Codex/ChatGPT 账号自己的会员额度，不会外接 API。

```powershell
python planner.py --backend codex --input example_spec.md --output out.csv --no-audit
```

Codex CLI 后端不是默认模式，避免影响已有 API 用户。

## 输出 CSV

主要列包括：

| 列名 | 用途 |
| --- | --- |
| `测试点编号` | 自动生成的树状编号 |
| `一级分类` / `二级分类` | 测试点归类 |
| `优先级` | `P0`、`P1`、`P2` |
| `测试点摘要` | 测试点的一句话目的 |
| `详细描述` | 需要验证的行为、观察点或期望结果 |
| `原文溯源` | 对应 Spec 原文，便于人工反查 |
| `存疑` / `缺陷/二义性说明` | 需要设计或架构澄清的问题 |

CSV 行数不是质量标准。更重要的是每条测试点是否具体、无歧义、能指导验证工作。

## Skills 怎么维护

用户最常维护的是：

```text
prompts/skills/
```

每个 skill 用来描述某类协议、接口或验证经验，例如 AXI、SRAM、反压等。它通常包含：

- `keywords`：命中哪些词时启用这个 skill。
- `explicit_rules`：原文明确写到时必须提取的规则。
- `implicit_rules`：基于团队验证经验允许补充的测试点。

新增或修改 skill 后，建议用同一份 Spec 前后对比 CSV，确认新增内容是有效覆盖，不是无意义扩写。

完整写法见 [用户手册：Skills 在哪里，怎么维护](docs/USER_MANUAL.md#7-skills-在哪里怎么维护)。

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `planner.py` | 主入口，负责整体流程和 CSV 导出 |
| `spec_loader.py` | 输入适配层，将 md/txt/docx/pdf 转成标准 Markdown |
| `extractor.py` | Maker，负责从文档块提取测试点 |
| `critic.py` | Critic，负责可选漏测审计 |
| `cluster.py` | 负责测试点归类和树状编号 |
| `chunker.py` | 按切块计划拆分 Spec |
| `codex_client.py` | 可选 Codex CLI 后端 |
| `schemas.py` | 输出数据结构约束 |
| `prompts/` | Prompt 和 skills |
| `docs/USER_MANUAL.md` | 用户手册 |
| `AI_HANDOFF.md` | 给后续维护者或 AI 的交接说明 |

## 常用命令

交互式运行：

```powershell
python planner.py
```

只检查输入适配，不调用大模型：

```powershell
python planner.py --input spec.pdf --dump-normalized-spec normalized.md --normalize-only
```

运行自动化测试：

```powershell
python -m unittest discover -s tests
```

语法检查：

```powershell
python -m compileall -q planner.py spec_loader.py codex_client.py extractor.py cluster.py critic.py schemas.py chunker.py
```

## 更多文档

- [用户手册](docs/USER_MANUAL.md)：安装、配置、架构、输入适配、CSV 输出、skills 维护、常见问题。
- [AI 交接说明](AI_HANDOFF.md)：当前状态、关键设计约束、验证记录和后续维护注意事项。

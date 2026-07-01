# 用户手册

本文面向使用者说明如何安装、配置、运行 DV Spec2Testplan Agent，以及如何检查输出结果。

## 1. 工具用途

DV Spec2Testplan Agent 用于将 Markdown 格式的硬件 Spec 转换为验证测试点列表。典型输入是一份模块级或子系统级设计规范，典型输出是一份 CSV 文件，供验证计划评审、用例拆分或后续自动化流程使用。

工具适合以下场景：

- 从设计规范中快速提取初版 DV testplan。
- 检查 Spec 中是否存在漏测风险。
- 标注条件缺失、时序不清或描述矛盾的地方。
- 基于 AXI、SRAM、反压等协议经验补充隐式验证点。

工具不替代人工评审。它生成的是测试计划草案，仍需要验证工程师确认优先级、场景完整性和二义性标注。

## 2. 运行环境

需要 Python 和项目依赖：

```powershell
pip install -r requirements.txt
```

当前依赖：

- `openai>=1.0.0`
- `pydantic>=2.0.0`
- `python-dotenv>=1.0.0`

如果使用 Codex CLI 后端，还需要本机已安装并登录 Codex。

## 3. 配置方式

### 3.1 默认 API 模式

默认模式保持原版行为，使用 OpenAI-compatible API。复制配置文件：

```powershell
copy .env.example .env
```

填写：

```env
DV_LLM_API_KEY="your_api_key_here"
DV_LLM_BASE_URL="https://api.deepseek.com"
DV_LLM_MODEL_NAME="deepseek-chat"
```

说明：

- `DV_LLM_API_KEY`：用户自己的 API Key。
- `DV_LLM_BASE_URL`：OpenAI-compatible 服务地址。
- `DV_LLM_MODEL_NAME`：模型名称，默认建议保持 `deepseek-chat`。

### 3.2 可选 Codex CLI 模式

Codex CLI 模式用于不外接 API、改用当前用户本机 Codex/ChatGPT 会员额度的场景。

一次性使用：

```powershell
python planner.py --backend codex --input example_spec.md --output out.csv --no-audit
```

长期使用时，可在 `.env` 中加入：

```env
DV_LLM_BACKEND="codex"
DV_CODEX_MODEL="gpt-5.5"
DV_CODEX_SANDBOX="read-only"
DV_CODEX_TIMEOUT_SEC="1800"
DV_CODEX_IGNORE_USER_CONFIG="1"
```

可选指定 Codex 可执行文件路径：

```env
DV_CODEX_EXE="C:\\Users\\yyou\\AppData\\Local\\OpenAI\\Codex\\bin\\codex.exe"
```

注意：Codex CLI 不是默认模式，避免影响已有 API 用户，也避免无意消耗用户 Codex 额度。

## 4. 运行方式

### 4.1 交互式运行

```powershell
python planner.py
```

程序会提示输入 Spec 路径，并询问是否开启 Critic 审计。

### 4.2 命令行运行

```powershell
python planner.py --input example_spec.md --output out.csv --audit
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--input` / `-i` | 输入 Markdown Spec 路径 |
| `--output` / `-o` | 输出 CSV 路径 |
| `--backend openai` | 使用默认 API 后端 |
| `--backend codex` | 使用本机 Codex CLI 后端 |
| `--audit` | 开启 Critic 漏测审计 |
| `--no-audit` | 关闭 Critic，加快运行 |

建议：

- 快速试跑时使用 `--no-audit`。
- 正式评审前使用 `--audit`。
- 大文档运行时间较长，建议明确指定 `--output`，避免重复运行后找不到产物。

## 5. 处理流程

工具内部流程如下：

1. 读取 Markdown Spec。
2. 提取目录和前言信息。
3. 生成全局上下文和语义切块计划。
4. 按章节切分文档。
5. Maker 按块提取测试点。
6. 如果开启 `--audit`，Critic 检查漏测并触发补提。
7. Cluster 将测试点标签归类为树状结构。
8. 导出 CSV。

## 6. CSV 输出说明

输出文件使用 UTF-8 with BOM，便于 Excel 打开。

| 列名 | 说明 |
| --- | --- |
| `测试点编号` | 自动生成的树状编号 |
| `一级分类` | 接口类、功能类、场景类、异常类、上报类、corner类等 |
| `二级分类` | 由模型根据 raw tag 聚合得到的子类 |
| `优先级` | `P0`、`P1`、`P2` |
| `特征标签` | 原始测试点标签 |
| `测试点摘要` | 一句话说明测试目的 |
| `详细描述` | 测试行为、观察点或期望结果描述 |
| `原文溯源` | 对应 Spec 原文，便于反查 |
| `存疑` | Spec 可能存在二义性时标记 |
| `缺陷/二义性说明` | 需要设计或架构澄清的问题 |

## 7. Skills 扩展

协议经验位于 `prompts/skills/`。当前包含：

- `axi.md`
- `sram.md`
- `backpressure.md`

每个 skill 通常包含三部分：

- `# keywords`：触发关键词。
- `# explicit_rules`：原文明确写到时必须覆盖的规则。
- `# implicit_rules`：基于验证经验应补充的隐式测试点。

新增 skill 时应保持规则具体、可验证，避免写成泛泛的建议。`implicit_rules` 应用于补充常见验证风险，不应替代 Spec 本身。

## 8. 结果检查建议

人工 review 时建议关注：

- 测试点是否能追溯到原文或明确的隐式规则。
- P0 是否覆盖核心数据通路、复位、使能和基本读写。
- 异常类是否覆盖非法 burst、越界、非对齐、关闭状态访问等。
- 场景类是否覆盖反压、背靠背、并发、边界切换等组合行为。
- “存疑”列是否真的指向需要澄清的问题。
- 是否存在可接受的重复。少量重复通常比漏掉验证维度更安全。

不要只用行数判断质量。更重要的是测试点是否有明确验证意图、覆盖范围是否合理、原文反标是否可信。

## 9. 常见问题

### 未检测到 `DV_LLM_API_KEY`

默认后端是 API 模式。请复制 `.env.example` 为 `.env` 并填写 API Key，或显式使用 Codex CLI：

```powershell
python planner.py --backend codex --input example_spec.md --output out.csv --no-audit
```

### Codex CLI 提示模型不支持

确认 `.env` 中的 `DV_CODEX_MODEL` 是当前账号可用的模型。当前验证过的配置是：

```env
DV_CODEX_MODEL="gpt-5.5"
```

### 找不到 Codex CLI

确认 Codex 已安装并登录。必要时在 `.env` 中指定：

```env
DV_CODEX_EXE="C:\\Users\\yyou\\AppData\\Local\\OpenAI\\Codex\\bin\\codex.exe"
```

### CSV 被 Excel 占用

关闭正在打开的 CSV 后重试。程序遇到权限问题时会尝试生成备用文件名。

### 控制台中文显示乱码

通常是 Windows 控制台编码问题，不代表 CSV 文件损坏。CSV 使用 `utf-8-sig` 写入，Excel 通常可以正常识别。

### 输出为空或格式校验失败

可能原因：

- 输入 Spec 内容过短或目录结构不完整。
- 模型输出不是合法 JSON。
- Prompt 中的 schema 约束未被模型遵守。

建议先关闭审计，用示例文件验证基础链路：

```powershell
python planner.py --input example_spec.md --output smoke.csv --no-audit
```

## 10. 维护边界

当前高质量输出依赖原版生成逻辑。后续维护应优先改进运行稳定性、文档、日志和错误提示，不应随意改动：

- `prompts/layer1_meta.md`
- `prompts/layer2_base.md`
- `prompts/skills/`
- `schemas.py`
- `extractor.py` 中的测试点生成规则

如果必须优化生成质量，应先准备人工认可的 golden 输出，再做 A/B 对比。

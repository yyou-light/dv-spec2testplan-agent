# 用户手册

这份手册面向两类用户：

- 使用者：拿一份 Spec，生成测试点 CSV。
- 验证知识维护者：维护 `prompts/skills/`，让工具更懂团队的协议、接口和验证经验。

如果你只是运行工具，先看第 1、2、4、5、6 节。如果你要理解项目基本架构或维护测试点生成质量，重点看第 3、7、8 节。

## 1. 这个项目做什么

DV Spec2Testplan Agent 用来把硬件 Spec 转成验证测试点列表。

输入：

- 标准 Markdown：`.md`、`.markdown`
- 非标准文本：`.txt`、`.text`
- Word 文档：`.docx`
- PDF 文档：`.pdf`

当前不直接支持网页 URL 或 HTML 文件。遇到网页 Spec 时，需要先保存或转换为 Markdown/文本文件，再作为输入。

输出：

- CSV 测试点表，包含分类、优先级、测试点摘要、详细描述、原文反标和二义性说明。

它适合生成初版 DV testplan，但不替代人工评审。验证工程师仍需要检查测试点是否有价值、是否覆盖完整、是否存在重复或误判。

## 2. 用户视角的项目结构

你通常只需要关心这几类文件：

| 你要做的事 | 主要看哪里 |
| --- | --- |
| 配置模型 | `.env`、`.env.example` |
| 运行工具 | `planner.py` |
| 输入适配 | `spec_loader.py` |
| 准备输入 | `example_spec.md` 或自己的 md/txt/docx/pdf Spec |
| 查看输出 | 生成的 `*.csv` |
| 维护验证经验 | `prompts/skills/*.md` |
| 调整全局提取纪律 | `prompts/layer1_meta.md`、`prompts/layer2_base.md` |
| 理解用户操作 | `README.md`、`docs/USER_MANUAL.md` |
| 交接给 AI/维护者 | `AI_HANDOFF.md` |

项目内部处理流程如下：

```mermaid
flowchart TD
    A["原始 Spec: md/txt/docx/pdf"] --> L["spec_loader.py 标准化"]
    L --> B["planner.py"]
    B --> C["提取目录和前言"]
    C --> D["LLM 生成切块计划"]
    D --> E["chunker.py 物理切块"]
    E --> F["extractor.py / Maker 提取测试点"]
    F --> G{"是否开启 --audit"}
    G -- 是 --> H["critic.py / Critic 查漏"]
    H --> F
    G -- 否 --> I["cluster.py 标签归类"]
    H --> I
    I --> J["导出 CSV"]
    K["prompts/skills/*.md"] --> F
```

从用户角度看，`prompts/skills/` 是最重要的可维护部分。它决定模型在看到 AXI、SRAM、ready、反压等关键词时，会额外带上哪些验证经验。

## 3. 项目基本架构

### 3.1 Planner

入口文件是 `planner.py`。它负责：

- 读取 Spec。
- 提取目录和前言。
- 调用大模型生成切块计划。
- 调用 Maker/Critic/Cluster。
- 导出 CSV。

普通用户不需要改它，只需要运行它。

### 3.2 Backend

当前有两个后端：

- 默认后端：OpenAI-compatible API。老用户继续使用 `.env` 中的 API Key。
- 可选后端：Codex CLI。显式使用 `--backend codex` 时才启用。

后端只负责“怎么调用模型”，不应该改变测试点生成逻辑。

### 3.3 Input Adapter

`spec_loader.py` 是输入适配层。它负责把不同来源的 Spec 转成内部统一使用的标准 Markdown。

它当前支持：

- 标准 Markdown：直接读取，不重写标题。
- 非标准 `.txt`：根据 `1.`、`1.1`、`第一章`、`一、`、Setext 标题等规则恢复 Markdown 标题。
- `.docx`：读取 Word 标题样式、段落和表格，并转成 Markdown。
- `.pdf`：提取页面文本，再按文本标题规则恢复 Markdown 标题。

输入适配层只处理结构，不生成测试点。这样可以提升格式兼容性，同时不破坏原来的 Maker/Critic 生成质量。

如果控制台提示结构置信度为 `low`，通常表示章节识别不充分。建议先用 `--dump-normalized-spec` 导出中间文件，手动确认标题结构，再决定是否需要把原始文档整理成更清晰的 Markdown。

### 3.4 Maker

`extractor.py` 是 Maker，负责从每个文档块中提取测试点。它会组合四层 Prompt：

- `prompts/layer1_meta.md`：全局角色和提取纪律。
- `prompts/layer2_base.md`：通用验证原则和场景推演要求。
- `prompts/skills/*.md`：按关键词动态挂载的协议经验。
- `schemas.py`：输出 JSON 结构要求。

### 3.5 Critic

`critic.py` 是可选审计器。开启 `--audit` 后，它会检查 Maker 是否漏掉了原文中的硬件行为。

正式评审前建议开启。快速试跑可以关闭。

### 3.6 Cluster

`cluster.py` 负责把测试点的原始标签归类成树状目录，例如：

- 接口类
- 功能类
- 场景类
- 异常类
- 上报类
- corner类

## 4. 安装和配置

安装依赖：

```powershell
pip install -r requirements.txt
```

复制配置：

```powershell
copy .env.example .env
```

### 4.1 默认 API 模式

默认模式保持原版行为，使用用户提供的 OpenAI-compatible API Key。

`.env` 示例：

```env
DV_LLM_API_KEY="your_api_key_here"
DV_LLM_BASE_URL="https://api.deepseek.com"
DV_LLM_MODEL_NAME="deepseek-chat"
```

### 4.2 可选 Codex CLI 模式

Codex CLI 模式用于不外接 API、改用本机 Codex/ChatGPT 会员额度的场景。

一次性运行时直接加参数：

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

Codex CLI 不是默认模式，避免影响已有 API 用户，也避免无意消耗用户自己的 Codex 额度。

## 5. 怎么运行

交互式运行：

```powershell
python planner.py
```

命令行运行：

```powershell
python planner.py --input example_spec.md --output out.csv --audit
```

检查输入适配结果：

```powershell
python planner.py --input spec.docx --dump-normalized-spec normalized.md --normalize-only
```

`normalized.md` 是工具真正送入后续切块和提取流程的标准 Markdown。对于 Word、PDF、非标准文本，建议先检查这个文件，确认章节识别是否合理。

如果输入来自网页，请先把网页正文保存成 Markdown 或文本文件。当前命令行参数只接受本地文件路径，不接受 `https://...` 这类 URL。

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--input` / `-i` | 输入 Spec 路径，支持 md/txt/docx/pdf |
| `--output` / `-o` | 输出 CSV 路径 |
| `--backend openai` | 使用默认 API 后端 |
| `--backend codex` | 使用本机 Codex CLI 后端 |
| `--dump-normalized-spec` | 导出输入适配后的标准 Markdown |
| `--normalize-only` | 只执行输入适配并退出，不调用大模型 |
| `--audit` | 开启 Critic 漏测审计 |
| `--no-audit` | 关闭 Critic，加快运行 |

建议：

- 快速验证链路：`--no-audit`
- 正式生成：`--audit`
- 大文档或多人协作：显式指定 `--output`

## 6. 输出 CSV 怎么看

输出文件使用 UTF-8 with BOM，通常可以直接用 Excel 打开。

| 列名 | 说明 |
| --- | --- |
| `测试点编号` | 自动生成的树状编号 |
| `一级分类` | 接口类、功能类、场景类、异常类、上报类、corner类等 |
| `二级分类` | 测试点子类 |
| `优先级` | `P0`、`P1`、`P2` |
| `特征标签` | Maker 提取的原始标签 |
| `测试点摘要` | 一句话测试目的 |
| `详细描述` | 测试行为、观察点或期望结果 |
| `原文溯源` | 对应 Spec 原文，便于反查 |
| `存疑` | Spec 可能存在二义性时标记 |
| `缺陷/二义性说明` | 需要设计或架构澄清的问题 |

人工 review 时不要只看行数。更重要的是：

- 测试点是否有明确验证意图。
- 是否能反查到原文或明确的隐式规则。
- 是否覆盖核心路径、异常路径、边界条件和真实使用场景。
- “存疑”是否真的指向需要澄清的问题。

## 7. Skills 在哪里，怎么维护

Skills 是用户最应该维护的部分。

目录：

```text
prompts/skills/
```

当前已有：

```text
prompts/skills/axi.md
prompts/skills/sram.md
prompts/skills/backpressure.md
```

每个 skill 文件分三段：

```markdown
# keywords
触发这个 skill 的关键词

# explicit_rules
原文明确写到时必须提取的规则

# implicit_rules
即使原文没有直接写明，也应基于验证经验补充的测试点
```

### 7.1 keywords 怎么写

`keywords` 用来决定当前文档块是否挂载这个 skill。

示例：

```markdown
# keywords
axi, awvalid, arvalid, wvalid, rvalid, bvalid, awready, wready
```

建议：

- 写协议名、接口名、关键信号名。
- 中英文都可以写。
- 不要写过泛的词，例如 `data`、`valid`、`enable` 单独使用容易误触发。

### 7.2 explicit_rules 怎么写

`explicit_rules` 表示：如果 Spec 原文明确出现相关行为，必须提取测试点。

适合写：

- 协议限制。
- 明确边界。
- 明确错误响应。
- 明确时序要求。

示例：

```markdown
# explicit_rules
1. 4KB 边界：如果原文描述 AXI burst 不允许跨越 4KB 边界，必须提取合法边界、跨界非法和错误响应测试点。
2. 非对齐访问：如果原文描述地址必须 word 对齐，必须提取对齐访问和非对齐访问测试点。
```

不要写：

- “需要充分测试 AXI”这类空话。
- 没有触发条件、没有期望行为的泛泛建议。

### 7.3 implicit_rules 怎么写

`implicit_rules` 表示：只要文档块命中关键词，就允许模型根据验证经验补充测试点。

适合写：

- 反压。
- 背靠背。
- ID 覆盖。
- 读写冲突。
- 前门/后门一致性。
- 长时间 stall 后恢复。

示例：

```markdown
# implicit_rules
1. 背靠背传输：当模块支持 AXI burst 或连续访问时，补充连续背靠背读写测试点。
2. 通道反压：覆盖 AW/W/B/AR/R 各通道 ready 拉低和恢复后的数据不丢不重。
3. AXI ID 覆盖：如果接口包含 ID，覆盖所有支持 ID 的读写事务。
```

注意：

- `implicit_rules` 权力很大，会让模型“脑补”测试点。
- 只写团队确实认可的验证经验。
- 不要把不确定的设计假设写成隐式规则。

### 7.4 新增一个 skill 的步骤

假设要新增 FIFO 相关经验：

1. 新建文件：

```text
prompts/skills/fifo.md
```

2. 写入结构：

```markdown
# keywords
fifo, full, empty, almost_full, almost_empty

# explicit_rules
1. 如果原文定义 FIFO full 行为，必须提取写 full 边界和 full 后继续写的异常测试点。
2. 如果原文定义 FIFO empty 行为，必须提取读 empty 边界和 empty 后继续读的异常测试点。

# implicit_rules
1. 指针回卷：覆盖读写指针接近最大值并回卷后的 full/empty 判断。
2. 同拍读写：覆盖同一周期读写同时发生时的计数和数据顺序。
```

3. 用包含 FIFO 章节的 Spec 试跑：

```powershell
python planner.py --input your_fifo_spec.md --output fifo_testplan.csv --no-audit
```

4. 检查 CSV：

- 是否出现 FIFO 相关测试点。
- 是否有无意义脑补。
- 原文反标是否能支撑测试点。

5. 正式生成时再开启审计：

```powershell
python planner.py --input your_fifo_spec.md --output fifo_testplan_audit.csv --audit
```

### 7.5 修改 skill 后怎么判断有没有改好

看三件事：

- 命中是否正确：该触发时触发，不该触发时不触发。
- 输出是否具体：测试点能看出测什么、为什么测。
- 反标是否可信：显式规则来自原文，隐式规则至少能从当前上下文找到触发依据。

不要用“输出越多越好”判断。skills 的目标是增加有效覆盖，不是制造行数。

## 8. 哪些文件不建议普通用户改

普通用户通常不要改：

- `schemas.py`
- `extractor.py`
- `critic.py`
- `cluster.py`
- `chunker.py`
- `codex_client.py`

这些文件是程序逻辑。改动它们可能导致 JSON 解析失败、分类异常或输出质量下降。

如果只是想让工具更懂某类协议，优先改 `prompts/skills/*.md`。

如果只是想调整测试点提取风格，优先讨论 `prompts/layer1_meta.md` 和 `prompts/layer2_base.md`，不要直接改 Python 逻辑。

## 9. 常见问题

### 未检测到 `DV_LLM_API_KEY`

默认后端是 API 模式。请检查 `.env` 是否存在，并填写：

```env
DV_LLM_API_KEY="your_api_key_here"
```

或者显式使用 Codex CLI：

```powershell
python planner.py --backend codex --input example_spec.md --output out.csv --no-audit
```

### Codex CLI 提示模型不支持

确认 `.env` 中的 `DV_CODEX_MODEL` 是当前账号可用模型。当前验证过的配置是：

```env
DV_CODEX_MODEL="gpt-5.5"
```

### 找不到 Codex CLI

确认 Codex 已安装并登录。必要时指定路径：

```env
DV_CODEX_EXE="C:\\Users\\yyou\\AppData\\Local\\OpenAI\\Codex\\bin\\codex.exe"
```

### CSV 被 Excel 占用

关闭正在打开的 CSV 后重试。程序遇到权限问题时会尝试生成备用文件名。

### 控制台中文乱码

通常是 Windows 控制台编码问题，不代表 CSV 文件损坏。CSV 使用 `utf-8-sig` 写入，Excel 通常可以正常识别。

## 10. 推荐工作流

维护一个协议 skill 时，建议按这个顺序：

1. 先用当前 skill 跑示例 Spec，保存 CSV。
2. 修改 `prompts/skills/*.md`。
3. 用同一个 Spec 再跑一次。
4. 对比新增、减少和变化的测试点。
5. 只保留能提升有效覆盖的规则。
6. 正式输出前开启 `--audit`。

这套工具的质量主要来自两点：

- Spec 原文是否写清楚。
- skills 是否沉淀了真实验证经验。

维护 skills 时要克制。具体、可验证、能指导测试的规则才应该进入知识库。

## 11. 输入适配测试集

项目内的自动化测试位于 `tests/test_spec_loader.py`。它不调用大模型，不消耗 API 或 Codex 额度，只验证输入适配层。

当前测试集覆盖 14 个文档样本：

- 标准 Markdown。
- `1.` / `1.1` 编号标题文本。
- 中文 `第一章` 标题。
- 中文 `一、` 标题。
- Setext 标题。
- 全大写英文标题。
- 带列表项的文本，验证不会把普通 bullet 误判成标题。
- 带 Markdown 表格的文本。
- 无标题纯文本兜底。
- Word 标题样式文档。
- Word 纯段落编号文档。
- Word 表格。
- PDF 编号标题文本。
- PDF 无标题兜底。

本地验证命令：

```powershell
python -m unittest discover -s tests
python -m compileall -q planner.py spec_loader.py codex_client.py extractor.py cluster.py critic.py schemas.py chunker.py
```

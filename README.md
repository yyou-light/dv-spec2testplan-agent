# DV Spec2Testplan Agent

> 从硬件 Spec 生成、分解并审计 DV 测试点

验证工程师直接使用 AI 的收益经常受限，因为很多验证任务同时具备 AI 不擅长的特征：高上下文、高耦合、高风险、需求模糊、缺少现成测试、强业务隐含知识，以及分布式系统排障、性能、安全、并发、一致性等复杂问题。硬件验证几乎完整落在这些困难区域里。相比之下，把 Spec 转成可 review 的测试点，输入集中、目标明确、结果容易人工校准，可能是当前 AI 对 DV 工作流最有价值、最容易落地的增益点。

DV Spec2Testplan Agent 是一个面向数字 IC 验证工作的命令行工具。它读取硬件 Spec，调用大模型生成 DV 测试点，并导出结构化 CSV，方便验证工程师继续评审、补充和落地到 testplan。

**支持自己接 API，也支持直接使用 Codex。** 两种方式共用同一套测试点生成流程，用户任选其一：

| 使用方式 | 需要准备 | 额度来源 |
| --- | --- | --- |
| 自己接 API | OpenAI-compatible API 的地址、Key 和模型名 | 用户自己的 API 额度 |
| 直接使用 Codex | 本机已安装并登录 Codex | 当前 Codex/ChatGPT 账号的会员额度，不需要配置模型 API |

Codex 模式调用的是本机 Codex CLI 和用户已有登录态，不是 Codex API。为了不影响原有用户，项目默认仍使用 API 模式；运行时加 `--backend codex` 即可切换到 Codex。

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

然后选择下面任意一种模型接入方式。

### 方式一：使用自己的 API

复制配置文件：

```powershell
copy .env.example .env
```

编辑 `.env`，填写自己的 OpenAI-compatible API：

```env
DV_LLM_API_KEY="your_api_key_here"
DV_LLM_BASE_URL="https://api.deepseek.com"
DV_LLM_MODEL_NAME="deepseek-chat"
```

运行：

```powershell
python planner.py --backend openai --input example_spec.md --output out.csv --audit
```

`--backend openai` 可以省略，因为 API 是默认后端。

### 方式二：直接使用 Codex

确认本机 Codex 已安装并登录。该模式不需要填写 `DV_LLM_API_KEY`，直接运行：

```powershell
python planner.py --backend codex --input example_spec.md --output out.csv --audit
```

这会使用当前 Codex/ChatGPT 账号的会员额度，不会调用或消耗外部模型 API。需要长期默认使用 Codex 时，可在 `.env` 中设置：

```env
DV_LLM_BACKEND="codex"
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

每次完整运行除 CSV 外，还会在同目录生成可复跑、可审计的 JSON 中间产物。它们用于定位问题，不需要人工编辑。

## 全局上下文与 Skill 路由

工具会在切块前阅读完整 Spec，建立带章节和原文证据的全局事实表。每个 Chunk 都会共享时钟复位、接口、位宽、地址、时序、限制和错误响应等事实，避免把其他章节已经定义的内容误报为 Spec 缺陷。

默认 `DV_SKILL_ROUTER="semantic"`。程序先用安全词边界识别文档中的协议和接口，再由大模型把每条 Skill 规则全局分配给最合适的 Chunk。只要 Spec 确认存在 AXI、SRAM 等接口，对应的常规 DV 经验仍会保留；全局分配用于减少同一规则在多个 Chunk 中被重复展开。

需要兼容逐 Chunk 路由时，可以在 `.env` 中设置：

```env
DV_SKILL_ROUTER="keyword"
```

`keyword` 模式不会使用简单子串匹配，例如 `program` 不会误触发 `ram`，`already` 不会误触发 `ready`。

## 六类分类语义

一级目录固定为六类，不会因为当前 Spec 没有对应测试点而改变业务含义：

| 一级目录 | 判定重点 |
| --- | --- |
| `1.接口类` | 信号、位宽、通道、握手和协议规定的正常接口行为 |
| `2.功能类` | Spec 支持范围内的正常功能，包括合法最小值、最大值和支持组合 |
| `3.场景类` | 多步骤、多接口或软硬件协作的完整使用流程 |
| `4.异常类` | 非法输入、不支持操作、越界、协议违规和错误响应 |
| `5.上报类` | 中断、状态、告警、错误码等以可观察上报为主要目的的行为 |
| `6.corner类` | 资源饱和、长时间停顿后的恢复、资源冲突、关键状态转换、多个合法极限条件叠加或多个独立错误机制的优先级交互 |

`corner类` 是保留的核心 DV 目录，但“边界、最大、交叉”这些字样本身不构成 corner。合法最高地址、合法最大 Burst 长度、所有支持 ID 和合法 size/length 遍历仍是正常接口或功能；合法起点的 Burst 后续 beat 越界仍是单一地址错误，应归异常。只有真实的极限状态、资源/状态交互，或多个独立错误机制同时命中的优先级问题才进入 corner。

分类前，系统会对每个内部测试点 ID 建立原子性台账。同一条如果同时包含正常完成和错误响应，且能按支持/不支持、范围内/范围外等客观刺激域切分，就会拆成独立测试点；具体支持边界或错误码待澄清不能作为漏拆理由。单一信号不变量、完整场景和同一刺激下的未决设计选择不会机械拆分。分类时还会记录合法性、主验证意图、结果关注域、错误机制、corner 触发条件和二级目录匹配依据。现有二级目录不合适时，系统会扩展目录并只重分受影响测试点，不会硬塞到语义无关的目录。

## 模型后端

本项目不是只能接 API，也不是只能在 Codex 中运行。API 与 Codex 共用同一套 Spec 解析、Skills、Maker、Critic 和分类流程，仅模型调用方式不同。

默认后端保持原版行为：使用用户提供的 OpenAI-compatible API Key。

```powershell
python planner.py --backend openai --input example_spec.md --output out.csv --audit
```

也可以显式使用本机 Codex CLI 后端。这会消耗当前 Codex/ChatGPT 账号自己的会员额度，不需要 API Key，也不会外接模型 API。

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
| `依据反标` | 优先对应 Spec 原文；如果测试点来自 skill 经验且没有合适 Spec 原文，则反标到 skill 编号规则 |
| `存疑` / `缺陷/二义性说明` | 需要设计或架构澄清的问题 |
| `内部测试点ID` | 分类前后保持稳定的审计 ID；拆分项使用 `-S1`、`-S2` 等后缀 |
| `分类置信度` / `分类依据` | 模型的逐点分类结论和理由 |
| `合法性判定` / `主验证意图` | 分类决策使用的结构化语义轴 |
| `结果关注域` / `错误机制` | 区分正常行为、单一错误、完整场景、资源/状态交互和多错误优先级 |
| `Corner触发条件` / `Corner判定依据` | 只有真实 corner 才填写的触发类型和证据 |
| `二级目录匹配依据` | 该测试点为何适合当前二级目录 |

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

规则建议使用稳定编号，方便 CSV 反标和 review：

```markdown
- AXI-IMP-004: 通道反压：确保各通道在正常工作情况下，都触发过反压(ready拉低)。
```

当 Spec 没有合适原文支撑某条经验测试点时，CSV 会使用类似下面的依据反标：

```text
[SKILL: axi.md#AXI-IMP-004] 通道反压：确保各通道在正常工作情况下，都触发过反压(ready拉低)。
```

新增或修改 skill 后，建议用同一份 Spec 前后对比 CSV，确认新增内容是有效覆盖，不是无意义扩写。

完整写法见 [用户手册：Skills 在哪里，怎么维护](docs/USER_MANUAL.md#7-skills-在哪里怎么维护)。

## 项目结构

| 路径 | 作用 |
| --- | --- |
| `planner.py` | 主入口，负责整体流程和 CSV 导出 |
| `spec_loader.py` | 输入适配层，将 md/txt/docx/pdf 转成标准 Markdown |
| `extractor.py` | Maker，负责从文档块提取测试点 |
| `skill_router.py` | 根据完整 Spec 和全部 Chunk 分配 Skill 规则 |
| `critic.py` | Critic，负责可选漏测审计 |
| `cluster.py` | 负责原子性台账、六类语义分类、二级目录修复和树状编号 |
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

只重新执行原子性审查、分类和 CSV 导出，不重复运行 Maker/Critic：

```powershell
python planner.py --backend codex --classify-only --input out.raw.json --output out_reclassified.csv
```

假设输出名为 `out.csv`，同目录会生成：

| 文件 | 作用 |
| --- | --- |
| `out.raw.json` | Maker/Critic 完成后、分类前的稳定输入，可配合 `--classify-only` 复跑 |
| `out.atomicity.json` | 每个原始测试点的拆分或保留台账 |
| `out.atomic.raw.json` | 完成必要拆分后的测试点集合 |
| `out.classification.json` | 最终 taxonomy、逐点分类和分类审计信息 |
| `out.csv` | 用户评审和后续维护的测试点列表 |

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

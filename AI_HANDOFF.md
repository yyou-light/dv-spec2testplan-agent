# AI 交接说明

## 当前状态

项目当前是“原版测试点写作逻辑 + 完整 Spec 全局事实表 + 全局 Skill 路由 + 六类语义分类闭环 + 可选 Codex CLI 后端”。

必须注意：默认后端是 OpenAI-compatible API，保持老用户行为不变。Codex CLI 只能通过 `--backend codex` 或 `.env` 中显式设置 `DV_LLM_BACKEND="codex"` 启用。

用户向文档入口是 `README.md` 和 `docs/USER_MANUAL.md`。后续如果运行方式、配置项或输出列发生变化，需要同步更新这两处。

当前输入适配层是 `spec_loader.py`。它支持 `.md/.markdown/.txt/.text/.docx/.pdf`，并通过 `--dump-normalized-spec` 和 `--normalize-only` 让用户检查标准化后的 Markdown 且不调用大模型。后续优化输入格式时应优先扩展 `spec_loader.py`，不要改 Maker/Critic/Schema。

当前还不直接支持 URL/HTML 输入。处理网页 Spec 时，需要先把网页正文保存为 Markdown 或文本文件，再交给 `planner.py`。如果后续要支持网页，应优先在 `spec_loader.py` 增加 URL/HTML 适配，并补对应单元测试。

当前 Maker 的依据反标规则是：Spec 直接支撑优先；如果测试点来自 skill 经验且当前 Chunk 没有合适 Spec 原文，则使用 `[SKILL: file.md#RULE-ID] 规则内容` 作为反标。Critic 仍只做漏测审计，不做额外质量评分。

切块规划不再只读取前言和目录。`planner.py` 会把完整标准化 Spec 交给模型，并通过 `GlobalSpecContext` 提取带章节和原文证据的全局事实。每个 Chunk 都接收同一份事实表，判断二义性时不得把其他章节已定义内容误报为缺失。

默认 `DV_SKILL_ROUTER="semantic"`。`skill_router.py` 先使用安全词边界从完整 Spec 识别候选 Skills，再要求模型把每条候选规则分配给至少一个真实 Chunk；Python 会检查规则漏分配、重复和未知 Chunk。`keyword` 是兼容模式，也已移除简单子串误命中。

`cluster.py` 已从“自由 raw_tag 映射目录”改为完整测试点语义分类。固定一级目录是接口、功能、场景、异常、上报、corner 六类。分类会读取 summary、details、反标、来源 Chunk 和全局事实，并输出四态合法性、主验证意图、结果关注域、错误机制、corner 触发条件、分类依据和二级目录匹配依据。

分类前必须执行全量原子性台账：每个原始内部 ID 必须且只能进入 `splits` 或 `kept_testpoints`。同时包含正常完成与错误响应、不是单一信号不变量或完整场景，并且可按支持/不支持、范围内/范围外等客观刺激域切分时必须拆分。`unresolved_design_alternatives` 不再是漏拆豁免；支持边界或错误码待澄清时，拆分后的测试点继续保留二义性。Python 会拒绝漏审、重复、过拆和满足资格却漏拆。二级目录不匹配时，分类器必须提出新目录，系统扩展 taxonomy 后只重分受影响测试点。

每次完整运行会生成同名的 `.raw.json`、`.atomicity.json`、`.atomic.raw.json` 和 `.classification.json`。其中 `.raw.json` 是 `--classify-only` 的稳定复跑输入；不要只保留 CSV 而丢失这些审计产物。

## 已验证结果

已使用 Codex CLI 后端跑通过示例：

```powershell
python planner.py --backend codex --input example_spec.md --output DV_Testplan_example_spec_codex_cli.csv --no-audit
```

结果生成 119 条测试点。这是恢复原版生成逻辑后的历史质量基线；后续全局上下文和 Skill 路由改造继续保留该版的测试点写作风格，不引入自动语义改写或自动删除。

输入适配层补充后，已完成以下验证：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q planner.py spec_loader.py codex_client.py extractor.py skill_router.py cluster.py critic.py schemas.py chunker.py
python planner.py --input example_spec.md --dump-normalized-spec _normalized_example.md --normalize-only
python planner.py --backend codex --input example_spec.md --output DV_Testplan_input_adapter_smoke.csv --no-audit
```

其中 `tests/test_spec_loader.py` 覆盖 14 类输入样本，不调用大模型，不消耗 API 或 Codex 额度。

也用 OpenTitan DMA 官方页面做过一次人工网页转 Markdown 后的端到端测试：

```powershell
python planner.py --backend codex --input _opentitan_dma_source.md --output DV_Testplan_opentitan_dma.csv --no-audit
```

结果生成 65 条测试点。`_opentitan_dma_source.md`、`_opentitan_dma_normalized.md` 和生成的 CSV 是本地测试产物，默认不要提交。

### 全局上下文与 Skill 路由实跑

P0 改造后已使用 Codex CLI 对 `example_spec.md` 完成两轮端到端回归：

```powershell
python planner.py --backend codex --input example_spec.md --output DV_Testplan_example_spec_codex_global_context_noaudit.csv --no-audit
python planner.py --backend codex --input example_spec.md --output DV_Testplan_example_spec_codex_global_context_audit.csv --audit
```

无审计版本生成 91 条测试点，用时约 14 分 25 秒。正式审计版本生成 97 条测试点，用时约 27 分 41 秒；6 个 Chunk 的 Critic 均实际运行并首轮通过，没有 Critic 解析失败。

正式审计结果结构检查：空摘要 0、空描述 0、空反标 0、未分类 0、精确重复摘要 0。完整 Spec 命中 AXI、SRAM、Backpressure 三个 Skills，14 条候选规则全部完成全局分配，并在最终 CSV 中得到实际覆盖。

与旧的 `DV_Testplan_example_spec_codex_cli_audit_skill_ref.csv` 比较：总行数从 136 降到 97，Skill 反标行从 61 降到 23，`SRAM-IMP-001` 从 6 条收敛为前门/后门两个不同方向，`AXI-IMP-004` 从 8 条收敛为写响应与读通道两个不同对象；跨章节已经定义的复位名称、有效电平等不再被误报为缺失。

当前仍可能存在同一 Spec 行为被分别写成通用、读、写测试点的语义相近项，以及同一真实 Spec 缺口在多个相关测试点中重复标记。这些属于后续语义重复 review 范围，不应通过本轮路由逻辑自动删除。

### 带 Critic 的最终闭环回归

先对 `example_spec.md` 执行完整 Maker、Critic、原子性和分类流程，再以该次 Critic 审过的 raw testpoint 复跑修正后的分类契约：

```powershell
python planner.py --backend codex --input example_spec.md --output DV_Testplan_example_spec_codex_semantic_classification_audit_final.csv --audit
python planner.py --backend codex --classify-only --input DV_Testplan_example_spec_codex_semantic_classification_audit_final.raw.json --output DV_Testplan_example_spec_codex_semantic_classification_audit_final_v2.csv
```

完整审计运行共 7 个 Chunk，Critic 7/7 实际调用且均首轮通过，没有解析失败，形成 103 条分类前测试点。最终分类复跑对 103/103 个原始 ID 建立唯一台账，拆分 `RTP_0101` 为 3 个单一结果域，形成 105 条最终测试点。接受结果是 `audit_final_v2.csv`；前一个 CSV 仅是本次修复使用的中间回归结果。

最终 CSV 为 105 行、21 列，一级分类分布为：接口 29、功能 36、场景 9、异常 20、上报 0、corner 11。上报类为空是因为当前 Spec 和 Skills 没有独立中断、状态或告警上报机制，不应为凑目录制造测试点。taxonomy 共 27 个实际主题。

结构门禁全部通过：必填字段缺失 0、内部 ID 重复 0、精确重复摘要 0、混合意图残留 0、低置信度 0、二级目录匹配失败 0、分类后待拆分 0、非 corner 错填 corner 证据 0，所有一级/二级编号连续，105 个分类 ID 与原子化输入完全一致。

关键业务断言已实跑通过：

- `RTP_0017`、`RTP_0018` 全部支持 AXI ID 覆盖属于接口类。
- `RTP_0032`、`RTP_0033`、`RTP_0092`、`RTP_0093` 合法最低/最高地址属于功能类。
- `RTP_0101-S1` 合法 AxSIZE/AxLEN 组合属于功能类；`-S2/-S3` 长度越界和不支持 Size 属于异常类。
- `RTP_0085` 随机反压、`RTP_0069` 普通 non-blocking 属于正常接口行为；`RTP_0071`、`RTP_0080` 长反压恢复保留为 corner。
- `RTP_0095` 合法起点后续 beat 越界、`RTP_0100` 跨 4KB 处理属于异常类，不再误入 corner。
- `RTP_0099` 同时命中非对齐和越界的错误优先级使用 `multiple_error_interaction`，保留为真实 corner。
- `RTP_0072` 最大 outstanding、`RTP_0007` 单端口并发仲裁、`RTP_0043` 至 `RTP_0045` 同址冲突和 `RTP_0026` 在途事务复位均保留为真实 corner。
- `RTP_0102` 连续最大合法 Burst 是完整业务流，属于场景类，不因“最大”二字误入 corner。
- `RTP_0075` 是多笔写事务交叠下的 AW/W 长间隔配对冲突；普通单笔 AW/W 先后到达仍在接口/功能类。

当前本地单元测试共 31 项，覆盖输入适配、全局上下文、Skill 路由、合法边界/异常/corner 判定、单一跨界错误拒绝伪装 corner、多错误优先级保留 corner、需求未决但刺激域可分时仍纠正漏拆、原子性过拆纠正、Schema/业务规则重试、二级目录扩展和编号连续性。

## 关键设计约束

1. 默认模式必须继续使用用户提供的 API Key。
2. 不要默认消耗用户 Codex 会员额度。
3. 不要引入硬编码语义改写、评分门禁或自动去重来改写测试点内容。
4. 不要为了 Codex CLI 修改测试点内容 Schema；全局事实和路由计划可以使用独立结构化 Schema。
5. Codex CLI 后端只负责把原来的 `client.chat.completions.create(...)` 调用转接到本机 Codex。
6. 输入格式适配只能改善文档结构，不应改写测试点语义。
7. Skills 规则应保留稳定编号，便于 CSV 反标 review。不要把 skill 经验覆盖能力收窄成“Spec 没写就不测”。
8. Skill 全局路由必须覆盖全部候选规则。语义分配可以改变规则落在哪个 Chunk，但不能静默删掉协议经验。
9. 六个一级目录的业务含义固定。合法端点不是 corner；单一非法越界是异常；合法起点的 Burst 后续 beat 越界仍是单一地址错误。corner 必须有资源饱和、长停顿恢复、并发冲突、关键状态转换、多合法极限叠加，或至少两个独立错误机制的优先级交互证据。
10. 不得退回只看 `raw_tag` 的分类方式，也不得用关键词硬编码代替完整测试点语义判断。
11. 原子性台账必须完整覆盖所有输入 ID；只输出拆分项会重新引入静默漏拆。
12. 二级目录语义不匹配时必须扩展 taxonomy 或明确失败，不能为了“都有分类”把测试点塞进无关目录。

## 常用命令

默认 API 模式：

```powershell
python planner.py --input example_spec.md --output out.csv --audit
```

Codex CLI 模式：

```powershell
python planner.py --backend codex --input example_spec.md --output out.csv --no-audit
```

只重跑分类：

```powershell
python planner.py --backend codex --classify-only --input out.raw.json --output out_reclassified.csv
```

语法检查：

```powershell
python -m unittest discover -s tests
python -m compileall -q planner.py spec_loader.py codex_client.py extractor.py skill_router.py cluster.py critic.py schemas.py chunker.py
```

## 后续优化建议

- 建立用户认可的多项目 golden testplan 集，持续做分类和内容 A/B 回归，不能只依赖当前 AXI-SRAM 示例。
- 发布前可在用户明确授权额度时，对默认 OpenAI-compatible API 后端做一次真实冒烟；当前 31 项单测已覆盖相同的 `chat.completions.create(...)` 结构化调用契约，默认后端配置未改变。
- 可以增加输出文件命名、运行参数、错误提示等外围体验。
- 若要优化质量，必须基于用户认可的 golden CSV 做 A/B 对比，不能用自定义关键词评分替代人工质量判断。

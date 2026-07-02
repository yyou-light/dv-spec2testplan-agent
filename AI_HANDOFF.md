# AI 交接说明

## 当前状态

项目已固化为“原版生成逻辑 + 可选 Codex CLI 后端”。

必须注意：默认后端是 OpenAI-compatible API，保持老用户行为不变。Codex CLI 只能通过 `--backend codex` 或 `.env` 中显式设置 `DV_LLM_BACKEND="codex"` 启用。

用户向文档入口是 `README.md` 和 `docs/USER_MANUAL.md`。后续如果运行方式、配置项或输出列发生变化，需要同步更新这两处。

当前输入适配层是 `spec_loader.py`。它支持 `.md/.markdown/.txt/.text/.docx/.pdf`，并通过 `--dump-normalized-spec` 和 `--normalize-only` 让用户检查标准化后的 Markdown 且不调用大模型。后续优化输入格式时应优先扩展 `spec_loader.py`，不要改 Maker/Critic/Schema。

当前还不直接支持 URL/HTML 输入。处理网页 Spec 时，需要先把网页正文保存为 Markdown 或文本文件，再交给 `planner.py`。如果后续要支持网页，应优先在 `spec_loader.py` 增加 URL/HTML 适配，并补对应单元测试。

## 已验证结果

已使用 Codex CLI 后端跑通过示例：

```powershell
python planner.py --backend codex --input example_spec.md --output DV_Testplan_example_spec_codex_cli.csv --no-audit
```

结果生成 119 条测试点。质量明显优于此前过度改造版本，因为当前版本没有改动原版 Prompt、Schema、Extractor、Critic、Cluster 和 Skills 的核心生成逻辑。

输入适配层补充后，已完成以下验证：

```powershell
python -m unittest discover -s tests -v
python -m compileall -q planner.py spec_loader.py codex_client.py extractor.py cluster.py critic.py schemas.py chunker.py
python planner.py --input example_spec.md --dump-normalized-spec _normalized_example.md --normalize-only
python planner.py --backend codex --input example_spec.md --output DV_Testplan_input_adapter_smoke.csv --no-audit
```

其中 `tests/test_spec_loader.py` 覆盖 14 类输入样本，不调用大模型，不消耗 API 或 Codex 额度。

也用 OpenTitan DMA 官方页面做过一次人工网页转 Markdown 后的端到端测试：

```powershell
python planner.py --backend codex --input _opentitan_dma_source.md --output DV_Testplan_opentitan_dma.csv --no-audit
```

结果生成 65 条测试点。`_opentitan_dma_source.md`、`_opentitan_dma_normalized.md` 和生成的 CSV 是本地测试产物，默认不要提交。

## 关键设计约束

1. 默认模式必须继续使用用户提供的 API Key。
2. 不要默认消耗用户 Codex 会员额度。
3. 不要引入硬编码语义改写、评分门禁或自动去重来改写测试点内容。
4. 不要为了 Codex CLI 修改原版 Schema。
5. Codex CLI 后端只负责把原来的 `client.chat.completions.create(...)` 调用转接到本机 Codex。
6. 输入格式适配只能改善文档结构，不应改写测试点语义。

## 常用命令

默认 API 模式：

```powershell
python planner.py --input example_spec.md --output out.csv --audit
```

Codex CLI 模式：

```powershell
python planner.py --backend codex --input example_spec.md --output out.csv --no-audit
```

语法检查：

```powershell
python -m unittest discover -s tests
python -m compileall -q planner.py spec_loader.py codex_client.py extractor.py cluster.py critic.py schemas.py chunker.py
```

## 后续优化建议

- 可以增加日志和失败重试，但不要改变测试点生成语义。
- 可以增加输出文件命名、运行参数、错误提示等外围体验。
- 若要优化质量，必须基于用户认可的 golden CSV 做 A/B 对比，不能用自定义关键词评分替代人工质量判断。

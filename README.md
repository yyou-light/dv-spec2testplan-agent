# 🚀 DV AI Agent: 智能数字 IC 验证计划提取引擎

基于大语言模型 (LLM) 和 Maker-Checker 多智能体架构的 Spec 解析工具。

## ✨ 核心特性
* **零漏测闭环 (Critic 机制)**：提取后自动进行逆向原文比对，确保没有任何一句硬件行为被遗漏。
* **外挂验证大脑**：纯 Markdown 管理 `skills`，可无限扩充 AXI/SRAM 等协议的隐式推导经验。
* **二义性雷达**：不仅提取功能，更能前置扫描 Spec 中的逻辑矛盾与时序模糊点。

## 🛠️ 快速上手
1. 克隆代码库：`git clone ...`
2. 安装依赖：`pip install -r requirements.txt`
3. 配置密钥：将 `.env.example` 重命名为 `.env`，填入你的大模型 API Key。
4. 一键运行：`python planner.py`，根据交互提示放入你的 Markdown 规范文档即可！

## 📂 目录结构
* `planner.py` - 主控中枢与交互入口
* `extractor.py` - 核心提取大模型 (Maker)
* `critic.py` - 防漏测审计大模型 (Checker)
* `prompts/skills/` - 💡 验证经验知识库，欢迎团队成员提交 PR 补充协议规范！
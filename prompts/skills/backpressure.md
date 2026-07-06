# keywords
ready, 反压, 握手, stall, wait state

# explicit_rules
（无）

# implicit_rules
- BP-IMP-001: 随机反压：下游随机拉低 ready 信号，验证数据不丢不重。
- BP-IMP-002: 极限反压：长达连续多拍的长反压后，立刻恢复传输的正确性。
- BP-IMP-003: 同拍握手：valid 和 ready 在同一时钟上升沿同时拉高时的零延迟握手行为。

# keywords
ready, 反压, 握手, stall, wait state

# explicit_rules
（这里留空，或者写一些必须在原文找到的具体反压时序要求）

# implicit_rules
1. 随机反压：下游随机拉低 ready 信号，验证数据不丢不重。
2. 极限反压：长达连续多拍的长反压后，立刻恢复传输的正确性。
3. 同拍握手：valid 和 ready 在同一时钟上升沿同时拉高时的零延迟握手行为。
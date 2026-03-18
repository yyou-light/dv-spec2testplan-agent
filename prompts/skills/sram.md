# keywords
sram, ram, 读写冲突, csn, wen

# explicit_rules
1. 读写冲突 (RAW/WAR/WAW)：提取对同一 SRAM 地址在同一周期或相邻周期同时发起读写的冲突测试点。
2. 背靠背传输：提取连续多拍全速写或全速读的流水线时序测试点。

# implicit_rules
1. 物理线测试：前门写后门读，后门写前门读
# keywords
axi, awvalid, arvalid, wvalid, rvalid, bvalid, awready, wready

# explicit_rules
1. 握手独立性：AXI读或写访问时使用了blocking和non-blocking访问。
2. 4KB 边界：提取 AXI Burst 传输跨越 4KB 地址边界时的报错或切分逻辑测试点。
3. 乱序传输：如果模块支持，提取 outstanding 和 out-of-order (乱序返回) 的测试点，要覆盖最大值。
4. 包类型：遍历所有size和length的cross情况

# implicit_rules
1. 背靠背传输：burst len=1时，测试连续背靠背传输能力。
2. 包间独立性：AXI读或写访问时使用了blocking和non-blocking访问
3. AXI ID全覆盖：确保读写通道的所有支持的AXI ID都得到覆盖
4. 通道反压：确保各通道在正常工作情况下，都触发过反压(ready拉低)
# AXI4 to SRAM Bridge Module Specification

## 1. 模块概述
AXI_SRAM_BRIDGE 是一个标准的 AXI4 Slave 设备，主要功能是将 AXI4 总线上的读写事务（Transactions）转换为标准的单端口同步 SRAM 读写时序。该模块主要用于挂载片上的 Scratchpad RAM。


## 2. 接口信号
### 2.1 全局信号
* `aclk`: AXI 全局时钟信号，上升沿有效。
* `aresetn`: AXI 全局复位信号，低电平异步复位，同步释放。

### 2.2 AXI4 Slave 接口
支持标准的 AXI4 AW, W, B, AR, R 五个通道，数据位宽为 32-bit，地址位宽为 32-bit。

### 2.3 SRAM Master 接口
* `sram_en`: SRAM 片选使能信号，高电平有效。
* `sram_we`: SRAM 写使能信号，高电平为写，低电平为读（前提是 sram_en 为高）。
* `sram_addr` [15:0]: SRAM 读写地址（Word 对齐）。
* `sram_wdata` [31:0]: SRAM 写数据。
* `sram_rdata` [31:0]: SRAM 读数据。

## 3. 功能描述与时序要求

### 3.1 复位行为
当 `aresetn` 拉低时，模块进入复位状态。所有的 AXI `VALID` 信号（如 `awready`, `wready`, `arready` 等）必须在复位期间强制拉低。SRAM 控制信号 `sram_en` 和 `sram_we` 必须保持为低电平。

### 3.2 模块使能控制
模块内部包含一个控制寄存器 `CTRL_REG`（地址偏移 0x0000_0000，默认值 32'h0）。
* Bit [0]: `bridge_enable`。当此位为 1 时，桥接器正常工作。当此位为 0 时，桥接器处于关闭状态。
* **异常处理**：如果在 `bridge_enable == 0` 时收到任何 AXI 读写请求（AWVALID 或 ARVALID 为高），模块必须立即在 B 通道或 R 通道返回 `SLVERR`（Slave Error），且不向 SRAM 发起任何操作。

### 3.3 写事务 (Write Transaction)
* **握手规则**：支持 AW 和 W 通道的乱序到达，但必须等待 `AWVALID` 和 `WVALID` 均有效后，才向 SRAM 发起写操作。
* **SRAM 时序**：写操作为零延迟。即 `sram_en` 和 `sram_we` 随 `sram_wdata` 同拍给出，下一拍即完成写入。
* **B 通道响应**：SRAM 写入完成后的下一拍，拉高 `BVALID`，并返回 `OKAY` 响应。

### 3.4 读事务 (Read Transaction)
* **SRAM 时序**：读操作有一拍延迟。拉高 `sram_en` 并拉低 `sram_we` 发送地址后，下一拍才能从 `sram_rdata` 采到有效数据。
* **R 通道响应**：采到有效数据当拍，将数据放到 AXI R 通道，拉高 `RVALID` 和 `RLAST`，返回 `OKAY` 响应。

## 4. 协议限制与边界条件 (Corner Cases)
受限于后端 SRAM 的简单结构，本桥接器对 AXI4 协议做了以下限制，这也是验证的重点关注区域：

1.  **Burst 类型限制**：仅支持 `INCR` (Incrementing) 类型的 Burst。如果收到 `FIXED` 或 `WRAP` 类型的请求，必须在传输结束时返回 `SLVERR`。
2.  **Burst 长度限制**：最大支持的 `AWLEN` 或 `ARLEN` 为 15（即最大 16 拍传输）。超过此长度的请求需返回 `SLVERR`。
3.  **地址越界保护**：SRAM 物理空间大小为 64KB（地址范围 0x0000 - 0xFFFF）。如果 AXI 请求的地址超过此范围，模块不执行 SRAM 操作，并直接返回 `DECERR`（Decode Error）。
4.  **非对齐传输**：不支持非对齐传输，要求所有请求的首地址必须是 4 字节对齐的（`awaddr[1:0] == 2'b00` 且 `araddr[1:0] == 2'b00`）。如果收到非对齐地址，返回 `SLVERR`。
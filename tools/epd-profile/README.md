# Ark 屏幕刷新诊断

目标为 HINK-T037A02-A1 / EPD037A02，JD7601，原生 720×480。仅使用现有刷新波形，不改变驱动时序或 SPI 频率。屏幕显示版本保持 3.2.5。

在 ESP-IDF menuconfig 的 **Ark EPD diagnostics** 打开 **Enable per-frame driver timing**（`CONFIG_ARK_EPD_PROFILE=y`），构建诊断固件。默认关闭，正常固件不记录逐帧数据。请将诊断构建及 sdkconfig 副本放在 D 盘，避免覆盖正常产物。

烧录后记录 115200 波特率串口日志。每次公开 MonoFast / ColorFast / ColorQual 调用产生一行 `EPD_PROFILE {...}`；同一调用内的准备清屏、波形切换与多阶段刷新合并在该条记录中。

```powershell
python tools/epd-profile/summarize.py capture.log
python tools/epd-profile/summarize.py capture.log --json > summary.json
python tools/epd-panel-lab/panel_lab.py --help
```

统计按刷新路径、是否准备会话、是否开启 mono 连续会话分组。首次从彩色进入黑白的调用不能与稳态帧混为一组。

- `total_us`：整个 driver 调用，截止日志输出前。
- `init_us/lut_us/ram_us/ref_us/pon_us/pof_us/other_us`：互不重叠的分段耗时。RAM 包含编码、等待写入及 SPI；REF/PON/POF 包含原有等待和固定延时，不等于纯粒子运动时间。
- `started_us`：设备启动后的单调时钟，用于对照，不是日历时间。
- `bytes/lut_bytes/ram_bytes`：成功发送字节；`stages` 为 REF 次数，准备清屏也计算。
- `timeouts/spi_errors/first_error/busy_ignored/ok`：失败与诊断状态。失败样本不纳入成功耗时均值。
- 连续 mono 会话停止后的 POF 不属于上一帧；完整动画节奏还包含文件读取、app 调度和帧间配置。诊断JSON的串口输出也可能拉长帧间隔；不把开启日志后的节奏直接当作关闭日志时的极限。

命令返回 0 表示日志有效且样本成功；1 表示有失败样本或损坏记录（仍输出可用统计）；2 表示无法读取或没有完整记录。未开启诊断、只有空日志、只有半条 JSON 都不会被报告为成功实测。

该工具不连接设备，不控制 RTS/DTR，也不写入屏幕。测量数据不能自动证明某个更高频率或未知波形适合该面板。生成的色卡/动画与测量流程见 [同屏测试工具](../epd-panel-lab/README.md)。


## RAM 批传输与图片首帧回归

本轮保持40MHz与原LUT，Mono差分数据按4行1440B批发送，整帧172800B不变，成功RAM事务从480降到120。profile增加 `ram_transactions`，旧日志缺少此字段时保持未知，不填0。静态DMA缓冲避免增加UI/film任务栈。

```powershell
python -m unittest discover -s tools/epd-profile -p test_mono_batch.py -v
python tools/epd-profile/check_atomic_image_open.py
node --test tools/ForFilm/tests/ark-open-image.test.cjs
```

编码测试冻结7737671的真实旧函数，编译当前真实新函数，比较完整SPI字节流和prev状态。原子打开host检查编译实际app/manager/文件解析函数，验证目标首帧、普通恢复、列表去重与失败状态。固件能力和客户端约定见 [0x4B](../../docs/blecmd/blecmd_protocol.md#471-app_switch-0x4b---切换-app)；网页提供 `ArkDevice.openImage(filename)`。成功回包仅表示已提交，不等于屏幕完成；已开始的波形仍正常完成。

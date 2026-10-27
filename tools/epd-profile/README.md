# Ark 屏幕刷新诊断

目标为 HINK-T037A02-A1 / EPD037A02，JD7601，原生 720×480。保留原刷新波形、SPI 频率和等待顺序；时序候选的失败及恢复见[同屏实测记录](../../docs/film/epd037a02.md)，不将驱动调用计数当成有效显示帧率。屏幕显示版本保持 3.2.5。

在 ESP-IDF menuconfig 的 **Ark EPD diagnostics** 打开 **Enable per-frame driver timing**（`CONFIG_ARK_EPD_PROFILE=y`），构建诊断固件。默认关闭，正常固件不记录逐帧数据。请将诊断构建及 sdkconfig 副本放在 D 盘，避免覆盖正常产物。

烧录后记录 115200 波特率串口日志。ColorFast / ColorQual 及 Mono 冷帧、含 INIT/PON 的调用产生 `EPD_PROFILE {...}`；同一调用内的准备清屏、波形切换与多阶段刷新合并在该条记录中。Mono 稳态在内存聚合，退出会话时仅输出一条 `EPD_PROFILE_SESSION {...}`，播放期间不逐帧打印。

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
- 连续 mono 会话停止后的 POF 不属于上一帧；完整动画节奏还包含文件读取、app 调度和帧间配置。旧诊断版本的逐帧串口输出会拉长帧间隔；现在的 Mono 会话汇总避开播放期间输出，但仍不能用驱动耗时倒数代替实际帧率。

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

## 低干扰 Mono 会话采样

`CONFIG_ARK_EPD_PROFILE` 开启时，begin 幂等，不因每帧重入清空；end/sleep/deinit 收尾并清空。仅保留前 192 个稳态样本和最多 191 个起点间隔，正常构建无新增存储。退出只输出一条聚合，不转储逐帧大日志，避免阻塞取消及页面交接。

- `sample_count/ok_samples` 是保留样本数及其中成功数；`dropped_samples` 是容量之外的调用数，不代表丢动画帧。
- `error_samples/timeouts/spi_errors` 覆盖全会话，包括超过采样容量后的失败；因此 error_samples 可能大于 sample_count。失败不会被采样上限隐藏。
- `total_sum_us`、`sum_us`、字节及事务 sum 只累计保留的成功样本；没有成功样本时不生成零耗时均值。
- 起点间隔包括保留样本之间的真实调用间隔；任何失败都会使该轮验收失败。`interval_sum_us/interval_count` 给出平均间隔，`interval_p50_us` 给出中位数。平均调用率为 interval_count × 1000000 / interval_sum_us；中位数倒数另行标记，二者不混用。
- CLI 同时兼容旧逐帧记录和新会话记录，JSON 的 groups 保留逐帧分组，sessions 单独列出会话结果。缺失或截断的会话记录不会被当作成功测量。

本轮实机对照需先使用聚合采样、原刷新顺序建立基线，再与同样聚合采样的优化版比较。固定同一文件和播放参数；旧的逐帧打印结果只能作为历史参考。

Windows + clang 的 `test_mono_profile.py` 检查真实 C 聚合器及会话生命周期，不连接设备。REF 尾部等待前移的候选已被实体显示测试否决，未保留在固件中。

## BUSY 与 REF 的本屏对应采样

PROFILE 构建对 GPIO11 的 BUSY 双边沿打时间戳，原命令、等待、尾延时与电源顺序不变。early 保留最初四个被采样的稳态调用及下一次 begin，最多80条；之后 IRQ 继续向固定 ring 采集最近四个完整调用，另留一个在途 slot，每 slot 最多20条。结束会话先 STOP 采集并移除本 pin handler，再执行原 POF，最后集中输出；不把关电边沿混入 REF。共享 GPIO ISR service 不卸载，正常固件无额外 IRQ 或 trace 存储。

```powershell
python tools/epd-profile/busy_trace.py capture.log --json
```

每次会话输出两条 EPD_BUSY_TRACE。window=early 保留 events 四元组 [相对微秒, call_id, marker, 原始电平]；window=tail 的 frames 按时间排列，每项为 {frame, initial_level, overflow, events}，events 是 [相对微秒, marker, 原始电平]。两者共用 registration_err、overflow、capture_complete 与 origin_us；tail 的 origin_us 是最老保留调用起点，end_us/end_level 是停止采集时刻和电平。partial_frame 为0表示无在途调用，否则是被排除的 call_id；该调用期间不属于完整 tail 覆盖。call_id 计数本会话的全部 Mono driver 调用（含 prepare），不是 film 帧下标；origin_us 是设备单调时钟。


| marker | 观测点 |
|---|---|
| 0 | GPIO 边沿 ISR |
| 1 | 帧 begin |
| 2 / 3 | DTM1 命令前 / 命令后 |
| 9 | DTM1 后 BUSY 等待返回 |
| 4 | RAM 写入结束 |
| 5 / 6 | REF 前 / REF 与 0x00 已发送 |
| 7 | REF BUSY 等待返回 |
| 8 | 原 10ms 尾延时返回（实际时长取决于 tick 相位） |

解析器保留等待返回后再次拉低的边沿，不会把一次 high 或没有超时直接当作完成。注册失败、溢出、缺失/乱序 marker、截断记录均不作为完整证据；只有空记录的短 UI 会话不会被当作有效测量。

这是 GPIO ISR 与软件 marker 的对应观测，带有中断延迟，不是逻辑分析仪的硬件捕获，也不测量光学稳定时间。接近同时发生的 marker/IRQ 时间不应按微秒级先后过度解释。需结合 REF、完整忙周期、恢复窗口、下一帧写入以及实体连续动画确认，不能据此猜测删等待。


### 最近调用与末段窗口

EPD_MONO_RECENT 保存最后8次调用：[call_id, started_us, total_us, ram_us, ref_us, stages, first_prepare, ok, timeouts, spi_errors]。steady 子对象提供整个会话的 count/ok_count/errors、首末起点、成功耗时之和与最小 REF 对应的 call_id；不受旧192样本上限影响。phase_sum_us 顺序为 [other, init, lut, ram, ref, pon, pof]。旧 EPD_PROFILE_SESSION 仍只统计前192个样本的耗时，不能用它代表后段。

CLI JSON 同时输出 early、tail 与 recent；没有最后一段采样时应明确缺失，不能把启动波形外推到长时间运行。软件调用率仍不等于光学帧率。

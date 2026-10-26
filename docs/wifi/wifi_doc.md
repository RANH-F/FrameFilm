# FrameFilm WiFi 功能说明

## 1. 概述

FrameFilm Pro 版本在基础版的 BLE 通信之外，新增了 WiFi 联网功能。通过 WiFi 连接，设备可以直接从网络下载 film 文件，实现**远程推送显示**和**WiFi 轮播模式**。

> 以下配网与轮播章节描述经典 Pro 固件；Ark App 的 WiFi Direct 直传见文末专节。

## 2. 功能架构

```
手机小程序 -- BLE --> 设备 -- WiFi STA --> HTTP API --> film 文件
                        │
                        └──> SD 卡存储 --> 电子纸显示
```

- **配网**：通过 BLE 命令设置 WiFi SSID/密码，设备以 STA 模式连接路由器
- **下载**：设备通过 HTTP GET 请求指定的 API URL，下载 film 文件到 SD 卡
- **轮播**：WiFi 轮播模式下，设备定时从 API 拉取最新内容并显示

## 3. 参数配置

设备通过 NVS 持久化存储以下网络参数：

| 参数 | 类型 | 长度 | 说明 |
|------|------|------|------|
| wifi_enable | uint8 | 1 | WiFi 开关（0: 关闭, 1: 开启），默认关闭 |
| wifi_ssid | string | 63 | WiFi SSID |
| wifi_password | string | 63 | WiFi 密码 |
| film_api_url | string | 127 | HTTP 下载 film 文件的 API 地址 |

## 4. BLE 命令协议

### 4.1 命令列表

| 通道 | 名称 | 方向 | 数据格式 | 说明 |
|------|------|------|----------|------|
| 0x30 | WIFI_ENABLE | 下行 | uint8 | WiFi 开关设置 (0: 关闭, 1: 开启) |
| 0x31 | WIFI_ENABLE_GET | 上行 | uint8 | 查询 WiFi 开关状态 |
| 0x32 | WIFI_SSID | 下行 | string | 设置 WiFi SSID |
| 0x33 | WIFI_SSID_GET | 上行 | string | 查询 WiFi SSID |
| 0x34 | WIFI_PASSWORD | 下行 | string | 设置 WiFi 密码 |
| 0x35 | WIFI_PASSWORD_GET | 上行 | string | 查询 WiFi 密码 |
| 0x36 | FILM_API_URL | 下行 | string | 设置 film 下载 API 地址 |
| 0x37 | FILM_API_URL_GET | 上行 | string | 查询 film 下载 API 地址 |
| 0x38 | WIFI_CONNECT | 下行 | 无 | 连接 WiFi |
| 0x39 | WIFI_DISCONNECT | 下行 | 无 | 断开 WiFi 连接 |
| 0x3A | WIFI_CONNECT_GET | 上行 | uint8 | 查询 WiFi 连接状态 (0: 未连接, 1: 已连接) |
| 0x3B | WIFI_CLEAR | 下行 | 无 | 清除所有网络配置 |

### 4.2 配网流程

```
小程序                              设备
  |                                  |
  | -- WIFI_ENABLE(1) ------------> | (1) 开启 WiFi
  | -- WIFI_SSID("MyWiFi") ------> | (2) 设置 SSID
  | -- WIFI_PASSWORD("pwd123") --> | (3) 设置密码
  | -- WIFI_CONNECT --------------> | (4) 连接 WiFi
  |                                  |     - 初始化 WiFi STA
  |                                  |     - 扫描并连接路由器
  |                                  |     - 获取 IP 地址
  | <-- WIFI_CONNECT_GET --------- | (5) 查询连接状态
  |        返回: 0x01 (已连接)       |
```

### 4.3 下载流程

```
设备                                         HTTP API
  |                                             |
  | (1) 接收到下载触发（定时/手动）              |
  | (2) 检查 WiFi 已连接                        |
  | (3) 检查 film_api_url 有效                  |
  |                                             |
  | -- HTTP GET film_api_url ----------------> |
  | <-- HTTP 200 + film 文件数据 -------------- |
  |                                             |
  | (4) 缓存数据到 SPIRAM                       |
  | (5) 保存到 SD 卡                            |
  | (6) 切换到新下载的文件显示                   |
```

### 4.4 播放模式

设备支持三种播放模式（通过 `CTRL_MODE` 命令设置）：

| 模式值 | 名称 | 说明 |
|--------|------|------|
| 0 | 手动模式 | 手动切换显示文件 |
| 1 | 本地轮播 | 从 SD 卡本地文件自动轮播 |
| 2 | WiFi 轮播 | 定时从 API 下载最新文件并显示 |

## 5. API 接口规范

设备以 HTTP GET 方式请求 `film_api_url`，期望返回 **film 格式文件**的二进制数据。

### 请求格式

```
GET {film_api_url} HTTP/1.1
Host: {host}
User-Agent: ESP32 HTTP Client
```

### 响应要求

| 要求 | 说明 |
|------|------|
| Content-Type | `application/octet-stream` 或 `image/*` |
| 超时时间 | 30 秒 |
| 重定向 | 支持 HTTP 301/302 重定向 |

### 示例

```
# 请求
GET https://example.com/api/film/latest HTTP/1.1

# 响应
HTTP/1.1 200 OK
Content-Type: application/octet-stream
Content-Length: 120032

<film binary data>
```

## 6. 固件实现

### 6.1 模块结构

| 文件 | 说明 |
|------|------|
| `service_wifi.h` | WiFi 服务接口定义 |
| `service_wifi.c` | WiFi 服务实现（STA 连接、事件处理） |
| `service_param.h` | 参数结构体定义（含网络配置） |
| `service_ble.h/c` | BLE 命令处理（WiFi 相关命令） |
| `service_film.c` | film 播放控制（WiFi 轮播模式） |

### 6.2 关键函数

```c
// 初始化/反初始化
void service_wifi_init(void);
void service_wifi_deinit(void);

// 连接/断开
void service_wifi_connect(void);
void service_wifi_disconnect(void);

// 状态查询
uint8_t service_wifi_get_connect_status(void);  // 0: 未连接, 1: 已连接

// 配置管理
void service_wifi_clear_config(void);            // 清除网络配置并保存

// 下载控制
void service_wifi_download_start(void);          // 开始下载
uint8_t service_wifi_download_get_progress(void); // 获取下载进度 (0-100)
wifi_download_state_t service_wifi_download_get_state(void); // 获取下载状态
```

### 6.3 下载状态枚举

```c
typedef enum {
    WIFI_DOWNLOAD_IDLE = 0,       // 空闲
    WIFI_DOWNLOAD_DOWNLOADING,    // 下载中
    WIFI_DOWNLOAD_DONE,           // 下载完成
    WIFI_DOWNLOAD_ERROR           // 下载失败
} wifi_download_state_t;
```

### 6.4 数据流程

```
service_wifi_download_start()
  └─> 创建 FreeRTOS 任务 (wifi_download_task)
       └─> esp_http_client_perform()
            └─> wifi_http_event_handler()
                 ├─ HTTP_EVENT_ON_DATA: 缓存到 SPIRAM
                 └─ HTTP_EVENT_ON_FINISH: 写入 SD 卡
```

## 7. 小程序端

### 7.1 BLE 命令常量

在 [ble-utils.js](../../tools/wechart/miniprogram/utils/ble-utils.js) 中定义：

```javascript
const BLE_FILM_TRANS_CH_CTRL_WIFI_ENABLE       = 0x30;
const BLE_FILM_TRANS_CH_CTRL_WIFI_ENABLE_GET   = 0x31;
const BLE_FILM_TRANS_CH_CTRL_WIFI_SSID          = 0x32;
const BLE_FILM_TRANS_CH_CTRL_WIFI_SSID_GET      = 0x33;
const BLE_FILM_TRANS_CH_CTRL_WIFI_PASSWORD      = 0x34;
const BLE_FILM_TRANS_CH_CTRL_WIFI_PASSWORD_GET  = 0x35;
const BLE_FILM_TRANS_CH_CTRL_FILM_API_URL       = 0x36;
const BLE_FILM_TRANS_CH_CTRL_FILM_API_URL_GET   = 0x37;
const BLE_FILM_TRANS_CH_CTRL_WIFI_CONNECT       = 0x38;
const BLE_FILM_TRANS_CH_CTRL_WIFI_DISCONNECT    = 0x39;
const BLE_FILM_TRANS_CH_CTRL_WIFI_CONNECT_GET   = 0x3A;
const BLE_FILM_TRANS_CH_CTRL_WIFI_CLEAR         = 0x3B;
```

### 7.2 使用示例

```javascript
// 设置 WiFi 参数并连接
app.sendBleCmd(0x30, 1);           // 开启 WiFi
app.sendBleCmd(0x32, "MyWiFi");    // 设置 SSID
app.sendBleCmd(0x34, "password");  // 设置密码
app.sendBleCmd(0x38, null);        // 连接
```

## 8. 使用场景

### 8.1 远程推送显示

1. 通过小程序配网（BLE 设置 WiFi 参数）
2. 设置 API 地址为远程服务器 URL
3. 设备连接 WiFi 后，自动从 API 下载最新 film 文件
4. 适用于远程分享照片给家人（父母家的冰箱贴）

### 8.2 WiFi 轮播

1. 将播放模式设置为 WiFi 轮播（mode = 2）
2. 设备定时从 API 拉取最新数据
3. 自动刷新屏幕显示最新内容
4. 适用于实时内容推送（天气、日历等）

## 9. 版本历史

| 版本 | 日期 | 描述 |
|------|------|------|
| 1.0 | 2026-07-22 | 初始版本，基于 service_wifi.c v0.1 |

## Ark App HTTP 直传流水线（2026-10-27）

本节适用于 `frame_film_ark` 的 App WiFi Direct 文件直传。Android 创建组并提供 HTTP 文件服务，Ark 作为 STA 用一次 GET 接收完整文件；不依赖外部路由器。前面的 Pro 配网/轮播说明不描述此路径。

参考 [Espressif Wireless Disk](https://github.com/espressif/esp-iot-solution/tree/master/examples/usb/device/usb_msc_wireless_disk) 的网络接收与落盘分离方式实现；没有照搬其大内存配置，也没有更换传输协议。

- 接收端一次申请3×16 KiB PSRAM缓冲池，聚合短HTTP read，按完整块或文件末尾短块交给既有file_task。
- 复用原4 KiB内部DMA中转及扇区对齐写入，不增加任务栈，不增加内部DMA缓冲。
- 异步保存接口借用缓冲，file_task完成后回调归还；入队失败没有回调，缓冲仍归调用者。同步BLE上传仍接管并释放消息缓冲。
- 进度按已写入成功的块累计，不能将仅进入队列的字节算作保存完成。最终仍检查长度、关闭文件、验证与提交结果。
- HTTP截断、短写、取消或资源不足不会提交正式文件；先收回全部在途缓冲，再撤销暂存文件和释放缓冲池。已有owner互斥、目标旧文件保护与文件任务单写者规则保留。
- BLE进度/取消通道和断连取消语义保留，传输期间仍使用WIFI_PS_NONE。本次未修改TCP窗口、BLE共存配置、显示版本3.2.5。
- Film、动画及显式路径文件（包括通行证资料）使用此路径；OTA的Flash写入及旧film_api_url轮播下载路径不在本次变更范围内。

### 诊断与验证

结束时输出一次 `HTTP pipeline`：net/saved字节、reads/blocks计数、read_us、queue_wait_us、write_us、elapsed_us；提交阶段另输出 `HTTP final commit_us` 与result。阶段时间会重叠，不能相加当总耗时。queue_wait_us包括提交文件消息及等待完成缓冲的时间；write_us来自文件任务的数据处理分支，包含检查和实际写入。elapsed_us涵盖缓冲准备、接收与排空，不含HTTP建连或最终提交。

[聚焦宿主检查](../../tools/wifi-transfer-tests/README.md)编译真实C接收函数及文件任务分支，覆盖短read、尾块顺序、缓冲生命周期、取消、写失败、截断、入队/分配失败与同步BLE释放行为；依赖由stub提供，不能代替ESP-IDF并发及SDMMC实测。

本机ESP-IDF 5.5.2构建通过，版本3.2.5，诊断镜像1939280B，仍适配现有1945600B应用分区。此前47,347,232B文件用时695.130秒、约68.1kB/s是旧实现实测；本次尚未取得设备吞吐对比，不能宣称已提速。下一轮应在同手机、同文件和同SD卡条件下比较保存完成耗时与上述阶段日志。

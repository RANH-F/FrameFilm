# Ark 自动构建

工作流：`.github/workflows/ark-builds.yml`。仅构建 Flutter Android app 与 `firmware/frame_film_ark`，不构建经典固件或 Dock。

## 触发与下载

- 推送到 `main`、向 `main` 提交 PR 时，限定 Flutter、复用的 Android Kotlin 源码、Ark 固件及工作流自身路径。
- main 推送或目标为 main 的 PR 自动构建；工作流进入默认分支后，也可从 GitHub → Actions → Ark builds → Run workflow 手动运行。
- 两个 job 独立运行，完成后从该次运行的 Artifacts 下载。构建失败时保留已生成的日志；SDK 安装或 checkout 阶段失败请查看 Actions 步骤日志。

## Android

固定 Flutter 3.47.6（随附 Dart 3.13.5）、Temurin JDK 21；Gradle 9.3.1、AGP 9.1.0、Kotlin 2.4.0 与 Android SDK 配置由仓库文件控制。JDK 21 用于运行构建，应用仍保持 Java/Kotlin 17 编译目标，最低安装系统 Android 9（API 28）。CI APK 包含 Flutter 默认支持的多个 Android ABI，本机快速验证包为 arm64。

仓库忽略 Gradle wrapper 脚本和 jar。CI 使用同版本 Flutter 在临时目录生成 Android 项目，仅复制 wrapper 脚本/jar，不覆盖仓库中的 Gradle 配置和业务代码。

产物 `ark-flutter-release-apk` 包含构建原件 `app-release.apk`，以及用于 GitHub Release 的精确命名附件 `framefilm-ark-flutter.apk`、`framefilm-ark-flutter.json`。JSON 记录包名、versionName、versionCode、最低 Android 版本、APK 大小和 SHA-256；上传前检查 `libapp.so` 与 `libflutter.so` 存在且没有 debug 的 `kernel_blob.bin`。日志位于 `ark-flutter-build-logs`。

Release/AOT APK 使用独立发行密钥，缺少配置时不会回退到 debug 签名。按 [Component_Manager 的发行工作流](https://github.com/Rafael-ban/Component_Manager/blob/master/.github/workflows/release.yml) 配置四项仓库 Actions Secrets：`ANDROID_KEYSTORE_BASE64`、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS`、`ANDROID_KEY_PASSWORD`。工作流在 runner 临时目录恢复 keystore，将路径及签名参数交给 Gradle，结束后删除临时密钥。Fork PR 无法访问这些 Secrets，因此不能完成发行签名 job。

本机密钥与私有 `key.properties` 保存在 `D:\FrameFilm-signing`，不提交到仓库。`flutter_app/tool/flutter.ps1` 默认引用此配置；其他环境可设置 `FRAMEFILM_SIGNING_PROPERTIES`，或使用 `ANDROID_KEYSTORE_PATH` 与上述三个密码/别名环境变量。请将整个签名目录另行安全备份，后续更新必须继续使用同一密钥。旧 debug 签名的正式包不能被新发行签名直接覆盖；`.dev` 开发包可继续并行保留，迁移前需备份旧 App 本地资料。

2026-10-16 本机 Release 构建和 APK 签名验证通过，最终 APK 为 59,802,980 字节，证书 SHA-256：`e5c1b5305670858656fce38cea82614838992aa3326ef3166546af4f9da7245e`。用户授权后，以上四项 Secrets 已加密上传到 `Rafael-ban/FrameFilm`，并回查各项元数据确认存在。这不代表新工作流已经在云端运行或已完成手机安装验收。

## Ark 固件

使用 Espressif 官方 `espressif/idf:v5.5.2` 容器与仓库现有 `sdkconfig`（ESP32-S3、自定义 OTA 分区），不执行 `set-target` 或重置配置。依赖按 `dependencies.lock` 从 Espressif registry 解析；不依赖本机 build/managed_components。

`ark-esp32s3-firmware` 包含：

- `frame_film_ark.bin`：应用镜像，用于现有 OTA 流程。
- `frame_film_ark-flash.bin`：按构建生成的 flash_args 合并的串口烧录镜像，从地址 `0x0` 写入；此操作会覆盖镜像范围内的现有数据，应先备份设备数据。
- bootloader、partition-table、OTA 初始化镜像，以及 flash_args/flasher_args.json：按该次构建生成的偏移进行分文件烧录。
- ELF、map、sdkconfig：用于定位问题和核对构建配置。

`ark-firmware-build-logs` 包含构建、merge-bin、`idf.py size` 报告及生成的 IDF 日志。CI 不连接设备、不刷机。普通构建不发布 Release；手动发布选项见下。

## 验证范围

首次远端运行：[Ark builds #37736539292](https://github.com/Rafael-ban/FrameFilm/actions/runs/37736539292)，源码提交 `f9614d3`。已验证 Flutter APK 编译、运行资源检查、APK 上传，以及 ESP-IDF 5.5.2 Ark 固件编译、大小报告、合并镜像与产物上传；两份构建日志也已上传。编译成功和 APK 资源检查通过不代表设备最终文件提交、相机、屏幕刷新或 OTA 已经实测。

参考：[Flutter action](https://github.com/subosito/flutter-action)、[Gradle Java compatibility](https://docs.gradle.org/current/userguide/compatibility.html)、[Espressif 官方 CI 容器](https://github.com/espressif/esp-idf-ci-action)、[IDF 5.5.2 merge-bin 实现](https://github.com/espressif/esp-idf/blob/v5.5.2/tools/idf_py_actions/serial_ext.py)。

## 可选 GitHub Release 固件发布

`workflow_dispatch` 提供 `publish_release`，默认 false。只有手动选择 main 并勾选此项，且该次 firmware 与 Android job 均成功，才运行 release job；普通 push/PR 继续只构建并上传 Artifacts。仅 release job 获得 contents:write。手动任务不启用运行中自动取消。

- 发布附件包含原始 `frame_film_ark.bin`、`framefilm-ark-flutter.apk` 和 `framefilm-ark-flutter.json`，不上传合并串口镜像作为在线升级包；release job 同时依赖 firmware 和 Android job 成功。
- 发布 tag 为 `ark-build-运行号-尝试号`，标题按构建编号显示，target 指向本次源码 SHA；重跑使用新尝试号，不覆盖旧发布附件。
- Release notes 记录源码提交和完整文件 SHA256。保留仓库原有 Latest 标记，客户端从最近20个正式发布中按 published_at 选含精确 Ark 资产的最新候选。
- `3.2.5` 不参与发布选择或升级判断。文件摘要用于下载完整性，实际 ELF SHA256 用于同构建跳过及重启后确认。
- 客户端无登录查询公开 Releases；只下载后校验导入，不自动刷机。若 GitHub 资产 digest 存在则同时核对；未提供时仍检查应用镜像自身完整性、ESP32-S3和Ark项目身份。

2026-10-09 已推送提交 `4fa8e77`，[Actions #37910525382](https://github.com/Rafael-ban/FrameFilm/actions/runs/37910525382) 的 Android APK 与 Ark 固件 job 均成功，包含新增 Android 原生更新代码、AOT 资源检查和 APK 元数据生成。此次为普通 push，Release job 按预期跳过；公开发布与 App 内覆盖安装仍需单独验收。

参考：[GitHub Releases API](https://docs.github.com/en/rest/releases/releases)、[gh release create](https://cli.github.com/manual/gh_release_create)。

该次 CI APK 为 `0.4.0+4`，59,475,012 字节，最低 API 28，包含 arm64-v8a / armeabi-v7a / x86_64。下载后 SHA256 与 JSON 元数据一致：`1afd4547b5106d436599b7e59a13ffb93f1725f573a0007331062998ece3c13b`。本地路径为 `D:/dev-tool/FrameFilm-build/ci/37910525382/extracted/app-release/framefilm-ark-flutter.apk`。本轮本机构建因工具审批超时未执行，交付的是 CI 产物。

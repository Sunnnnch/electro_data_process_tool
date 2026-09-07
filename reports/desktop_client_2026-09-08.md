# Windows 客户端首版验收记录

日期：2026-09-08。产品：ElectroChem｜智能电化学数据处理软件。版本：6.0.20，本地测试构建。

开始实施前已创建本地 Git 检查点 `072a555`（`chore: save verified theme branding and manuals before desktop client work`）。本次客户端改动在此基线上完成，未推送远程或发布版本。

## 实现范围

- 使用 WebView2 显示独立桌面窗口，启动本机计算服务；同一数据目录重复启动时唤起已有窗口。
- 记住窗口位置、大小、最大化状态、语言、外观、项目与助手会话；显示器变化后恢复到可见区域。
- 提供系统托盘、后台继续、等待完成退出与取消任务退出。已接收的 HTTP 请求先完成，再停止任务提交，最后等待计算及不可取消写入完成。
- 原生文件选择、TXT/CSV 拖入、结果另存为、数据目录入口；网页导出与受支持的示例下载使用原生保存窗口。
- 明确区分安装版用户数据与便携版数据；旧数据复制使用进程检查、SQLite 备份及文件校验，保留历史标识、指纹与源文件。历史引用仍可能依赖旧目录，因此复制后不能据此删除旧目录。
- 用户主动检查 GitHub Releases，显示版本和发布说明并打开官方发布页；不自动下载或执行更新。
- `start.bat` 启动桌面版，`start_browser.bat` 保留浏览器入口；已更新中英说明与客户端文档。

## 验证范围

最终完整回归 **1287 项全部通过**，耗时 280.51 秒。日志：`.test_runtime/desktop-full-regression-final.log`。重构建与冻结 EXE 验收均已完成。

回归命令为 `python -m pytest tests -o addopts='' -q -p no:cacheprovider --tb=short`；启用 `ELECTROCHEM_REQUIRE_PLAYWRIGHT=1`，数据目录设为 `.test_runtime/desktop-full-regression-final`，`PYTHONPATH` 包含源码和本地测试依赖目录。Ruff、Pyright（0 错误/警告）、`app.js` 与 `desktop.js` 的 Node 语法检查、`git diff --check` 均通过。

已通过的针对性验证包括：真实跨进程单实例激活、显示器变化、偏好保存、桥接访问范围、原生保存取消、SQLite/WAL 迁移及历史复算；任务测试使用真实线程与独立进程。

退出回归另覆盖普通计算和助手任务各自的等待/取消模式：真实 TCP 请求先发送请求头、暂停请求体，在退出开始后补发请求体；已接收请求返回 202，新请求返回 503，窗口等待工作完成或安全取消后才关闭。

开发环境下的真实 WebView2 验证覆盖 WinForms 文件拖入、预检、实际 CV 计算、原生关闭按钮、等待退出和托盘恢复，记录位于 `.test_runtime/desktop-native/report-active.json`。自动测试不调用外部付费模型。

最终 EXE 的独立验收记录位于 `.test_runtime/frozen-desktop-final/report.json`，结果为 `passed`。测试启动时清除源码 `PYTHONPATH`，使用实际打包的计算引擎与 WebView2 152.0.4191.66：

- 中文、英文界面、桥接、托盘和偏好保存通过，浏览器脚本错误列表为空。
- CV 预检完成；任务 `c972c5f3f911490bae8b6d73307505c2` 状态为 `succeeded`，生成 7 个结果文件。
- 二次启动退出，原客户端和服务保持运行；随后正常退出，测试进程和端口均无残留。

PyInstaller 6.17.0 与 Inno Setup 6.5.2 重构建成功；构建日志为 `.test_runtime/desktop-onedir-build.log` 和 `.test_runtime/desktop-installer-build.log`。完整构建环境依赖记录在便携目录的 `runtime-requirements.txt`。

| 产物 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `dist/ElectroChemV6/ElectroChemV6.exe` | 21,692,961 | `b014106016cc8ca643360ce42a2d1a29cbaa476826d8c193abe39c3ca95a8658` |
| `dist_installer/ElectroChemV6-Setup-6.0.20.exe` | 63,770,615 | `9ea65297fbf75c6e166afd2fc4b7690fac75d6a12e73ef072dd38d083f618559` |

安装包旁的 `.exe.sha256` 已与文件哈希比对一致。

## 使用与发布边界

安装包位于 `dist_installer/ElectroChemV6-Setup-6.0.20.exe`。便携程序位于 `dist/ElectroChemV6/ElectroChemV6.exe`，须保留整个目录。

本地构建未签名，尚未在干净 Windows 环境实际执行安装、升级及卸载；未在当前电脑运行安装器。默认安装包不内置 WebView2 Runtime，缺失时由安装向导提供 Microsoft 官方下载入口。

所有运行验收使用 `.test_runtime` 下的独立数据目录及空闲端口，没有迁移或修改用户项目数据；安装目录中未创建测试用 `user_data`。

计算流程与现有数据分析助手沿用原有实现。在线模型依然需要相应网络和模型配置；客户端打包不包含本地大语言模型。

使用说明见 `docs/desktop_client.md`，构建与签名说明见 `packaging/README.md`。

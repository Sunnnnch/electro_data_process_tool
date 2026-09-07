# 客户端图标、名称与原生标题栏验收

日期：2026-09-08。版本：6.0.20，本地测试构建。

## 修改内容

- 采用用户选定的 D「智能数据」图标。原 PNG 字节保持不变；窗口、托盘、浏览器入口、EXE 和安装包统一使用该图标。
- `packaging/build_icon.ps1` 使用 Windows .NET 图像工具生成 16、20、24、32、40、48、64、128、256 像素的 ICO，保留透明通道。九帧均通过 Windows 原生图标解码；重复生成哈希一致。
- 对外文件名改为 `ElectroChem.exe`、`ElectroChem-Setup-6.0.20.exe`，Windows 文件属性、安装卸载名称和快捷方式不附加 V6。版本号仍单独保留为版本信息。
- 保留原安装标识、安装目录、数据目录及进程互斥名称；安装更新指向新 EXE 的快捷方式，精确清理旧 EXE；更新检查兼容旧发布文件名。构建发现便携 `user_data` 时会拒绝清理。
- 原生窗口采用固定的 `ElectroChem.Desktop` 应用标识。标题栏根据软件实际页眉颜色同步背景、文字及按钮明暗，保留 Windows 最小化、最大化还原、关闭与窗口操作。
- 跟随系统模式与高对比度响应分别处理；系统高对比度优先。不支持原生配色接口的系统保留默认外观。Windows 系统任务栏整体外观仍由系统控制。

## 已完成验证

- **完整回归：1319 项全部通过，278.40 秒**。日志：`.test_runtime/branding-full-regression.log`。启用真实 Playwright 浏览器测试，使用隔离数据目录；未调用外部付费模型。
- Ruff、Pyright、JavaScript 语法检查和 `git diff --check` 通过。
- 真实 Windows 11 build 26200、WebView2 152.0.4191.66 窗口验收通过：新图标与包内 ICO 一致，应用标识正确，四主题实际标题栏配色成功；原生最小化、还原、最大化和关闭正常。
- 在本机，`DwmGetWindowAttribute` 可读取属性 20，但读取 35/36 返回 `E_INVALIDARG`；因此颜色验证采用成功的 Set 调用加完整窗口截图，不将不支持的 Get 当作产品故障。
- “跟随系统”和高对比度通过浏览器媒体模拟触发，并验证实际原生响应；没有改变操作系统全局主题或高对比度设置。
- 原生报告：`.test_runtime/titlebar-native/report.json`。完整窗口截图：`.test_runtime/titlebar-native/window-dark.png`、`window-lab.png`、`window-ocean.png`、`window-pixel.png`。

图标 SHA-256：

| 资源 | SHA-256 |
| --- | --- |
| 用户选中 PNG 与桌面/网页副本 | `56a8d058975f1b4703fa39f1faa83feafbc875622c61015484429555faa96a59` |
| 桌面及安装包 ICO | `34df33d431b3ac00a0614990a4c8a24dd8f28419051ff28744ff5da46e846875` |

## 构建与交付

新 EXE 与安装包均已生成，Windows 产品名称和文件说明均为“智能电化学数据处理软件”，版本为 6.0.20。两项产物的 PE 图标资源都包含正式 D 图标的九帧，各帧与源 ICO 的哈希完全一致。

| 产物 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist/ElectroChem/ElectroChem.exe` | 21,662,290 | `b92afcc61dfb54934572fab75061a3be2726dc0ba5d27505999ddb2d4d864986` |
| `dist_installer/ElectroChem-Setup-6.0.20.exe` | 64,213,253 | `e24175f5d2762c8d2e831178a5dbc4a90863598c0e9e43c494d4607b56fd94ff` |

安装包附带同名 `.sha256` 校验文件。两项产物均未签名；直接运行 EXE 时须保留整个 `dist/ElectroChem` 文件夹。

最终冻结 EXE 在独立数据目录中实际运行通过：真实 WebView2 和托盘、正式名称及中英文菜单、窗口图标逐像素比对、四主题原生标题栏配色、最小化/最大化/还原、CV 数据处理成功并输出 7 个文件、第二次启动保持原实例、原生关闭按钮正常退出。页面 JavaScript 错误为空，测试进程及专用端口已关闭，未在发布目录写入 `user_data`。

冻结 EXE 验收报告：`.test_runtime/branding-frozen/report.json`。完整窗口截图：`.test_runtime/branding-frozen/frozen-window-lab.png`、`frozen-window-dark.png`、`frozen-window-ocean.png`、`frozen-window-pixel.png`。产物清单和嵌入图标校验分别记录在 `.test_runtime/desktop-distribution-manifest.json`、`.test_runtime/desktop-embedded-icon-validation.json`。

本次不实际运行安装器、不发布远程版本。测试使用独立数据目录和端口，保留用户项目与此前生成的旧版本产物。现有旧任务栏固定入口若仍指向旧 EXE，可按 `docs/desktop_client.md` 说明重新固定新版入口。

原生接口依据：[Microsoft 的窗口属性说明](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)、[Win32 明暗主题说明](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-windows-themes)。

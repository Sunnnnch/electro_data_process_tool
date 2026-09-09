# macOS 客户端

ElectroChem 的 macOS 桌面客户端面向 **macOS 13 或更新版本**，分别为 **Apple Silicon（arm64）** 和 **Intel（x64）** 构建原生候选包。构建最低部署版本为 13.0，自动验收运行于 macOS 15，尚未完成 macOS 13/14 实机验收。候选包采用 **ad-hoc 签名，未经 Apple 公证**；公开 Release 是否提供 Mac 下载，以实际附件为准。

## 候选包与启动

按“关于本机”显示的芯片选择包：

| 电脑 | 候选包文件名 |
| --- | --- |
| Apple Silicon | `ElectroChem-<版本>-macos-arm64.dmg` 或同名前缀 `.zip` |
| Intel | `ElectroChem-<版本>-macos-x64.dmg` 或同名前缀 `.zip` |

包内包含 Python、计算依赖和原生桥接组件，界面使用系统 **WKWebView**，不需要 Windows 的 WebView2。保留完整 `ElectroChem.app`；DMG 中将它拖入“应用程序”，或解压 ZIP 后移动到该目录，再打开应用。首次打开可能受 macOS 安全检查限制；先核对来源和配套 `.sha256`，不要关闭系统安全检查。

在 [macOS Client 工作流](https://github.com/Sunnnnch/electro_data_process_tool/actions/workflows/macos.yml) 中打开成功的运行，下载名称带有对应架构的产物（不要选择 `diagnostics`）。GitHub 产物下载可能需要登录，候选安装包保存 14 天；过期后可重新运行工作流。产物包括 DMG、ZIP、配套 `.sha256`、构建清单和验证报告。

Mac 候选包不会替换现有 Windows 7.0.1 发布资产，也不会自动发布到 Releases。工作流检查原生窗口、Dock 恢复、任务退出保护、科学计算及打包后的 MCP；`verification.json` 记录实际运行系统、架构和检查结果。系统文件选择窗口的人工操作及 Gatekeeper 首次安装仍需人工验收。

核对来源后，如首次打开提示无法验证开发者，可参照 [Apple 的打开应用说明](https://support.apple.com/zh-cn/102445)，在“系统设置 → 隐私与安全性”中查看该应用的“仍要打开”选项；是否允许由本机安全策略决定。

更新时先退出客户端，再用新版本替换“应用程序”中的 `ElectroChem.app`。卸载时将应用移到废纸篓；用户数据目录会保留，重新安装可继续使用。移走或清理实验文件前，应先导出并核对备份。

## 从源码运行

安装与本机芯片架构匹配的 **Python 3.12**，确保终端中可运行 `python3.12`。在仓库目录执行：

```bash
bash Start_Mac.command
```

首次启动联网创建仓库内的 `.venv-macos`，并安装固定的 macOS 依赖；以后复用检查通过的环境。无需修改系统 Python，也不要求仓库保留脚本的可执行权限。基础分析、项目管理和报告可离线使用；首次准备依赖、云端 AI 和检查更新需要网络。

从源码直接启动浏览器服务时使用同一虚拟环境；若需与桌面共用数据，请明确指定目录：

```bash
ELECTROCHEM_V6_DATA_DIR="$HOME/Library/Application Support/ElectroChem" \
  .venv-macos/bin/python run_v6.py --port 8010
```

## 数据与窗口

桌面默认数据目录为 `~/Library/Application Support/ElectroChem`，保存项目、历史、设置、会话及恢复信息。“客户端 → 打开数据目录”可直接定位。实验原始文件与所选输出目录仍由用户管理。

应用与数据分开保存；移动或更换 `.app` 不会删除该目录。`ELECTROCHEM_V6_DATA_DIR` 可明确指定其他可写位置，但不能指向 `.app` 内部。Mac `.app` 不使用 Windows 便携版的内部 `user_data` 模式。旧源码目录 `~/.electrochem/v6` 可在迁移检查中核对并确认复制；已有目标数据不合并、不覆盖，历史引用的旧原始文件和输出仍需保留。

重复启动会唤起同一数据目录的已有窗口。“后台继续”隐藏窗口并保持任务运行，可从 Dock 重新打开。关闭窗口、⌘Q 和 Dock“退出”均经过任务退出保护；有活动任务或保存操作时，先按提示选择继续、等待或取消任务后退出。更新应用前，结束任务、退出客户端，并断开外部 AI 的 MCP 连接。

标题栏跟随软件明暗及配色，左上角窗口按钮由 macOS 绘制。文件选择与另存为使用系统窗口；当前 Mac 入口以“选择文件／文件夹”为准。

## 环境自检、MCP 与更新

“客户端 → 环境自检”检查系统版本、架构、WKWebView 桥接依赖和数据目录，可刷新与复制诊断。诊断不自动上传，不包含模型密钥；目录路径可能包含账户名。源码也可运行：

```bash
bash Start_Mac.command --environment-check --json
```

“客户端 → AI 连接（MCP）”生成当前应用与数据目录的完整配置。打包的 stdio 入口为 `/Applications/ElectroChem.app/Contents/MacOS/ElectroChem-MCP`；默认只读，需运行计算或导出时再启用写入权限。使用期间保持桌面运行。详见 [MCP 连接说明](mcp.md)。

“检查更新”仅在点击后查询官方 GitHub Releases，并按本机芯片选择带配套校验文件的 Mac DMG 或 ZIP；没有匹配包时给出明确状态。下载入口打开官方页面，不自动下载、执行或替换应用，也不能据此判断 Apple 公证状态。

# ElectroChem 7.0.1 发布说明

ElectroChem｜智能电化学数据处理软件 7.0.1 将本地电化学计算、Windows 桌面操作、项目结果复核和外部 AI 连接整合到同一工作流程。基础数据处理无需模型密钥，也无需启用 AI。

## Windows 桌面客户端

- 使用 `ElectroChem.exe` 打开独立窗口；窗口、托盘和安装包使用统一图标，显示名称不再附加 V6。
- 同一数据目录重复启动时唤起已有窗口。记住窗口位置、主题、语言、上次项目与助手会话；不自动恢复输入文件和实验参数。
- 支持原生文件选择、拖入 TXT/CSV、文件另存为和检查更新。拖入文件后仍需核对清单、类型及参数并预检。
- 有任务时关闭窗口可选择继续使用、后台继续、等待完成后退出或取消任务后退出。不可取消的保存阶段完成后才退出。
- 中断的数据处理可经来源检查与预检恢复为新任务；不会自动重发 AI 对话，也不是从计算中间点继续执行。

## 通过 MCP 连接其他 AI

“客户端 → AI 连接（MCP）”生成当前程序和数据目录的本地 stdio 配置，配套程序为 `ElectroChem-MCP.exe`。

默认提供项目与结果查询、明确记录比较、参数查询和预检。启用写入配置后，可新建处理任务和导出报告，任务及结果继续显示在本软件中。修改开关只改变生成的配置，需复制到 AI 客户端并重新连接后生效；已有连接保留其原权限。

连接期间需保持本软件运行。此接口复用本机计算服务，不调用内置助手或模型；外部 AI 客户端的模型、授权和费用由该客户端管理。它不提供删除数据、执行命令或修改模型密钥的工具，也不提供公网 MCP 服务。详见 [MCP 连接说明](mcp.md)。

## 主题与阅读

- 保留实验室浅色、高对比暗色、专业深海、像素终端四种主题，并支持跟随系统。
- 字号、舒适/紧凑密度和背景网格可以独立设置，旧主题选择继续保留。
- 原生标题栏采用独立配色及分界线，像素终端的窗口边界更加清晰；页面、列表、弹窗、说明和代码区域的滚动条统一适配主题。
- 系统高对比度优先。窗口按钮继续由 Windows 绘制，不支持自定义标题栏颜色的系统使用默认外观。
- 助手长文、代码和宽表格适配阅读；图表预览可跟随主题，科学图表导出保留固定配色与白底。

## 项目、复算和分析

- 项目工作区分为“结果、对比、报告”，结果按处理批次组织、详情按需展开。搜索样品或文件名，并用类型和日期筛选全部历史结果记录。
- 项目可关联参数模板，应用前预览差异；保存项目信息不会暗中改变当前处理目标。
- 对比明确指定的两条历史记录，展示指标、参数、来源及质量变化。报告明确区分全项目、所选结果和单次处理；勾选一条结果不会连带导出同批其他样品。
- 历史复算核验保存的参数、原始文件与辅助依赖，创建新运行和新输出目录，保留旧记录。已保留的原 ZIP 或有效恢复缓存可用于恢复上传来源。
- 助手提供参数建议、记录比较、复算计划和所选结果报告操作卡，通过预览与用户点击执行。LSV Tafel 候选显示点数、区间、拟合诊断和局限；缺少实验条件时先提示补全，候选不等于已确认的动力学区间。
- 独立重复实验组保存采用版本、排除理由与可比性确认，显示有效 n、均值和样本标准差，支持 CSV/SVG 导出。同源复算版本不作为多个独立实验重复计数。

计算仍支持 LSV、CV、EIS、ECSA 和 COUPLED/FE。输入列、单位、符号、扫速和参比基准需按实验记录确认；质量提示与来源记录帮助复核结果，不替代实验判断。中英文手册提供合成 CV 示例、操作流程和计算口径说明。

## 升级与数据兼容

1. 等待任务完成或在软件中取消，退出托盘客户端，并断开外部 AI 的 ElectroChem MCP 连接，再安装或替换程序文件。
2. 备份整个应用数据目录，以及历史引用的原始数据和输出文件。项目成果 ZIP 不能代替完整应用数据备份。
3. 安装版沿用既有安装标识和数据位置。便携版需保留完整程序目录与 `user_data`；换目录前先核对当前数据位置，按照客户端说明迁移或明确指定数据目录。不要覆盖正在运行的程序目录。
4. 旧历史继续保留其记录和来源路径。迁移会复制数据，不合并已有目标数据，也不擅自改写历史路径；确认历史文件仍可访问前，应保留旧目录。
5. 升级后先核对项目和历史，再对新数据运行预检。旧历史中缺少的参数、指纹或配方会显示为未记录；不能仅凭升级补齐证据或保证能够复算。

**版本为 7.0.1，但兼容标识保持不变。** 内部包名 `electrochem_v6`、`ELECTROCHEM_V6_*` 环境变量、安装标识和默认用户数据目录中的 `v6` 均继续使用，请勿为匹配新版本号而手动改名。历史复算使用当前引擎；软件、算法或依赖版本变化可能导致结果变化，不承诺跨版本逐位一致，也不会自动启动旧版本计算环境。

Windows 客户端需要 Microsoft Edge WebView2 Runtime。检查更新只打开官方发布页面，不自动替换程序；安装包、依赖与校验信息以该版本实际发布附件为准。完整说明见 [Windows 客户端](desktop_client.md)、[项目工作区与复算](project_workspace.md)、[中文手册](../src/electrochem_v6/ui/static/help_manual.zh.md)和[英文手册](../src/electrochem_v6/ui/static/help_manual.en.md)。

## English summary

Version **7.0.1** brings a native Windows workspace, task-aware exit and recovery, theme-aware native captions and scrollbars, and a local MCP connection for external AI clients. MCP is read-only by default; processing and report tools require an explicit write-enabled configuration and a reconnection. It uses the running local service and does not call the built-in assistant or a model.

Project workflows now provide full-history search, exact-record comparisons, source-checked replay, explicitly scoped reports and independent replicate summaries. Assistant action cards preview changes before applying them. Scientific conditions must still be supplied and verified; a suggested fit range is not a validated kinetic region.

Before upgrading, back up application data, original inputs and outputs; finish tasks, exit the tray application and disconnect MCP clients. Keep the complete application folder and all historical source files. Existing data locations, the `electrochem_v6` package, `ELECTROCHEM_V6_*` variables and installer identity remain unchanged. Missing legacy provenance cannot be reconstructed automatically, and replay uses the current engine without promising bit-for-bit agreement across versions. See the [English user guide](../src/electrochem_v6/ui/static/help_manual.en.md) for the operating workflow.

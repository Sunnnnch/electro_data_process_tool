# ElectroChem 7.0.1 发布说明

ElectroChem｜智能电化学数据处理软件 7.0.1 将本地电化学计算、Windows 桌面操作、项目结果复核和外部 AI 连接整合到同一工作流程。基础数据处理无需模型密钥，也无需启用 AI。

## Windows 桌面客户端

本轮补充按需环境自检、可复制启动诊断及明确区分的标准/离线安装包。发布目标为 Windows 10 22H2 / Windows 11 x64，WebView2 120+；离线包内含经过微软签名校验的 WebView2 独立安装程序。最低版本属于支持策略，独立机器的安装升级验收状态见[Windows验收矩阵](windows_acceptance_7.0.1.md)，不以本机编译或自动测试替代。默认助手入口更新为烧瓶星光图标和月白灰外观，并跟随当前配色变化。

- 使用 `ElectroChem.exe` 打开独立窗口；窗口、托盘和安装包使用统一图标，显示名称不再附加 V6。
- 同一数据目录重复启动时唤起已有窗口。记住窗口位置、主题、语言、上次项目与助手会话；不自动恢复输入文件和实验参数。
- 支持原生文件选择、拖入 TXT/CSV、文件另存为和检查更新。拖入文件后仍需核对清单、类型及参数并预检。
- 有任务时关闭窗口可选择继续使用、后台继续、等待完成后退出或取消任务后退出。不可取消的保存阶段完成后才退出。
- 中断的数据处理可经来源检查与预检恢复为新任务；不会自动重发 AI 对话，也不是从计算中间点继续执行。

## 通过 MCP 连接其他 AI

“客户端 → AI 连接（MCP）”生成当前程序和数据目录的本地 stdio 配置，配套程序为 `ElectroChem-MCP.exe`。

默认提供项目与结果查询、明确记录比较、参数查询和预检。启用写入配置后，可新建处理任务和导出报告，任务及结果继续显示在本软件中。修改开关只改变生成的配置，需复制到 AI 客户端并重新连接后生效；已有连接保留其原权限。

连接期间需保持本软件运行。此接口复用本机计算服务，不调用内置助手或模型；外部 AI 客户端的模型、授权和费用由该客户端管理。它不提供删除数据、执行命令或修改模型密钥的工具，也不提供公网 MCP 服务。详见 [MCP 连接说明](mcp.md)。

## 内置助手的模型选择

AI 设置在输入密钥后自动查询所填服务地址的模型列表，支持手动刷新、候选选择和手动填写模型 ID。查询不发送对话、不自动保存密钥，也不自动替换当前模型；不支持模型列表的兼容服务可继续手动配置。模型列表不能保证模型的对话能力或账户调用权限，“测试连接”会实际请求模型。更换服务地址到另一站点时，需提供对应密钥，避免把已保存凭据自动发往新站点。

## 主题与阅读

- 原“专业模式”更名为“数据处理”，中英文界面、助手与使用说明统一用词。顶部品牌区放大名称并加入图标，导航与工具按钮分行排列；客户端菜单文字与箭头居中对齐，并适配不同窗口宽度与字号。
- 提供现代简洁、纸感编辑、柔和模块、像素复古四种界面风格，保持相同分析功能。纸感编辑使用细线分隔和轻量纸面，默认复古米白；柔和模块使用舒展圆角和柔和层次，默认雾灰蓝。风格切换不改变计算或导出。
- 四种风格均可搭配实验室浅色、专业深海、高对比暗色、复古米白、石板蓝、暖黑琥珀、雾灰蓝、掌机黄绿、灰紫九组预设及自选颜色。背景、面板、强调色、正文和标题栏即时保存；切换配色保留风格，并同步标题栏、滚动条与助手。正文对比不足时提供提醒和自动文字颜色。
- 每种风格分别记住配色。“跟随系统”自动切换实验室浅色和高对比暗色，同时保留风格。旧外观设置自动迁移，未采用的旧自选颜色保存在可展开的恢复区。
- 配色区可恢复当前风格的默认颜色；弹窗底部恢复默认则清除四种风格的配色选择和旧配色备份，并重置阅读设置。字号、舒适/紧凑密度和背景网格可以独立设置。旧版仅有两种风格的设置会自动补全新增风格的默认配色，保留原自选颜色、备份与阅读设置。
- 原生标题栏采用独立配色及分界线，窗口边界更加清晰；页面、列表、弹窗、说明和代码区域的滚动条统一适配主题。
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

EIS 现提供六种等效电路：单时间常数 RC/CPE、半无限 Warburg RC/CPE、双时间常数 RC/CPE。可选择 Hz 频段与均匀/模值权重，查看 Nyquist/Bode 拟合叠图、残差、局部近似 95% 参数区间和参数可辨识性提示。KK 一致性检查可独立开启，结果按保存的经验门槛给出提示，不证明电路物理正确或实验完全满足 KK 假设。模型、分析频段、权重及完整诊断进入历史、报告和 JSON/CSV 导出，原始数据保留完整；详情见 [EIS 拟合说明](eis_fitting.md)。

本次检查补充了计算与报告边界保护：Tafel 电流或电位无可区分跨度时不输出斜率，低 R² 拟合标记需复核；ECSA 非正或平坦电容关系不输出无效面积。所选记录报告按来源筛选质量明细、计数与结果文件，无法确认的旧归属明确提示，整运行报告保留全量。

1. 等待任务完成或在软件中取消，退出托盘客户端，并断开外部 AI 的 ElectroChem MCP 连接，再安装或替换程序文件。
2. 备份整个应用数据目录，以及历史引用的原始数据和输出文件。项目成果 ZIP 不能代替完整应用数据备份。
3. 安装版沿用既有安装标识和数据位置。便携版需保留完整程序目录与 `user_data`；换目录前先核对当前数据位置，按照客户端说明迁移或明确指定数据目录。不要覆盖正在运行的程序目录。
4. 旧历史继续保留其记录和来源路径。迁移会复制数据，不合并已有目标数据，也不擅自改写历史路径；确认历史文件仍可访问前，应保留旧目录。
5. 升级后先核对项目和历史，再对新数据运行预检。旧历史中缺少的参数、指纹或配方会显示为未记录；不能仅凭升级补齐证据或保证能够复算。

**版本为 7.0.1，但兼容标识保持不变。** 内部包名 `electrochem_v6`、`ELECTROCHEM_V6_*` 环境变量、安装标识和默认用户数据目录中的 `v6` 均继续使用，请勿为匹配新版本号而手动改名。历史复算使用当前引擎；软件、算法或依赖版本变化可能导致结果变化，不承诺跨版本逐位一致，也不会自动启动旧版本计算环境。

Windows 客户端需要 Microsoft Edge WebView2 Runtime。检查更新只打开官方发布页面，不自动替换程序；安装包、依赖与校验信息以该版本实际发布附件为准。完整说明见 [Windows 客户端](desktop_client.md)、[项目工作区与复算](project_workspace.md)、[中文手册](../src/electrochem_v6/ui/static/help_manual.zh.md)和[英文手册](../src/electrochem_v6/ui/static/help_manual.en.md)。

## English summary

Version **7.0.1** brings a native Windows workspace, task-aware exit and recovery, theme-aware native captions and scrollbars, and a local MCP connection for external AI clients. Appearance offers Modern, Paper Editorial, Soft Modules and Pixel Retro styles, independently combined with nine preset palettes and custom colors. Each style remembers its own palette; following system light/dark preferences preserves the chosen style. Upgrades retain existing colors, custom backups and reading settings while adding defaults for new styles. Unused custom palettes remain available for recovery. Contrast guidance and separate resets are provided. Style and palette changes update the workspace, assistant and native captions without changing calculations or exports; paper-white previews and scientific data colors are retained. MCP is read-only by default; processing and report tools require an explicit write-enabled configuration and a reconnection. It uses the running local service and does not call the built-in assistant or a model.

Project workflows now provide full-history search, exact-record comparisons, source-checked replay, explicitly scoped reports and independent replicate summaries. Assistant action cards preview changes before applying them. Scientific conditions must still be supplied and verified; a suggested fit range is not a validated kinetic region.

Before upgrading, back up application data, original inputs and outputs; finish tasks, exit the tray application and disconnect MCP clients. Keep the complete application folder and all historical source files. Existing data locations, the `electrochem_v6` package, `ELECTROCHEM_V6_*` variables and installer identity remain unchanged. Missing legacy provenance cannot be reconstructed automatically, and replay uses the current engine without promising bit-for-bit agreement across versions. See the [English user guide](../src/electrochem_v6/ui/static/help_manual.en.md) for the operating workflow.

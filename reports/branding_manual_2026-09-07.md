# 软件更名与使用说明更新验证

日期：2026-09-07。版本保持 `6.0.20`。

## 名称与兼容性

- 中文名称：ElectroChem｜智能电化学数据处理软件。
- 英文名称：ElectroChem | Intelligent Electrochemical Data Processing Software。
- 界面品牌、浏览器标题、桌面启动器窗口、安装器展示名称、启动检查、命令行说明及 README 已统一；版本单独显示。
- 保留 `electrochem_v6` 包名、`ElectroChemV6.exe`、安装器 AppId、安装目录、数据库和用户数据路径。
- 安装器配置仅增加两个固定旧名称快捷方式的清理规则；本次未运行安装、未重新打包。

## 使用说明

- [中文说明](../src/electrochem_v6/ui/static/help_manual.zh.md)和[英文说明](../src/electrochem_v6/ui/static/help_manual.en.md)均按当前界面重写，包含 8 个主节和 27 个小节。
- 覆盖输入与参数、预检、项目模板与筛选、指定结果对比、历史复算、重复实验、可复现报告、助手操作卡、任务恢复及外观设置。
- 区分 CV 与 LSV 的面积/电位/符号处理；解释绝对电荷积分、ECSA Ev 的源电位基准、EIS 配对预检与实际 Rs 提取时机。
- 四张中英文操作截图来自隔离服务上的真实界面。说明页支持查看原图，正文字号随外观设置变化。
- 加入可下载的[合成 CV 示例](../src/electrochem_v6/ui/static/guide-cv-demo.csv)，下载名为 `CV_demo.csv`；[生成与计算说明](../docs/demo_data.md)记录合成公式和预期输出。
- 脚本调用内容移入独立[中文接口指南](../docs/api_guide.zh.md)和[英文接口指南](../docs/api_guide.en.md)。同步更新 OpenAPI 名称、根响应结构，并补充预检接口。

## 验证结果

- 相关自动化回归 **159 passed in 84.11s**：UI、静态资源、外观/手册展示、服务、入口、打包兼容、配置、存储、运行清单及可复现报告。
- 浏览器检查覆盖 1440/600 宽度、中英文、标准/最大字号、实际文本边界、四张图片解码与原图打开、CSV 文件名与逐字节内容，以及手册本地资源范围。
- Ruff 通过；Pyright 为 0 errors、0 warnings；`app.js` 和 `i18n.js` 语法检查及 `git diff --check` 通过。
- `python run_v6.py check` 通过，五类处理模块可运行，应用名称正确。
- 实际 CV 流程经过文件选择、预检、后台处理、项目归档：200 点，0–1 V，约 −0.80–1.00 mA，两圈绝对积分电荷 **18.4474 mC**；生成图像、结果表、质量文件与运行报告。
- API 示例实际验证 LSV 后台处理、精确主数据选择、COUPLED 同步处理、不可运行预检、浏览器会话校验；助手传输使用本地桩，不调用外部模型。
- OpenAPI 严格检查通过：68 个唯一 operationId、132 个本地引用全部解析；双语示例语法和资源链接检查通过。

回归命令：

```powershell
python -m pytest tests/test_v6_ui_playwright.py tests/test_v6_ui_static_models.py tests/test_v6_appearance_ui.py tests/test_v6_server.py tests/test_v6_entry_points.py tests/test_v6_packaging_contract.py tests/test_v6_config_precedence.py tests/test_v6_store_runtime.py tests/test_v6_processing_manifest.py tests/test_v6_reproducible_reports.py -o addopts='' -q -p no:cacheprovider --tb=short
```

测试使用隔离运行目录并要求 Playwright 可用；未操作用户正在运行的服务或项目数据。截图与测试日志保存在被忽略的 `.test_runtime` 下。本次验证不包含重新构建安装包或执行实际升级安装。

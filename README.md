<h1>
  <img src="docs/logo.png" width="36" height="36" align="absmiddle" />
  ElectroChem｜智能电化学数据处理软件
</h1>

[![CI](https://github.com/Sunnnnch/electro_data_process_tool/actions/workflows/ci.yml/badge.svg)](https://github.com/Sunnnnch/electro_data_process_tool/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Sunnnnch/electro_data_process_tool?include_prereleases)](https://github.com/Sunnnnch/electro_data_process_tool/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文](README.md) | [English](README.en.md)

数据处理 · 项目管理 · 结果复核 · AI 辅助分析

ElectroChem 面向电化学实验数据的本地处理与分析，支持 `LSV`、`CV`、`EIS`、`ECSA`、`COUPLED/FE` 批量处理、项目历史与可复现报告，以及可选的 AI 辅助分析。基础数据处理无需配置 AI。

当前源码版本：**7.0.1** · [本版发布说明与升级注意](docs/release_7.0.1.md) · [更新记录](CHANGELOG.md)

当前公开安装包仍为 [v6.0.20](https://github.com/Sunnnnch/electro_data_process_tool/releases/tag/v6.0.20)；7.0.1 安装包尚未正式发布，详见[验收与发布者签名进度](docs/windows_release_readiness_7.0.1.md)。

7.0.1 沿用既有数据位置和内部兼容标识。升级前请备份应用数据及原始/输出文件，结束任务、退出托盘并断开 MCP 连接；不要因目录名中保留 `v6` 而手动改名。

[完整使用说明](src/electrochem_v6/ui/static/help_manual.zh.md) · [合成 CV 示例](src/electrochem_v6/ui/static/guide-cv-demo.csv) · [开发者接口指南](docs/api_guide.zh.md)

## 项目简介

`ElectroChem` 的目标是把常见电化学数据处理流程收敛到一个统一工作台中，减少手工整理、重复导出和脚本碎片化问题。

适用场景：

- 批量处理同一批实验样品
- 统一输出 `LSV` / `CV` / `EIS` / `ECSA` / `COUPLED` 结果文件
- 保留项目、历史和质量报告，方便复核
- 通过本地 UI 降低使用门槛

## 核心功能

- 支持 `LSV` / `CV` / `EIS` / `ECSA` / `COUPLED` 多类型数据处理
- 支持按文件名前缀、包含、正则进行批量匹配
- 支持 `LSV` 的目标电流、电位换算、`iR` 补偿、`Tafel`、`Onset`、`Halfwave`
- 支持 `LSV` Tafel 拟合 R² 自动验证（R² < 0.99 时在质量报告中警告）
- 支持 `CV` 峰检测、`ΔEp` 计算和电荷积分
- 支持 `EIS` 的 `Nyquist` / `Bode` 绘图、六种等效电路拟合、频段选择、残差与参数区间，以及独立 KK 一致性检查
- 支持 `ECSA` 的 `Cdl` / `ECSA` / `RF` 计算，内置材料比电容 Cs 预设（Pt、Carbon、IrO₂、RuO₂ 等）
- 支持联用产品定量表计算 `COUPLED/FE` 指标，包括法拉第效率、摩尔选择性和 FE 选择性
- 支持参比电极预设（Ag/AgCl、SCE、Hg/HgO、Hg/Hg₂SO₄、MSE、RHE）与温度相关的能斯特换算
- 单文件失败不中断整批处理（skip-on-error），错误文件汇总至结果
- 处理与 AI 请求使用持久化后台任务，提供逐文件/阶段进度和协作式取消；中断的数据处理经预检后可恢复为新任务，AI 对话不自动重发
- UI 支持基础/高级模式切换，简化初学者操作
- 支持项目回收站/恢复/永久删除、游标分页历史、按需详情、托管文件空间统计与孤立文件清理
- 项目工作区分为结果、对比、报告；支持原参数/修改参数历史复算、精确两版本比较，以及明确范围的 HTML/Markdown 可复现报告。新运行保存参数、输入与辅助依赖指纹；上传 ZIP 可恢复原始输入。详见[使用说明](docs/project_workspace.md)。
- 项目结果支持按样品或文件名搜索，并按类型、日期筛选全部历史；项目颜色可选色块或自定义。可关联常用参数模板，处理新数据前预览差异并明确应用，保留当前已选数据与辅助文件。
- 支持项目结果 ZIP 一键导出（`GET /api/v1/projects/{id}/export-zip`）
- 支持本地 HTTP 服务和 Web UI
- 支持可选的 LLM / Agent 分析链路
- 助手提供可预览的参数、比较、复算和报告操作卡；LSV 参数建议复用正式计算流程，显示候选拟合诊断，缺少实验条件时提示补全。
- 项目可保存独立重复实验组，输出有效 n、均值、样本标准差、单点和误差棒，保留采用版本、排除原因，支持 CSV/SVG 导出。
- 顶部任务面板统一查看处理与 AI 任务，支持状态筛选、取消、失败详情，以及返回对应结果或会话。
- 外观设置提供现代简洁、纸感编辑、柔和模块、像素复古四种界面风格，均可搭配九组预设、跟随系统或自选配色；分别记住颜色，旧设置自动迁移。字号、密度和背景网格独立设置，助手与图表预览同步配色，科学图表导出保留白底。详见[外观说明](docs/appearance.md)。

## 快速开始

### Windows 双击方式

当前桌面发布目标为 Windows 10 22H2 / Windows 11 **x64**，要求 WebView2 Runtime **120+**。安装版内置 Python 和计算依赖；ARM、32 位 Windows、macOS/Linux 客户端尚未正式支持。完整条件、环境自检和三种下载方式见[客户端说明](docs/desktop_client.md)；独立系统验收进度见[验收矩阵](docs/windows_acceptance_7.0.1.md)。

标准安装包需要电脑已有合适的 WebView2；文件名带 `-offline` 的离线安装包包含微软运行库；便携 ZIP 需要保留整个解压目录。基础分析可离线使用，云端 AI 需要网络。通过“客户端 → 环境自检”可查看检查结果并复制诊断。

- 安装版：安装后打开“智能电化学数据处理软件”快捷方式。
- 源码版：先双击 `setup.bat` 安装依赖，再双击 `start.bat` 启动。

`start.bat` 默认打开独立桌面窗口，自动启动本地计算服务；重复启动会唤起同一数据目录的已有窗口。需要浏览器模式时运行 `start_browser.bat`，默认地址为：

- `http://127.0.0.1:8010/ui`

客户端支持托盘、任务退出保护、窗口与外观记忆、原生文件选择和另存为、检查更新。标题栏与滚动条随主题切换；“客户端 → AI 连接（MCP）”提供其他 AI 调用项目、预检、处理和报告的配置，见 [MCP 说明](docs/mcp.md)。安装版与便携版的数据位置及旧数据迁移见[客户端说明](docs/desktop_client.md)。

### 第一次处理

1. 在“数据处理”点击“选择数据”，选 TXT/CSV 文件或文件夹，核对清单中的类型与勾选项。
2. 按需关联项目、应用参数模板；确认数据列、单位、电极面积和电位基准符合实验条件。
3. 点击“预检”，检查识别结果、参数和辅助文件配对；通过后点击“运行处理”。
4. 在“处理结果”复核指标与质量摘要；进入项目的“结果／对比／报告”继续归档、复算和导出。

首次可下载上面的合成 CV 示例并保存为 `CV_demo.csv`。它仅用于操作演示，参数和预期输出见[使用说明](src/electrochem_v6/ui/static/help_manual.zh.md)，[数据生成说明](docs/demo_data.md)列出合成公式和已验证输出；不能作为真实实验结果。

### 命令行方式

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run_v6.py --port 8010
```

## 启动命令

最常用：

```powershell
python run_v6.py --port 8010
```

其他命令：

```powershell
python run_v6.py check
python run_v6.py smoke --port 8011
python run_v6.py stress --port 8012
python run_v6.py version
```

## 使用入口

- UI：`http://127.0.0.1:8010/ui`
- 健康检查：`http://127.0.0.1:8010/health`
- API 示例：`http://127.0.0.1:8010/api/v1/projects`

## 支持的数据类型

### 输入文件兼容范围

当前直接读取的是导出的数值文本表，支持制表符、逗号、分号或空白分隔，并可按处理方式配置数据列、单位及 EIS 虚部约定。厂商专有二进制项目文件需要先从工作站软件导出为文本表。本仓库的固定夹具验证通用文本布局，不等同于 CH Instruments、Gamry、Autolab、BioLogic 等厂商格式认证。详见 [`docs/input_format_compatibility.md`](docs/input_format_compatibility.md)。

### `LSV`

- 目标电流点插值
- `Tafel` 拟合
- `iR` 补偿：支持手动 Rs、同目录/根目录回退/递归/指定文件 EIS 配对，并在预检和报告中记录来源
- 过电位计算
- `Onset` / `Halfwave`
- 质量检测开关与阈值可调

### `CV`

- 曲线绘制
- 峰检测（可选）
- `ΔEp` 峰电位差计算（需启用峰检测）
- 电荷积分（`Q = ∫|I|dt`，需要填写实验扫描速率；缺少扫描速率时不报告电量）
- 质量检测开关与阈值可调

### `EIS`

- `Nyquist` 图
- `Bode` 图（幅值+相位）
- **六种等效电路**：单时间常数 RC/CPE、含半无限 Warburg 扩散的 RC/CPE、双时间常数 RC/CPE；双支路按时间常数由快到慢排列
- 按 Hz 选择闭区间，支持均匀或模值权重；保存数值收敛、R²、RMSE、局部近似 95% 参数区间和可辨识性提示
- 独立 Lin-KK 一致性诊断；数值门槛与经验诊断不等于电路的物理正确性，无法估计的参数区间会明确标记
- 保存 Nyquist/Bode 拟合叠图、残差图、逐点 CSV 和完整诊断 JSON；历史复算和报告保留模型、频段、权重与诊断。详见 [EIS 拟合说明](docs/eis_fitting.md)

### `ECSA`

- `ΔJ-v` 拟合
- `Cdl`
- `ECSA`
- `RF`
- 内置材料 Cs 预设，并在结果中明确记录 Cs、几何面积、公式及材料/电解液相关性限制

### `COUPLED / FE`

- 可从已定量产品表直接计算法拉第效率（Faradaic efficiency）
- 可从一维信号原始峰自动定位、内标校正并定量产物，再计算 FE
- 计算同一样品内的摩尔选择性和 FE 选择性
- 支持 `CSV` / `TSV` / `TXT` / `XLSX` / `XLS` 产品表
- 结果写入 `coupled_results.csv`，并同步进入统一的 `processing_results.csv`

产品定量表至少需要包含以下信息，列名可使用英文别名：

```csv
sample,product,product_moles,n,charge
sample-a,H2,0.000002,2,1.0
sample-a,CO,0.000001,2,1.0
```

其中 `product_moles` 为产物物质的量（mol），`n` 为该产物对应电子转移数，`charge` 为总电荷量（C）。

产品表可以在中性列名中显式标注单位，例如 `Product Moles (mmol)`、`Charge (mC)`、`Current (mA)` 和 `Time (min)`；读取时统一换算为 mol、C、A 和 s。无单位列沿用上述默认单位。未知单位、相互冲突的单位声明或多个竞争列会拒绝导入。旧版 `.xls` 由随依赖安装的 xlrd 读取。

ECSA 至少需要两个有效的不同扫速；同一扫速的重复实验不能单独用于求斜率。最后 N 圈平均按完整正反扫配对计算。CV 分圈绘图支持窗口中间起扫，末尾不完整圈会提示并保留在总曲线中。

峰分析模式使用一个测量表和一个方法 JSON。测量表关联样品、信号文件和电荷量；方法文件定义内标、产物峰预期位置、定量核数、电子转移数及搜索/定量窗口。自动寻峰、内标偏移校正和约束伪 Voigt 拟合均可独立开关。批次会使用固定的相对定量窗口，并输出 `fe_peak_diagnostics.csv` 与 `fe_peak_results.json` 供复核。

内置方法文件仅为结构模板。`electron_count`、`nuclei_count`、内标浓度/体积、响应因子及峰窗口必须按实际反应和经过验证的分析方法填写。

## 质量检测

当前质量检测覆盖 `LSV`、`CV` 和峰分析 FE，处理完成后会生成质量摘要，并在有需要时输出质量报告。

目前支持：

- `LSV`：启用/禁用质量检测，调节最少点数、异常值比例、扫描范围、噪声、跳变比例、局部波动阈值
- `CV`：启用/禁用质量检测，调节最少点数和循环闭合容差
- `COUPLED/FE 峰分析`：检查检出/定量 SNR、候选峰歧义、拟合 R²、参考峰偏移及总 FE 是否超过 100%

相关实现位置：

- `src/electrochem_v6/core/processing_quality.py`
- `src/electrochem_v6/core/processing_lsv.py`
- `src/electrochem_v6/core/processing_cv.py`

## 输出结果

处理后通常会生成：

- 各类型结果图
- `LSV_results.csv`
- `ECSA_results.csv`
- `coupled_results.csv`
- `processing_results.csv`
- `quality_report.json`
- `latest_quality_report.json`
- 历史记录与项目记录

具体输出取决于启用的数据类型和参数配置。

## 常见问题

### 端口被占用

换一个端口启动：

```powershell
python run_v6.py --port 8011
```

### 没有虚拟环境

先执行：

```powershell
setup.bat
```

### 日志和数据保存在哪里

默认路径为 `~/.electrochem/v6/`，可通过环境变量自定义。

## 环境变量参考

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `ELECTROCHEM_V6_DATA_DIR` | 统一数据根目录（设置后其余路径跟随） | `~/.electrochem/v6` |
| `ELECTROCHEM_V6_PORT` | HTTP 服务端口 | `8010` |
| `ELECTROCHEM_V6_LOG_FILE` | 日志文件路径 | `<data_dir>/logs/v6_server.log` |
| `ELECTROCHEM_V6_LOG_LEVEL` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` | `INFO` |
| `ELECTROCHEM_V6_PROJECTS_FILE` | 项目列表文件路径 | `<data_dir>/projects.json` |
| `ELECTROCHEM_V6_HISTORY_FILE` | 处理历史文件路径 | `<data_dir>/processing_history.json` |
| `ELECTROCHEM_V6_CONVERSATION_FILE` | 对话历史文件路径 | `<data_dir>/conversation_history.json` |
| `ELECTROCHEM_V6_TEMPLATE_FILE` | 处理模板文件路径 | `<data_dir>/process_templates.json` |
| `ELECTROCHEM_V6_QUALITY_REPORT_FILE` | 质量报告文件路径 | `latest_quality_report.json` |
| `ELECTROCHEM_V6_LLM_CONFIG_FILE` | LLM 配置文件路径 | `~/.electrochem/llm_config.json` |
| `OPENAI_API_KEY` | OpenAI API 密钥（优先于配置文件） | — |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — |
| `QWEN_API_KEY` | Qwen API 密钥 | — |
| `KIMI_API_KEY` | Kimi API 密钥 | — |

> **安全说明**：服务仅监听 `127.0.0.1`（localhost），不对外网暴露，无需 CORS 或身份认证。

项目、历史、会话和处理模板统一保存在 `<data_dir>/electrochem_v6.db`。旧版 JSON 文件仅在首次启动时进行一次原子导入；导入校验失败时不会写入完成标记，下次启动会继续重试。

### 数据库维护

```powershell
# 检查完整性、Schema、记录数量和失联项目引用
python run_v6.py db-check

# 创建经过完整性校验的滚动备份
python run_v6.py db-backup

# 预览可能由测试生成的项目，不修改数据
python run_v6.py db-cleanup-preview

# 恢复前会先备份当前数据库；必须显式确认
python run_v6.py db-restore "备份文件.db" --yes
```

数据库每 24 小时最多自动备份一次，默认保留最近 5 份。备份位于 `<data_dir>/backups/`。

## 故障排查

### Unicode / 编码错误

在 PowerShell 或 CI 中出现中文乱码时，设置：

```powershell
$env:PYTHONUTF8 = "1"
```

或在 CMD 中：

```cmd
set PYTHONUTF8=1
```

### 中文字体缺失（图表显示方块）

系统需安装中文字体（SimHei / Microsoft YaHei / SimSun 之一）。  
也可通过处理参数的 `font` 字段指定可用字体名称。

### matplotlib 后端报错

在无图形界面环境（CI / Docker）中，需在导入 matplotlib 前设置：

```python
import matplotlib
matplotlib.use("Agg")
```

### 数据文件读取失败

- 检查文件编码：支持 UTF-8、GBK、GB2312、ASCII、Latin-1
- 检查 `start_line` 参数是否跳过了表头行
- 确认数据列之间以制表符或逗号分隔

### 调试模式

启用详细日志：

```powershell
$env:ELECTROCHEM_V6_LOG_LEVEL = "DEBUG"
python run_v6.py
```

## 项目结构

### 运行入口

- `run_v6.py`：命令行入口
- `setup.bat`：创建虚拟环境并安装依赖
- `start.bat`：启动本地服务和 UI

### 核心模块

- `src/electrochem_v6/core/processing_core_v6.py`：共享日志、绘图、异常与处理工具
- `src/electrochem_v6/core/processing_scan.py`：目录扫描、文件匹配与数据起始行识别
- `src/electrochem_v6/core/processing_registry.py`：处理模块与参数 Schema 的单一定义来源
- `src/electrochem_v6/core/processing_module_runtime.py`：处理模块注册表与运行契约
- `src/electrochem_v6/core/processing_module_orchestrator.py`：正式模块化批处理编排
- `src/electrochem_v6/core/processing_quality.py`：质量检查与质量报告
- `src/electrochem_v6/core/processing_lsv.py`：`LSV` 处理与 `IR/Tafel`
- `src/electrochem_v6/core/processing_cv.py`：`CV` 处理
- `src/electrochem_v6/core/processing_eis.py`：`EIS` 处理
- `src/electrochem_v6/core/processing_ecsa.py`：`ECSA` 处理与样品匹配辅助函数
- `src/electrochem_v6/core/processing_coupled*.py`：联用产品定量、法拉第效率与选择性计算
- `src/electrochem_v6/core/processing_result_*.py`：统一指标结果模型、汇总与导出
- `src/electrochem_v6/core/processing_metric_registry.py`：指标定义与别名注册

### 其他模块

- `src/electrochem_v6/server/`：HTTP 服务与路由
- `src/electrochem_v6/store/`：项目、历史、模板、本地持久化
- `src/electrochem_v6/ui/`：本地 Web UI
- `src/electrochem_v6/agent/`：Agent 工具链
- `src/electrochem_v6/llm/`：LLM 客户端与配置

## 开发与测试

安装开发依赖：

```powershell
pip install -r requirements-dev.txt
```

常用验证：

```powershell
python run_v6.py check
python run_v6.py smoke --port 8011
python -m pytest -q
python -m pytest -q tests/test_v6_numerical_reference.py
```

版本化电化学数值基准位于 `tests/reference_data/`。修改计算公式、单位换算或拟合方法时，
必须同时运行数值基准测试；预期值应根据公式独立推导，不能由被测实现自动生成。

## 打包与发布

打包相关文件位于：

- `packaging/`

发布前建议检查：

- `PUBLISH_CHECKLIST.md`
- `CHANGELOG.md`
- `packaging/README.md`

## License

本项目采用 `MIT` 许可证，详见 `LICENSE`。

## 路线建议

后续较值得继续优化的方向：

- 扩展有限长度扩散、感抗及适用于特定体系的 EIS 模型比较
- 为 README 补使用截图或流程图
- 实测 `PyInstaller` 打包链路
- `CV` 多圈自动分段与循环伏安参数提取
- 前端结果页展示跳过错误文件的详细列表

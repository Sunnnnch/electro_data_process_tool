# ElectroChem V6

面向电化学实验数据的本地处理与分析工具，支持 `LSV`、`CV`、`EIS`、`ECSA` 批量处理、本地 Web UI、项目/历史管理，以及可选的 AI 辅助分析。

## 项目简介

`ElectroChem V6` 的目标是把常见电化学数据处理流程收敛到一个统一工作台中，减少手工整理、重复导出和脚本碎片化问题。

适用场景：

- 批量处理同一批实验样品
- 统一输出 `LSV` / `CV` / `EIS` / `ECSA` 结果文件
- 保留项目、历史和质量报告，方便复核
- 通过本地 UI 降低使用门槛

## 核心功能

- 支持 `LSV` / `CV` / `EIS` / `ECSA` 多类型数据处理
- 支持按文件名前缀、包含、正则进行批量匹配
- 支持 `LSV` 的目标电流、电位换算、`iR` 补偿、`Tafel`、`Onset`、`Halfwave`
- 支持 `CV` 峰检测
- 支持 `EIS` 的 `Nyquist` / `Bode` 绘图
- 支持 `ECSA` 的 `Cdl` / `ECSA` / `RF` 计算
- 支持项目管理、历史记录、质量摘要和质量报告
- 支持本地 HTTP 服务和 Web UI
- 支持可选的 LLM / Agent 分析链路

## 快速开始

### Windows 双击方式

1. 双击 `setup.bat`
2. 安装完成后双击 `start.bat`

默认打开：

- `http://127.0.0.1:8010/ui`

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

### `LSV`

- 目标电流点插值
- `Tafel` 拟合
- `iR` 补偿
- 过电位计算
- `Onset` / `Halfwave`
- 质量检测开关与阈值可调

### `CV`

- 曲线绘制
- 峰检测
- 质量检测开关与阈值可调

### `EIS`

- `Nyquist` 图
- `Bode` 图
- 历史记录与结果输出

### `ECSA`

- `ΔJ-v` 拟合
- `Cdl`
- `ECSA`
- `RF`

## 质量检测

当前质量检测以 `LSV` 和 `CV` 为主，处理完成后会生成质量摘要，并在有需要时输出质量报告。

目前支持：

- `LSV`：启用/禁用质量检测，调节最少点数、异常值比例、扫描范围、噪声、跳变比例、局部波动阈值
- `CV`：启用/禁用质量检测，调节最少点数和循环闭合容差

相关实现位置：

- `src/electrochem_v6/core/processing_quality.py`
- `src/electrochem_v6/core/processing_lsv.py`
- `src/electrochem_v6/core/processing_cv.py`

## 输出结果

处理后通常会生成：

- 各类型结果图
- `LSV_results.csv`
- `ECSA_results.csv`
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

可用环境变量控制：

- `ELECTROCHEM_V6_DATA_DIR`
- `ELECTROCHEM_V6_LOG_FILE`
- `ELECTROCHEM_V6_PORT`

## 项目结构

### 运行入口

- `run_v6.py`：命令行入口
- `setup.bat`：创建虚拟环境并安装依赖
- `start.bat`：启动本地服务和 UI

### 核心模块

- `src/electrochem_v6/core/processing_core_v6.py`：兼容入口、共享工具、统一导出
- `src/electrochem_v6/core/processing_pipeline.py`：批处理编排与目录扫描
- `src/electrochem_v6/core/processing_quality.py`：质量检查与质量报告
- `src/electrochem_v6/core/processing_lsv.py`：`LSV` 处理与 `IR/Tafel`
- `src/electrochem_v6/core/processing_cv.py`：`CV` 处理
- `src/electrochem_v6/core/processing_eis.py`：`EIS` 处理
- `src/electrochem_v6/core/processing_ecsa.py`：`ECSA` 处理与样品匹配辅助函数

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
```

当前发布版验证状态：

- `41 passed, 1 skipped`
- `python run_v6.py check` 通过
- `python run_v6.py smoke --port 8011` 通过

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

- 为 `EIS` / `ECSA` 补更细的质量检测
- 为 README 补使用截图或流程图
- 实测 `PyInstaller` 打包链路
- 增加 `LICENSE`

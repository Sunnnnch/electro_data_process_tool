# ElectroChem V6

电化学数据处理与智能分析工具，支持 `LSV`、`CV`、`EIS`、`ECSA` 数据处理，以及本地 Web UI 与 AI 分析。

## 安装

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
```

## 启动

### 最常用

```powershell
python run_v6.py --port 8010
```

### 其他命令

```powershell
python run_v6.py check
python run_v6.py smoke --port 8011
python run_v6.py stress --port 8012
python run_v6.py version
```

## 使用入口

- UI：`http://127.0.0.1:8010/ui`
- 健康检查：`http://127.0.0.1:8010/health`
- API：`http://127.0.0.1:8010/api/v1/projects`

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

### 日志和数据保存在哪

可用环境变量控制：

- `ELECTROCHEM_V6_DATA_DIR`
- `ELECTROCHEM_V6_LOG_FILE`
- `ELECTROCHEM_V6_PORT`

## 开发

安装开发依赖：

```powershell
pip install -r requirements-dev.txt
```

常用测试：

```powershell
python run_v6.py check
python run_v6.py smoke --port 8011
python -m pytest -q tests/test_v6_server.py
```

### Core 结构

- `src/electrochem_v6/core/processing_core_v6.py`：兼容入口、共享工具、统一导出
- `src/electrochem_v6/core/processing_pipeline.py`：批处理编排与目录扫描
- `src/electrochem_v6/core/processing_quality.py`：质量检查与质量报告
- `src/electrochem_v6/core/processing_lsv.py`：`LSV` 处理与 `IR/Tafel` 相关逻辑
- `src/electrochem_v6/core/processing_cv.py`：`CV` 处理
- `src/electrochem_v6/core/processing_eis.py`：`EIS` 处理
- `src/electrochem_v6/core/processing_ecsa.py`：`ECSA` 处理与样品匹配辅助函数

建议新增处理逻辑时优先放到对应领域模块，不再继续堆叠到 `processing_core_v6.py`。

## 发布

发布前建议检查：

- `PUBLISH_CHECKLIST.md`
- `CHANGELOG.md`

当前版本已通过：

- `python run_v6.py check`
- `python run_v6.py smoke --port 8011`
- `tests/test_v6_server.py`
- `tests/test_v6_e2e_real_data.py`
- `tests/test_v6_stress.py`

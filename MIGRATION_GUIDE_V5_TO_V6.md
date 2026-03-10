# v5 -> v6 迁移说明（无激活机制）

本文档用于当前仓库从 `v5.0.1` 迁移到 `v6_refactor_no_license` 的实施与验收。

## 1. 迁移目标

1. 去除激活码/试用期机制，默认可用。
2. 从单文件重入口逐步迁移到 API-first 分层结构。
3. 保持核心处理能力（LSV/CV/EIS/ECSA）与已有数据结构兼容。
4. 降低回归风险：保留 v5 可运行路径，v6 独立目录演进。

## 2. 版本与目录策略

1. v5 保留：`电化学处理_更新_v5.0.1.py`、`cli_process.py`、根目录历史数据文件。
2. v6 独立：`v6_refactor_no_license/`。
3. 运行入口：
   - `python v6_refactor_no_license/run_v6.py check`
   - `python v6_refactor_no_license/run_v6.py smoke`
   - `python v6_refactor_no_license/run_v6.py stress`
   - `python v6_refactor_no_license/run_v6.py server --port 8010`

## 3. 模块迁移映射

详细映射见 [MIGRATION_MAP.md](D:\Cursor_agent\elec_tool\v6_refactor_no_license\MIGRATION_MAP.md)。

关键路径：

1. 服务端：`app/services/server_manager.py` -> `src/electrochem_v6/server/*`
2. 处理服务：`processing_core.py` -> `src/electrochem_v6/core/process_service.py`（桥接）
3. 数据存储：
   - `project_manager.py` -> `src/electrochem_v6/store/projects.py`
   - `history_manager.py` -> `src/electrochem_v6/store/history.py`
   - `conversation_manager.py` -> `src/electrochem_v6/store/conversations.py`
4. AI 与 LLM：
   - `app/agent/*` -> `src/electrochem_v6/agent/*`
   - `app/llm/*` -> `src/electrochem_v6/llm/*`

## 4. 兼容性与行为变化

### 4.1 License 机制

1. v6 不再依赖激活/试用逻辑。
2. 校验策略由“先授权后运行”改为“默认允许运行”。

### 4.2 配置文件读取优先级（已统一）

优先级：`环境变量 > 用户目录 > 项目默认`。

主要环境变量：

1. `ELECTROCHEM_V6_PROJECTS_FILE`
2. `ELECTROCHEM_V6_HISTORY_FILE`
3. `ELECTROCHEM_V6_CONVERSATION_FILE`
4. `ELECTROCHEM_V6_TEMPLATE_FILE`
5. `ELECTROCHEM_V6_QUALITY_REPORT_FILE`
6. `ELECTROCHEM_V6_LLM_CONFIG_FILE`
7. `ELECTROCHEM_LLM_CONFIG_FILE`（LLM 兼容兜底）

### 4.3 summary 输出规范

1. `summary.json` 写入统一版本字段：`version=APP_VERSION`。
2. 兼容保留旧字段：`pipeline_version`。
3. 增加兼容结构：`summary_schema_version`、`history`、标准化 `processing.output_files`。

### 4.4 日志与脱敏策略

1. 新增结构化日志策略模块：`core/logging_policy.py`。
2. 默认仅记录低风险摘要（keys/status/message）。
3. `ELECTROCHEM_V6_LOG_INCLUDE_PAYLOAD=1` 时记录脱敏后的 payload。
4. `api_key/token/authorization/password` 与 bearer/sk 模式均会脱敏。

## 5. 新增验证能力

### 5.1 基线回归

命令：

```powershell
python v6_refactor_no_license/scripts/baseline_regression.py
```

输出：

1. `v6_refactor_no_license/reports/baseline_regression_latest.json`
2. 时间戳报告副本 `baseline_regression_*.json`

### 5.2 并发上传 + 长会话压力 smoke

命令：

```powershell
python v6_refactor_no_license/run_v6.py stress --upload-workers 4 --upload-requests 8 --conversation-turns 40
```

或：

```powershell
python v6_refactor_no_license/scripts/stress_smoke.py
```

输出：

1. `v6_refactor_no_license/reports/stress_smoke_latest.json`
2. 时间戳报告副本 `stress_smoke_*.json`

## 6. 迁移实施步骤（建议）

1. 锁定 v5 基线：
   - 运行 `baseline_regression.py` 并保存报告。
2. 切换到 v6 服务：
   - 启动 `run_v6.py server`，验证 `/health`、`/ui`、`/api/v1/*`。
3. 迁移配置文件路径：
   - 先设置环境变量覆盖，避免污染默认项目目录。
4. 联调 UI/接口：
   - 专业模式参数、多数据类型选择、模板增删改查、历史统计面板。
5. 压测：
   - 运行 `run_v6.py stress`，确认无 5xx/无崩溃。
6. 灰度发布：
   - 小范围用户验证后再替换默认启动入口。

## 7. 回滚方案

1. v6 与 v5 并存，不直接覆盖 v5 文件。
2. 若 v6 不满足上线条件，恢复使用：
   - `python 电化学处理_更新_v5.0.1.py`
   - `python cli_process.py ...`
3. 回滚时保留 v6 报告文件作为问题定位依据。

## 8. 上线前检查清单

1. `python -m pytest -q` 通过。
2. `python v6_refactor_no_license/run_v6.py check` 通过。
3. `python v6_refactor_no_license/run_v6.py smoke --port 8011` 通过。
4. `python v6_refactor_no_license/run_v6.py stress` 通过。
5. 日志文件确认无明文密钥泄露。


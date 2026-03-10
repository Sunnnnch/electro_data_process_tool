# 模块迁移映射（v5 -> v6）

## 入口层

1. `电化学处理_更新_v5.0.1.py` -> `src/electrochem_v6/app.py`（逐步拆分）
2. `cli_process.py` -> `src/electrochem_v6/cli.py`
3. `app/services/server_manager.py` -> `src/electrochem_v6/server/*`

## 核心处理

1. `processing_core.py` -> `src/electrochem_v6/core/*`（分阶段迁移）
2. `app/controllers/data_processing.py` -> `src/electrochem_v6/core/pipeline_service.py`

## 数据与会话

1. `project_manager.py` -> `src/electrochem_v6/store/projects.py`
2. `history_manager.py` -> `src/electrochem_v6/store/history.py`
3. `conversation_manager.py` -> `src/electrochem_v6/store/conversations.py`

## AI 与配置

1. `app/llm/*` -> `src/electrochem_v6/llm/*`
2. `app/agent/*` -> `src/electrochem_v6/agent/*`
3. `app/config/*` -> `src/electrochem_v6/config/*`

## 授权（移除项）

1. `app/services/license_manager.py` -> 删除（v6 不保留）
2. `app/controllers/license_controller.py` -> 删除（v6 不保留）
3. 相关 UI 激活页与校验流程 -> 删除并改为默认可用

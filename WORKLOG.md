# v6 重构工作日志

## 2026-02-27 17:18

1. 初始化重构目录 `v6_refactor_no_license/`。
2. 建立中断恢复文档：
   - `README.md`
   - `TODO.md`
   - `MIGRATION_MAP.md`
3. 建立第一版代码骨架：
   - `run_v6.py`
   - `src/electrochem_v6/` 基础模块
   - `core/pipeline_adapter.py`（桥接 v5 处理核心）
4. 当前验证目标：
   - `python v6_refactor_no_license/run_v6.py check`

## 2026-02-27 17:20

1. 执行 `python v6_refactor_no_license/run_v6.py check`，结果 `ok=true`。
2. 验证 bridge：可找到 `processing_core.run_pipeline`，说明 v6 骨架已可复用 v5 核心。
3. 下一步优先级：
   - 去激活链路（License 相关依赖清理）
   - server 路由拆分（先 health/projects/history）

## 2026-02-27 17:23

1. 新增 server 拆分占位模块：
   - `routes_health.py`
   - `routes_projects.py`
   - `routes_history.py`
2. `app.run_check()` 增加 `health_route` 自检输出。
3. `TODO.md` 中 server 路由拆分状态更新为进行中（`[~]`）。

## 2026-02-27 17:30

1. 新增 v6 实际可运行服务端：`server/http_server.py`（ThreadingHTTPServer）。
2. 新增 store 适配层：
   - `store/projects.py`
   - `store/history.py`
   - `store/conversations.py`
3. 新增 LLM 与 Agent 适配层：
   - `llm/config_adapter.py`
   - `agent/service.py`
4. `run_v6.py` 新增子命令：
   - `server`
   - `smoke`
5. 新增 `smoke.py`，用于自动化最小接口自测。
6. `app.run_check()` 增加“无 license import 扫描”。

## 2026-02-27 17:36

1. 修复 v6 项目创建兼容性：绕过 v5 `project_manager` 的终端编码副作用，改为适配层安全写入。
2. 验证 `python v6_refactor_no_license/run_v6.py smoke --port 8011` 通过。
3. 验证 `python v6_refactor_no_license/run_v6.py check` 通过（含 no-license 扫描）。
4. 全仓回归：`python -m pytest -q` -> `10 passed`。

## 2026-02-27 17:42

1. 新增 `core/process_service.py`，提供：
   - `/api/v1/process`（JSON folder_path 处理）
   - `/api/v1/quality-report/latest` 数据读取
2. `server/http_server.py` 新增上述路由，并为 `/api/v1/process-zip` 提供 alpha 阶段提示响应。
3. `smoke.py` 增加 `quality-report/latest` 检查（允许 200/404）。

## 2026-02-27 17:46

1. 重新执行 `check/smoke/compileall` 全部通过。
2. 更新 `TODO.md`：`health/projects/history/agent/llm/config` 路由拆分项标记为已完成。
3. 目前主要剩余项：
   - ZIP 上传处理与安全边界
   - v6 单元测试
   - UI 静态资源迁移与美化

## 2026-02-27 17:52

1. 新增 `/api/v1/process-zip`（multipart）处理链路。
2. 加入 ZIP 安全边界：
   - 上传体积限制
   - 文件体积限制
   - 条目数限制
   - 解压总量限制
   - 路径穿越防护
3. `smoke.py` 增加 `process` 与 `process-zip` 路由可达性检查。
4. `TODO.md` 中“ZIP 安全边界”标记为已完成。

## 2026-02-27 18:02

1. 完成 `http_server.py` 精简：仅保留 server host + handler 外壳。
2. 新增路由分发模块：
   - `server/routes_get.py`
   - `server/routes_post.py`
   - `server/request_utils.py`
3. 新增静态 UI 骨架：
   - `ui/static/index.html`
   - `ui/static/styles.css`
   - `ui/static/app.js`
   并支持 `/ui` 与 `/ui/static/*` 访问。
4. 新增 v6 服务端测试：`v6_refactor_no_license/tests/test_v6_server.py`。
5. 验证结果：
   - `pytest v6_refactor_no_license/tests/test_v6_server.py` -> 3 passed
   - `python -m pytest -q` -> 13 passed

## 2026-02-27 18:12

1. 升级 `/api/v1/agent/messages`：
   - 支持 JSON 与 multipart/form-data
   - multipart 支持可选 ZIP 文件，自动处理后再喂给 Agent
   - 响应中包含 `processing_result` 与 `attachments`
2. 新增并验证会话混合流测试：
   - `test_v6_agent_message_multipart_without_file`
   - `test_v6_agent_message_multipart_with_zip`
3. `/ui` 页面升级为可交互工作台：
   - 会话列表加载
   - 会话详情展示
   - 消息发送（JSON / multipart）
4. 验证结果：
   - `pytest v6_refactor_no_license/tests/test_v6_server.py` -> 5 passed
   - `python -m pytest -q` -> 15 passed

## 2026-02-27 18:18

1. 完成 `agent/messages` 混合输入升级：
   - JSON 模式：支持附带 `processing_result`、`attachments`
   - multipart 模式：支持可选 ZIP，自动处理后注入 Agent 上下文
2. `/ui` 页面升级为可交互工作台：
   - 会话列表加载
   - 会话详情展示
   - 文本发送与 ZIP 附件发送
3. `smoke.py` 增加 `/ui` 可达性检查。
4. 验证结果：
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` 通过
   - `pytest v6_refactor_no_license/tests/test_v6_server.py` -> 5 passed
   - `python -m pytest -q` -> 15 passed

## 2026-02-27 18:24

1. `/ui` 升级为第一版工作台：
   - 会话删除按钮
   - 处理参数面板（调用 `/api/v1/process`）
   - 统计卡片（调用 `/api/v1/stats`）
   - 历史列表（调用 `/api/v1/history`）
2. 调整样式与移动端布局，保证新增模块在窄屏可用。
3. 验证结果：
   - `pytest v6_refactor_no_license/tests/test_v6_server.py` -> 5 passed
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true
   - `python -m pytest -q` -> 15 passed

## 2026-02-27 18:28

1. Rebuilt `ui/static/index.html` process panel with dual modes:
   - Quick mode (minimal inputs)
   - Professional mode (advanced grouped parameters)
2. Rebuilt `ui/static/app.js`:
   - Added mode toggle and per-data-type panel switching (LSV/CV/EIS/ECSA)
   - Added folder picker integration with `POST /api/v1/system/select-folder`
   - Added payload builder for advanced `params` and compatibility fields (`target_current`, `tafel_range`)
3. Rebuilt `ui/static/styles.css` to support new professional layout and responsive behavior.
4. Added test `test_v6_system_select_folder` in `tests/test_v6_server.py` (monkeypatch dialog function).
5. Validation:
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` -> 6 passed
   - `python -m pytest -q` -> 16 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true

## 2026-02-27 19:01

1. UI language baseline switched to Chinese and added language selector (`zh` / `en`) with i18n key mapping.
2. Layout refactor to tab workflow:
   - Professional Mode tab
   - AI Chat Mode tab
   Default tab set to Professional Mode.
3. Home view hierarchy changed: processing workflow and status are now primary; chat moved to dedicated tab.
4. Updated static files:
   - `ui/static/index.html`
   - `ui/static/app.js`
   - `ui/static/styles.css`
5. Validation:
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` -> 6 passed
   - `python -m pytest -q` -> 16 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true

## 2026-02-27 19:19

1. UI processing panel refactor:
   - removed Quick/Basic mode
   - kept only professional parameter panel
   - replaced single `data_type` selector with multi-select checkboxes (`LSV/CV/EIS/ECSA`)
2. UX clarity improvements:
   - data-type panels now show/hide based on selected types (can show multiple together)
   - feature blocks (IR/Onset/Halfwave/CV peaks) remain enable-gated and grouped
3. Backend processing update (`core/process_service.py`):
   - added `data_types` normalization and validation
   - supports both `data_types` (new) and `data_type` (legacy)
   - builds combined gui flags for multi-type processing in one run
4. Added regression test:
   - `test_v6_process_route_accepts_data_types_list`
5. Validation:
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` -> 7 passed
   - `python -m pytest -q` -> 17 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true
6. Fix applied during validation:
   - removed BOM from `core/process_service.py` after `check` found `U+FEFF` parse error.

## 2026-02-27 19:49

1. Added process template backend store: `store/process_templates.py`
   - built-in templates (LSV/CV/EIS/ECSA)
   - user template persistence to `process_templates.json`
   - save/list/delete operations
2. Added template routes:
   - `GET /api/v1/process/templates`
   - `POST /api/v1/process/templates`
   - `POST /api/v1/process/templates/{name}/delete`
3. Updated Professional UI for template workflow:
   - template selector + load/save/delete controls
   - template state mapping for data types, values, and toggles
4. Moved result panel to stats/history column and keep it visible by default with placeholder.
5. Added tests:
   - `test_v6_process_templates_routes`
6. Validation:
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` -> 8 passed
   - `python -m pytest -q` -> 18 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true

## 2026-02-27 20:30

1. Frozen baseline acceptance checklist for v5/v6:
   - `v6_refactor_no_license/V5_V6_BASELINE_ACCEPTANCE.md`
2. Added one-click baseline regression scripts:
   - `v6_refactor_no_license/scripts/baseline_regression.py`
   - `v6_refactor_no_license/scripts/run_baseline_regression.ps1`
3. Updated `TODO.md` with baseline-checkpoint completion.
4. Validation:
   - `python v6_refactor_no_license/scripts/baseline_regression.py` -> all checks PASS
   - report generated at `v6_refactor_no_license/reports/baseline_regression_latest.json`

## 2026-02-27 21:10

1. Unified v6 version output in processing service:
   - `core/process_service.py` now injects `app_name`/`app_version` into process result payload.
2. Added v6 summary normalization and rewrite step after `run_pipeline`:
   - keep legacy `pipeline_version` if present
   - write `version=APP_VERSION`
   - add `summary_schema_version`/`data_type(s)`/`history` compatibility block
   - attach normalized `processing.output_files`
3. Added tests:
   - `tests/test_v6_process_service.py`
4. Validation:
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_process_service.py` -> 2 passed
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` -> 10 passed
   - `python -m pytest -q` -> 22 passed
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true
5. Follow-up fix:
   - Removed UTF-8 BOM from `core/process_service.py` (it broke `run_v6.py check` AST parsing).
   - Re-ran baseline regression script: all PASS.

## 2026-02-27 21:45

1. Implemented unified config/data path precedence in v6 (`env > user dir > project default`):
   - `src/electrochem_v6/config.py` now provides central resolvers for:
     - projects/history/conversations/templates/quality_report/llm_config
2. Added runtime bridge to keep legacy v5 singleton managers aligned with resolved v6 paths:
   - `src/electrochem_v6/store/legacy_runtime.py`
   - updated stores: `projects.py`, `history.py`, `conversations.py`
3. Updated template and quality-report file lookups to use centralized resolver.
4. Extended LLM config loading/saving precedence:
   - `app/llm/config.py` supports `ELECTROCHEM_V6_LLM_CONFIG_FILE` and `ELECTROCHEM_LLM_CONFIG_FILE`
   - load order: env path > user `~/.electrochem/` > project default
5. Added tests:
   - `tests/test_v6_config_precedence.py` (4 cases, includes resolver + managers + LLM config)
6. Validation:
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_config_precedence.py` -> 4 passed
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py v6_refactor_no_license/tests/test_v6_process_service.py` -> 12 passed
   - `python -m pytest -q` -> 26 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true
   - `python v6_refactor_no_license/scripts/baseline_regression.py` -> all PASS

## 2026-02-27 22:10

1. Added structured logging policy with sensitive-data masking:
   - `src/electrochem_v6/core/logging_policy.py`
   - recursive key-based masking (`api_key/token/authorization/password/...`)
   - bearer/token pattern redaction and safe payload summary mode
2. Integrated logging in server boundary:
   - `src/electrochem_v6/server/http_server.py`
   - request/response/error events for GET/POST + static responses
3. Added targeted route logging for provider config update:
   - `src/electrochem_v6/server/routes_post.py` (`/api/v1/llm/config`)
4. Added tests:
   - `tests/test_v6_logging_policy.py` (masking + summary + file-output no secret leak)
5. Validation:
   - `python -m py_compile ...` (changed files) -> pass
   - `python -m pytest -q` -> 29 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true
   - `python v6_refactor_no_license/scripts/baseline_regression.py` -> all PASS

## 2026-02-27 22:35

1. Added stress smoke module and command:
   - `src/electrochem_v6/stress.py`
   - `run_v6.py stress` (concurrent upload + long conversation)
2. Added stress runner scripts:
   - `scripts/stress_smoke.py`
   - `scripts/run_stress_smoke.ps1`
3. Added stress regression test:
   - `tests/test_v6_stress.py`
4. Added migration documentation:
   - `MIGRATION_GUIDE_V5_TO_V6.md`
5. TODO updates:
   - marked stress smoke and migration guide as completed.
6. Validation:
   - `python -m pytest -q` -> pass
   - `python v6_refactor_no_license/run_v6.py stress ...` -> pass
   - `python v6_refactor_no_license/scripts/stress_smoke.py ...` -> pass and report written

## 2026-02-27 22:50

1. Fixed stress script import/runtime robustness:
   - `scripts/stress_smoke.py` added repository root to `sys.path` to avoid `ModuleNotFoundError: app`.
   - `stress.py` switched to isolated temp data files (projects/history/conversations/templates/quality report) to reduce side effects.
2. Fixed v6 legacy runtime singleton init race:
   - `store/legacy_runtime.py` now guards manager initialization/rebinding with module-level `RLock`.
3. Re-validated:
   - `python -m pytest -q` -> 30 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true
   - `python v6_refactor_no_license/run_v6.py stress --upload-workers 8 --upload-requests 20 --conversation-turns 30` -> pass
   - `python v6_refactor_no_license/scripts/stress_smoke.py --upload-workers 4 --upload-requests 8 --conversation-turns 20` -> pass and report updated

## 2026-02-27 23:10

1. Fixed real concurrency risk in project persistence:
   - `core/process_service.py` no longer resolves projects via legacy default-path manager.
   - now uses v6-only project resolver (`get_or_create_project_id_by_name`) to avoid mixed file targets.
2. Hardened project store writes:
   - `store/projects.py` added process-level lock (`RLock`) for get/create/delete critical sections.
   - fallback write path switched to atomic file replace (`tmp + fsync + os.replace`) to prevent partial JSON writes.
   - added dedupe guard for same-name concurrent create requests.
3. Added concurrency regression test:
   - `tests/test_v6_projects_concurrency.py`
4. Validation:
   - `python -m pytest -q` -> 31 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true
   - `python v6_refactor_no_license/run_v6.py stress --upload-workers 12 --upload-requests 40 --conversation-turns 40` -> pass
   - `python v6_refactor_no_license/scripts/stress_smoke.py --upload-workers 6 --upload-requests 12 --conversation-turns 20` -> pass and report updated

## 2026-02-27 23:25

1. Added AI conversation rename capability (backend + frontend):
   - backend storage: `conversation_manager.py` adds `rename_conversation`.
   - v6 adapter: `src/electrochem_v6/store/conversations.py` + `store/__init__.py`.
   - API route: `POST /api/v1/agent/conversations/{id}/rename` in `server/routes_post.py`.
   - UI: conversation item now has Rename/Delete actions in `ui/static/app.js` and `ui/static/styles.css`.
2. Added regression test:
   - `tests/test_v6_server.py::test_v6_agent_conversation_rename`
3. Validation:
   - `python -m py_compile conversation_manager.py ...` -> pass
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` -> pass
   - `python -m pytest -q` -> 32 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true

## 2026-02-27 23:45

1. UI interaction polish completed for AI conversation panel:
   - added conversation keyword search controls in sidebar (`index.html` + `app.js` + `styles.css`).
   - added rename action and status i18n for zh/en.
2. Process/history linkage improved:
   - history list items are now clickable.
   - clicking a history item renders a structured result card in the process result panel (summary/types/output/quality).
   - result card now supports rendering extra quality fields beyond fixed totals.
3. Tests expanded for conversation workflows:
   - `tests/test_conversation_manager.py` adds rename success/empty-title cases.
   - `v6_refactor_no_license/tests/test_v6_server.py` adds keyword-filter list API case.
4. TODO consolidation:
   - marked front-end panel/layout linkage and core/server/conversation test expansion as completed.
5. Validation:
   - `python -m py_compile ...` -> pass
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py tests/test_conversation_manager.py` -> 15 passed
   - `python -m pytest -q` -> 35 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true

## 2026-02-27 23:58

1. Added LLM provider/model/API settings panel in AI tab:
   - `ui/static/index.html`: provider/model/base_url/timeout/api_key inputs + reload/save buttons.
   - `ui/static/styles.css`: new panel layout (`llm-panel`, `llm-grid`) and responsive adaptation.
2. Added frontend logic for config lifecycle:
   - `ui/static/app.js`
   - load current config from `GET /api/v1/llm/config`
   - provider switch auto-fills model/base_url/timeout and shows API-key configured hint
   - save changes via `POST /api/v1/llm/config`
3. Chat request now carries selected provider/model:
   - both JSON and multipart modes append `provider` and `model` to `/api/v1/agent/messages`.
4. Validation:
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` -> 12 passed
   - `python -m pytest -q` -> 35 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true

## 2026-02-28 00:08

1. Reworked AI settings UX from inline block to dedicated panel:
   - added `AI设置` button in chat header.
   - moved model/API controls into side settings panel (`ai-settings-panel`).
2. Added prompt management in AI settings:
   - prompt attach toggle, template selector, prefix editor.
   - local save/apply flow (stored in browser localStorage).
   - prompt is prepended to user message when enabled.
3. Chat request payload enhancement:
   - selected `provider/model` now sent in both multipart and JSON paths.
4. UI updates:
   - new panel sections/styles for cleaner layout and responsive behavior.
5. Validation:
   - `python -m pytest -q v6_refactor_no_license/tests/test_v6_server.py` -> 12 passed
   - `python -m pytest -q` -> 35 passed
   - `python v6_refactor_no_license/run_v6.py check` -> ok=true
   - `python v6_refactor_no_license/run_v6.py smoke --port 8011` -> ok=true

## 2026-02-28 19:40

1. Added release closing documentation under `reports/`:
   - `RELEASE_CHECKLIST_V6_0_1.md`
   - `CHANGELOG_V6_0_1.md`
   - `PACKAGING_PLAN_V6_0_1.md`
2. Documents focus on:
   - pre-release validation scope
   - v6.0.1 user-facing change summary
   - packaging strategy recommendation (`local service + desktop shell`)
3. No business logic changes in this step.

## 2026-02-28 21:11

1. Added initial packaging scaffold under packaging/:
   - electrochem_v6_launcher.py
   - electrochem_v6.spec
   - equirements-pack.txt
   - uild_onedir.ps1
   - uild_installer.ps1
   - installer.iss
   - README.md
   - ssets/app_icon.ico
2. Packaging approach for this stage:
   - dedicated packaging virtual environment (.venv-pack)
   - PyInstaller onedir
   - lightweight desktop launcher starts local service and opens browser UI
   - Inno Setup wraps the tested onedir output into an installer
3. Validation:
   - python -m py_compile packaging/electrochem_v6_launcher.py packaging/electrochem_v6.spec -> passed
   - PowerShell parser check for uild_onedir.ps1 and uild_installer.ps1 -> passed

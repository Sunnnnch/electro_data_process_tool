# v6 重构 TODO（无激活机制）

> 状态约定：`[ ]` 未开始，`[~]` 进行中，`[x]` 已完成  
> 当前基线：`v5.0.1`（git: `be7acfc`，2026-02-27）

## A. 启动与保护

- [x] 新建独立重构目录 `v6_refactor_no_license/`
- [x] 建立中断恢复文件：`TODO.md`、`WORKLOG.md`、`MIGRATION_MAP.md`
- [x] Freeze v5 baseline acceptance checklist (CLI/API/GUI quick regression)
- [x] 建立 v6 阶段性验收脚本（最小 smoke test）

## B. 架构骨架（API-first）

- [x] 建立 `src/electrochem_v6/` 包结构
- [x] 建立 `run_v6.py` 统一入口
- [x] 建立 `config.py`（版本与运行开关）
- [x] 建立 `core/pipeline_adapter.py`（桥接 v5 处理核心）
- [x] 建立 `server` 路由分层（health/projects/history/agent/config）
- [x] 建立 `ui` 静态资源目录（预留）

## C. 去激活机制（明确范围）

- [x] 删除 v6 中所有 LicenseManager/LicenseController 依赖
- [x] 去掉“试用期/激活页/激活校验”入口逻辑
- [x] 将权限校验改为“默认允许”
- [x] 清理相关 UI 文案与配置字段
- [x] 加入回归检查：无激活文件也可正常运行 v6

## D. 服务端拆分

- [x] 从大文件拆分路由：`/health`
- [x] 拆分路由：`/api/v1/projects*`
- [x] 拆分路由：`/api/v1/history`、`/api/v1/stats`
- [x] 拆分路由：`/api/v1/agent/*`
- [x] 拆分路由：`/api/v1/llm/config`、`/api/v1/quality-report/latest`
- [x] 保留 ZIP 安全边界与请求体大小限制

## E. 前端与交互（后续）

- [x] 把内嵌 HTML/CSS/JS 从 Python 字符串抽离
- [x] 建立统一视觉变量（字体/色板/间距/组件）
- [x] 新版会话面板与结果卡片布局
- [x] 移动端基础响应式
- [x] 处理面板与统计历史面板联调

## F. 一致性与技术债

- [x] 统一版本号来源，修复 `summary.json` 历史字段差异
- [x] 统一配置读取优先级（环境变量 > 用户目录 > 项目默认）
- [x] 明确日志策略与敏感信息脱敏

## G. 测试与发布准备

- [x] 新增 v6 单元测试骨架
- [x] 迁移并扩展关键测试（core/server/conversation）
- [x] 并发上传与长会话压力 smoke test
- [x] 编写 v6 迁移说明（从 v5 到 v6）

## 中断恢复步骤

1. 先读 `WORKLOG.md` 最后一条记录。
2. 回到本文件找到第一个 `[~]` 或第一个 `[ ]` 任务。
3. 完成后更新两处：
   - 本文件状态
   - `WORKLOG.md` 追加“时间 + 修改内容 + 验证结果”

## 2026-02-27 Incremental checkpoint (v6)
- [x] Add Quick/Professional mode in `/ui` process panel.
- [x] Wire advanced parameter groups for LSV/CV/EIS/ECSA into `/api/v1/process` payload (`params`).
- [x] Add folder picker button in UI, integrated with `POST /api/v1/system/select-folder`.
- [x] Add server test for `/api/v1/system/select-folder` using monkeypatch.
- [x] Regression passed: `pytest v6_refactor_no_license/tests/test_v6_server.py` and `python -m pytest -q`.
- [x] Next: continue UX polish for professional presets and parameter templates.

## 2026-02-27 Incremental checkpoint (UI tabs)
- [x] UI default language switched to Chinese.
- [x] Added tab layout: Professional Mode / AI Chat Mode.
- [x] Professional mode is now the default landing tab.
- [x] Added i18n framework (`zh`/`en`) via language selector for later expansion.
- [x] Reworked homepage information hierarchy to emphasize processing workflow first.
- [x] Added AI conversation rename action (UI + API).
- [x] Added AI tab LLM settings panel (provider/model/base_url/api_key/timeout).

## 2026-02-27 Multi-select update
- [x] Removed basic parameter mode in processing tab.
- [x] Added multi-select data types (LSV/CV/EIS/ECSA) in professional panel.
- [x] Backend `/api/v1/process` now supports `data_types` while keeping `data_type` compatibility.
- [x] Added route test for multi-type payload.

## 2026-02-27 Template module
- [x] Added process template management API (`/api/v1/process/templates` GET/POST and delete endpoint).
- [x] Added built-in templates + user-defined template persistence.
- [x] Added template controls in Professional Mode (load/save/delete).
- [x] Added server route tests for template APIs.

## 2026-02-27 Baseline checklist freeze
- [x] Frozen v5/v6 baseline acceptance checklist document.
- [x] Added one-click baseline regression script (quick/full modes).
- [x] Added Windows PowerShell launcher for baseline regression.




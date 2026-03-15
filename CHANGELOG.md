# Changelog

## 6.0.19

### 前端

- 移除"自动识别起点"复选框（`pro-auto-detect`），自动检测数据起始行现为默认且唯一行为
- ECSA 参数面板布局优化：7 个字段从单一 3 列网格拆分为 3 列 + 2 列两组，消除"材料预设"被撑高和"Cs 单位"孤立的问题
- CSS：`.field-grid` 添加 `align-items: start`，防止子项被相邻 param-tip 纵向拉伸
- 删除 i18n 中 `auto_detect` 翻译键（中/英）

### 后端

- `process_service._build_gui_vars()` 移除无用的 `auto_detect_start` 字段
- `processing_pipeline.resolve_data_start_line()` 签名简化：`params` 改为可选参数
- `auto_detect_data_start()` 增强：BOM 标记处理、多分隔符检测（tab/comma/semicolon）、更多注释样式支持（`'`、`!`、`:`）
- Agent `tools_projects.py` 移除硬编码 `auto_detect_start: True`
- 内置模板 `process_templates.py` 移除 `pro-auto-detect` 条目

### 测试

- 修复 `test_v6_auto_detect_start.py` lint 错误（移除未使用的 `os`/`pytest` 导入，删除冗余 `sys.path` 设置）
- 修正 `test_numeric_header_different_col_count` 预期值以匹配实际检测逻辑
- `test_resolve_always_auto_detects` 适配 `resolve_data_start_line` 新签名

## 6.0.7

### 代码质量 & 安全加固

- XSS 防护：引入 DOMPurify 3.2.4，所有 AI / 服务端返回的 HTML 均经过消毒
- 路径安全：`validate_path_within` 增加 `..` / null-byte / 符号链接跳出检测
- 批处理并行度：新增 `ELECTROCHEM_V6_PARALLEL` 环境变量控制工作线程上限
- `skipped_errors` 结构化返回：批处理跳过的文件以 `{file, error}` 数组形式返回前端

### 前端

- i18n 翻译提取至独立 `i18n.js`（~280 键 × 2 语言），`app.js` 减少约 926 行
- 版本显示简化为 "V6"，页脚增加 GitHub 链接

### 文档

- 新增 `docs/openapi.yaml`：OpenAPI 3.1.0 完整规范，覆盖 31 个 API 端点
- 中英文使用手册同步更新

### CI / CD

- GitHub Actions 新增 Pyright 类型检查步骤
- 覆盖率门槛从 60% 提升至 65%

### 测试

- 新增 11 个测试文件（agent_controller / agent_service / config_adapter / history / lsv_calc / processing_ecsa / smoke / system_service / tools_catalyst / tools_data / vision_client）
- 新增约 100+ 测试用例，测试总数从 ~430 增至 ~460
- conftest.py 统一 ROOT/SRC/sys.path 管理，清理 17 个旧测试文件的重复路径设置
- 全部 ruff / Pyright lint 警告清零

### 代码清理

- 移除 4 处未使用变量（`tafel_values` / `encodings` × 2 / `db`）
- 移除 30+ 处未使用 import（`typing.Any` / `pytest` / `patch` 等）
- 12 处 import 排序修复（I001）
- 核心模块补充 `__all__` 导出声明

## 6.0.4

### 项目质量改进

- README 与 README.en 新增完整环境变量参考表（16 个变量）、故障排查章节和安全说明
- `pyproject.toml` 补充 license / authors / keywords 元数据
- `packaging/README.md` 新增常见打包问题排查
- `http_server.py` 添加安全设计说明文档字符串
- `processing_core_v6.py` 新增 `ELECTROCHEM_V6_LOG_LEVEL` 环境变量支持
- 依赖版本范围优化：numpy / openai 放宽至 `<3.0`，pywebview 收紧至 `<5.0`
- 新增 `requirements-frozen.txt` 精确锁定版本
- CI 新增 `--cov-fail-under=60` 覆盖率门槛

### 测试

- 新增 7 个测试文件共 109 个测试覆盖 LSV / CV / EIS / quality / LLM / agent / entry-points
- 覆盖率从 56% 提升至 63%
- 修复 I001 import 排序错误

### CI / CD

- 修复 PowerShell 中 `$(.+?)` 被误解析为子表达式的 regex bug（ci.yml 和 release.yml）

## 6.0.3

### CI / CD

- CI release job 迁移至 `windows-latest`，自动构建 PyInstaller 便携包 + Inno Setup 安装程序
- GitHub Release 现在包含 `ElectroChemV6-<version>-win64.zip` 及可选安装程序 EXE
- 修复 GITHUB_TOKEN 推送的 tag 无法触发其他 workflow 的问题（合并 build+release 为同一 job）
- `release.yml` 改为手动触发备用
- CI 新增 `pytest-cov` 覆盖率报告和 `ruff` 代码风格检查
- Inno Setup 在 CI 上通过 `choco install` 自动安装

### 代码质量

- 统一 `print()` 替换为 `logger` 调用（processing_core_v6 / processing_cv / processing_eis）
- 数据库 JSON→SQLite 迁移路径异常处理细化，增加失败记录的上下文日志
- `requirements-dev.txt` 补全开发工具（pytest-cov、ruff、pyright）
- `.gitignore` 补全 IDE / OS 常见条目

### 文档

- README 添加 CI 状态、Release、License 徽章
- CHANGELOG 补充 v6.0.3 条目

## 6.0.2

### 安全修复

- `system_service.py`：`open_path_target` 增加白名单校验，仅允许打开 `folder` / `file`
- `system_service.py`：新增运行时目录注册 + 历史记录回退校验，修复处理完成后"打开文件/目录"无响应的问题
- `http_server.py`：静态文件响应增加 10MB 大小限制
- `request_utils.py`：ZIP 上传增加 `PK\x03\x04` 魔数校验
- `.gitignore`：去除重复的 `__pycache__/` 条目

### 新增功能

- **SQLite 存储后端**：新增 `database.py`，WAL 模式 + 线程安全连接池，首次启动自动从 JSON 迁移；设置 `ELECTROCHEM_V6_STORAGE=json` 可切回旧 JSON 模式
- **Pipeline skip-on-error**：单文件处理失败不中断批处理，错误汇总至结果 (`skipped_errors`)
- **逐文件进度反馈**：LSV/CV/EIS 处理时显示 `类型 (N/M): 文件名` 进度状态
- **EIS Randles 等效电路拟合**：简化 Rs + Rct‖Cdl 模型，拟合曲线叠加到 Nyquist 图并标注参数
- **ECSA 材料 Cs 预设**：UI 新增材料下拉选择（Pt/Carbon/IrO₂/RuO₂/NiFeOOH/MnO₂/CoOₓ），自动填充比电容
- **Tafel R² 验证**：Tafel 拟合 R² < 0.99 时自动在质量报告中追加警告
- **UI 基础/高级模式**：新增"显示高级配置"开关，未勾选时隐藏详细参数配置面板
- **参比电极预设扩展**：新增 Hg/Hg₂SO₄ (sat. K₂SO₄)、MSE、RHE 预设
- **项目 ZIP 导出**：新增 `GET /api/v1/projects/{id}/export-zip` 端点
- **历史指标范围过滤**：`/api/v1/history` 支持 `metric_key` / `metric_min` / `metric_max` / `type` 查询参数
- **CV ΔEp 与电荷积分**：峰检测启用时计算峰电位差 ΔEp 并标注；梯形法计算 ∫|I|dE 电荷量

### 测试

- 新增 7 个 `open_path_target` 白名单安全测试
- 全部 110 个测试通过（1 个 playwright 跳过）
- CI 改为运行全部测试

### 其他

- 新增 `pyrightconfig.json` 配置 `extraPaths`

## 6.0.1

- 发布独立可运行的 `v6` 仓库版本
- 支持 `python run_v6.py --port 8010` 直接启动服务
- 提供 `setup.bat` 与 `start.bat`
- 内化 `store` / `llm` / `agent` / `processing_core` 运行依赖
- 通过最小运行验证：
  - `check`
  - `smoke`
  - `server` 相关测试
  - `e2e real data`
  - `stress`

## 6.0.0

### 初始版本

- 从内部项目拆分为独立仓库，建立 v6 架构
- 支持 LSV / CV / EIS / ECSA 四种数据类型处理
- 本地 HTTP 服务 + Web UI 工作台
- 项目管理、历史记录、质量报告基础框架
- 可选的 LLM / Agent 分析链路
- 参比电极预设（Ag/AgCl、SCE、Hg/HgO）
- 批量匹配（前缀、包含、正则）
- JSON 存储后端

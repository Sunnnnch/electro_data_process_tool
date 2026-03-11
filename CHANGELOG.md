# Changelog

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

# 通过 MCP 连接其他 AI

ElectroChem 提供本地 stdio MCP 服务，复用正在运行的客户端服务、项目、任务与结果。它不需要本软件内置助手的模型密钥，也不会调用内置助手或付费模型；AI 客户端自身的模型和计费由该客户端管理。

## 从桌面客户端连接

1. 打开 `ElectroChem.exe`，进入“客户端 → AI 连接（MCP）”。
2. 默认提供查询、结果比较和预检。如需运行计算与生成报告，勾选“允许新建处理任务和导出报告”。
3. 点击“复制配置”，在 AI 客户端的本地 MCP 设置中添加。已有 `mcpServers` 时，仅合并 `electrochem` 项，不覆盖其他服务。
4. 重新连接 MCP，确认能看到 ElectroChem 工具。使用期间保持本软件运行，最小化或“后台继续”均可。

配置使用当前程序和数据目录的完整路径，无需猜测桌面端口；每次工具调用会重新发现并验证当前桌面服务。软件退出后无法继续查询或提交任务，重新打开后可再次调用。

打包目录包含窗口客户端 `ElectroChem.exe` 和供 AI 启动的 stdio 程序 `ElectroChem-MCP.exe`。请保留完整目录，不要用 GUI EXE 代替 MCP 程序，也无需手动双击 MCP 程序。

通用配置示例，实际路径以软件内复制的配置为准：

```json
{
  "mcpServers": {
    "electrochem": {
      "command": "D:\\Apps\\ElectroChem\\ElectroChem-MCP.exe",
      "args": ["--data-dir", "D:\\Apps\\ElectroChem\\user_data", "--allow-write"]
    }
  }
}
```

移除 `--allow-write` 即为只读模式。修改后需重新启动该 MCP 连接，工具列表才会更新。各 AI 客户端对工具调用的批准方式由它们自己的设置决定。

## 工具

| 工具 | 用途 |
| --- | --- |
| `list_projects` | 分页查询项目 |
| `search_results` | 按项目、类型、关键词搜索历史结果 |
| `get_result` | 读取指定记录的指标、质量信息及输出路径 |
| `get_run` | 读取运行配方、参数、输入指纹和计算版本 |
| `get_processing_schema` | 查询处理参数、单位、范围与默认值 |
| `list_templates` | 查询保存的参数模板 |
| `preflight_process` | 检查文件与参数，不执行正式计算 |
| `list_jobs` / `get_job` | 查询数据处理任务与进度 |
| `compare_results` | 比较明确指定的两条历史记录 |
| `start_process` | 预检通过后提交后台计算，需要 `--allow-write` |
| `export_report` | 导出指定运行或所选项目记录的报告，需要 `--allow-write` |

预检沿用引擎的路径权限检查，可能创建临时检查文件，但不生成计算结果。正式处理使用软件生成的新输出目录，保留原始数据；MCP 不接受任意输出目录或关闭独立输出目录。它不提供删除项目、删除数据、修改模型密钥、执行命令或操作外部网页的工具。

## 调用示例

可以先对 AI 说：“列出我的电化学项目，找到最近的 CV 结果并解释质量提示。”

处理时先查询 `get_processing_schema`，再调用 `preflight_process`。示例请求结构：

```json
{
  "request": {
    "data_types": ["CV"],
    "input_files": [{"path": "D:\\Measurements\\CV_sample.csv", "data_type": "CV"}],
    "params": {"cv_scan_rate_v_s": 0.05}
  }
}
```

数值仅用于说明结构，实际参数应依据实验记录填写。参数键、单位和默认值以当前引擎返回的 schema 为准。检查预检的 `runnable`、文件清单与警告后，`start_process` 接受相同请求结构，再次预检并返回 `job_id`。用 `get_job` 跟踪任务，再按结果引用中的 `run_id`、`record_keys` 读取本次结果；不要以“最近一条记录”代替本次任务结果。

导出单次运行报告使用 `export_report(run_id="运行标识", format="html")`。导出项目报告时提供 `project_id`，并选择 `record_keys` 或 `run_ids` 中的一组；返回报告的本机文件路径。

## 源码与浏览器模式

源码环境安装 `requirements.txt` 后，MCP 配置的 `command` 使用该环境的 Python，`args` 使用 `run_v6.py` 的完整路径和 `mcp` 子命令：

```text
python run_v6.py mcp --data-dir "D:\ElectroChemData"
python run_v6.py mcp --data-dir "D:\ElectroChemData" --allow-write
```

`--data-dir` 指向已打开的桌面客户端的数据目录。浏览器模式已启动 HTTP 服务时，可指定其地址：

```text
python run_v6.py mcp --url http://127.0.0.1:8010 --allow-write
```

stdio 启动后等待 AI 客户端发送协议消息，没有普通终端提示输出是正常现象。不要用 `pythonw.exe` 启动，也不要向 stdout 添加调试文字。

此版本连接同一台电脑上的客户端，不提供公网 MCP 地址。仅支持远程 HTTP MCP 的云端 AI 不能使用本地 stdio 配置。输入路径须位于运行本软件的电脑上。

## 排查连接

- 没有桌面服务：先打开本软件，核对数据目录，或重新复制软件内配置。
- 缺少 MCP 程序：使用完整的新版本目录，不能仅复制 GUI EXE。
- 找不到处理或导出工具：启用对应权限后重新连接 MCP。
- 预检阻断：核对本机路径、文件类型、仪器列、单位和必填参数。
- 提交超时或连接中断：先查询任务确认是否已提交，避免盲目重试产生重复计算。
- 更新软件时仍提示运行中：结束处理任务、退出软件，并断开 AI 客户端的 ElectroChem MCP 连接后再更新。

实现采用官方 Python SDK 维护中的 1.x 系列。协议参考：[MCP stdio 传输](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、[官方 Python SDK 1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)。

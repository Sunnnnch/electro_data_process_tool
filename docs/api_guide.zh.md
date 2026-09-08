# ElectroChem 开发者接口指南

**智能电化学数据处理软件**（ElectroChem — Intelligent Electrochemical Data Processing Software）的本地 HTTP 接口，适用于脚本、批处理和自定义客户端。界面操作见[使用说明](../src/electrochem_v6/ui/static/help_manual.zh.md)，接口字段参考 [OpenAPI](openapi.yaml)。[English](api_guide.en.md)

## 1. 启动与请求约定

按 [README](../README.md) 安装依赖后，在仓库根目录运行：

```shell
python run_v6.py --port 8010
```

默认地址为 `http://127.0.0.1:8010`，界面为 `/ui`。软件显示名称变化不改变 `electrochem_v6` 包名、`run_v6.py`、接口路径或默认端口。文件路径均指**服务所在电脑**上的路径，返回的输出路径也不是下载 URL。

```shell
curl.exe http://127.0.0.1:8010/health
curl.exe "http://127.0.0.1:8010/api/v1/process/schema?data_types=LSV,EIS"
```

`/health` 返回 `{"status":"ok","version":"…"}`。处理等业务接口通常使用 `status: "success" | "error"`；不要把健康状态、任务状态和业务状态混为一谈。JSON 请求使用 `Content-Type: application/json` 和 UTF-8；需要空请求体的 POST 也应传 `{}`。

### 本地访问与会话校验

- 服务监听回环地址。请求的 `Host` 必须是允许的本机名称和服务端口；浏览器 `Origin` 也必须通过回环来源及端口检查，跨站请求会被拒绝。
- 本机 Python、curl 等非浏览器客户端通常不发送 `Origin` / `Sec-Fetch-Site`，可直接调用，无需 Bearer token。
- 浏览器写请求需要本次服务启动生成的 `X-Electrochem-Session`。内置 `/ui` 页面中的 `ElectrochemApi.fetch(...)` 会从页面会话元信息读取并添加它；服务重启后须重新加载页面。该 header 不能绕过来源校验。
- 这是本地请求保护机制，不是多用户登录或公网 API 认证。模型供应商的 API key 属于助手配置，不是 HTTP 接口的会话凭据。

目录还须在应用允许的范围内：通常为工作目录、用户目录中的非敏感路径，或通过本机文件选择器登记的目录。遇到“路径不在允许范围内”，可在界面选取该目录，或调用 `POST /api/v1/system/select-folder` 打开本机选择器；这不是无人值守的路径授权接口。

## 2. 参数 schema 与精确输入

`GET /api/v1/process/modules` 查询处理模块；`GET /api/v1/process/schema?data_types=LSV,EIS` 返回 `schema.parameters`，每项含 `key`、`value_type`、默认值、范围、选项、适用模块和界面说明。它是**参数目录**，不是可直接传给 JSON Schema 校验器的完整请求 schema。

请求结构为 `folder_path` / `input_files`、`data_types`、可选的 `project_id` 或 `project_name`，以及 `params`。已有项目使用稳定的 `project_id`，其优先级高于名称。不要用显示名称推断唯一项目。未声明参数会被拒绝；schema 中的默认值也不能替代真实的面积、单位、参比电极或实验条件。

输入有两种语义：

| 方式 | 行为 |
| --- | --- |
| 仅 `folder_path` | 按各模块的文件匹配设置扫描目录；是否递归取决于参数。 |
| 提供 `input_files` | 只处理清单中启用的主数据，不从附近目录增加主数据。对象需指定 `path` 和 `data_type`；`enabled` 默认 `true`。 |

使用绝对路径。主数据目前接受 `.txt` / `.csv`，不能把已生成的结果文件重新作为主数据。一个文件不能分配给两个模块；空的启用清单会报错。精确输入模式可省略 `folder_path`，以首个文件目录作为上下文；为相对辅助路径提供明确上下文时，建议保留它。

`input_files` 只约束**主数据**。iR 所用 EIS、COUPLED 定量表、方法文件和信号文件仍按对应参数解析；需要精确的 iR 配对时，使用 `ir_eis_search_scope: "specified_file"` 和 `ir_eis_file`。COUPLED 表不放入 `input_files`，而是指定 `params.coupled_products_file`。

### LSV 请求示例

把以下内容保存为 UTF-8 的 `request.json`，修改为实际文件路径。示例明确假定第 1 列是 V、第 2 列是 A、面积为 1 cm²，使用电流绝对值，无电位偏移、无 iR 补偿，不启用 Tafel 或过电位计算。**这些是演示条件，须按实验记录修改。**列号从 1 开始。

```json
{
  "folder_path": "D:/data/demo",
  "project_name": "API_demo",
  "data_types": ["LSV"],
  "input_files": [
    {"path": "D:/data/demo/LSV_A.txt", "data_type": "LSV", "enabled": true}
  ],
  "params": {
    "area": 1.0,
    "lsv_potential_column": 1,
    "lsv_current_column": 2,
    "lsv_potential_unit": "v",
    "lsv_current_unit": "a",
    "potential_mode": "manual",
    "potential_offset": 0.0,
    "use_abs_current": true,
    "ir_compensation_enabled": false,
    "lsv_target_current": "10",
    "tafel_enabled": false,
    "overpotential_enabled": false
  }
}
```

先预检，再提交同一份请求：

```shell
curl.exe -H "Content-Type: application/json" --data-binary @request.json http://127.0.0.1:8010/api/v1/process/preflight
curl.exe -H "Content-Type: application/json" --data-binary @request.json http://127.0.0.1:8010/api/v1/process/jobs
```

预检成功响应含 `preflight.by_type`、`matched_counts`、`warnings`、`checks`、`runnable`。HTTP 200 / `status: "success"` 表示预检请求完成；仍要检查 **`preflight.runnable`** 和识别到的文件。预检不保证后续拟合或全部输入处理成功。

LSV 电流密度单位为 mA/cm²；`lsv_target_current` 和 `tafel_range` 使用该单位，Tafel 斜率使用 mV/dec。启用过电位时还需核实电位基准和 `eq_potential`，过电位指标以 mV 表示。候选区间或高拟合优度不能代替实验条件和拟合诊断复核。

## 3. 同步、后台任务与结果

| 用途 | 请求 | 成功响应 |
| --- | --- | --- |
| 同步处理 | `POST /api/v1/process` | HTTP 200，完整处理响应 `{status, result}`。 |
| 后台处理 | `POST /api/v1/process/jobs` | HTTP 202，`{status, job_id, job}`，仅表示已受理。 |
| 完整任务结果 | `GET /api/v1/process/jobs/{job_id}` | `{status, job}`，处理响应位于 `job.result`。 |
| 统一任务列表 | `GET /api/v1/tasks?kind=all&status=active&limit=30&offset=0` | 摘要、进度、可取消状态和稳定结果引用，不含完整结果。 |
| 请求取消 | `POST /api/v1/tasks/{job_id}/cancel` | 已请求取消或 HTTP 409；仍需轮询最终状态。 |

任务状态为 `queued`、`running`、`succeeded`、`failed`、`cancelled`、`interrupted`。最后四种是客户端应停止普通轮询的状态。取消是协作式请求，不能保证立即停止；不要因客户端超时就重复提交。需要重新运行时，用下节的复算或恢复流程。

下面的 Python 示例只使用标准库。它读取前面的 `request.json`，检查预检并轮询后台任务。用于同步处理时，将提交和轮询两行替换为 `body = api("/api/v1/process", payload)`。

```python
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:8010"

def api(path, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(BASE + path, data=data,
                      headers={"Content-Type": "application/json"})
    try:
        response = urlopen(request, timeout=120)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8')}") from exc
    with response:
        body = json.load(response)
    if body.get("status") == "error":
        raise RuntimeError(body.get("message", body))
    return body

def wait_job(job_id, kind="process", timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = api(f"/api/v1/{kind}/jobs/{job_id}")["job"]
        if job["status"] == "succeeded":
            return job["result"]
        if job["status"] in {"failed", "cancelled", "interrupted"}:
            raise RuntimeError(f"{job['status']}: {job.get('error')}")
        time.sleep(0.5)
    raise TimeoutError(f"Task {job_id} may still be running; query its status before retrying")

payload = json.loads(Path("request.json").read_text(encoding="utf-8-sig"))
preflight = api("/api/v1/process/preflight", payload)["preflight"]
if not preflight["runnable"]:
    raise RuntimeError(preflight)
submitted = api("/api/v1/process/jobs", payload)
body = wait_job(submitted["job_id"])
result = body["result"]
run_id = result["manifest"]["run"]["run_id"]
print("run_id:", run_id)
print("outputs:", result["processing"]["output_files"])
print("quality:", result["quality_summary"])
print("skipped:", result["skipped_errors"])
```

处理成功仍可能包含跳过的文件、质量告警或报告写入错误。保留 `manifest`、输入指纹和 `run_id`，检查 `quality_summary`、`skipped_errors` 及实际输出；不要把“任务成功”解释为科学结论已审核。

## 4. COUPLED / FE

### 已定量的产物表

在输入目录保存 `products.csv`：

```csv
sample_name,product_name,product_moles,electron_count,charge_C
sample-A,H2,0.000002,2,1.0
sample-A,CO,0.000001,2,1.0
```

这里 `product_moles` 为 mol，`electron_count` 为每个产物对应的电子转移数，`charge_C` 为正的总电荷 C。示例给出 H₂ FE ≈ 38.5941%、CO FE ≈ 19.2971%；摩尔选择性分别为 66.6667% 和 33.3333%，与 FE 是不同指标。数值用于演示计算，不代表实验结果。

```json
{
  "folder_path": "D:/data/demo",
  "project_name": "FE_API_demo",
  "data_types": ["COUPLED"],
  "params": {
    "coupled_input_mode": "product_table",
    "coupled_products_file": "products.csv",
    "coupled_products_sheet": 0
  }
}
```

该请求同样先发 `/process/preflight`，再发 `/process/jobs` 或 `/process`。相对表路径从 `folder_path` 解析；CSV 不使用工作表，Excel 的 `coupled_products_sheet` 可用从 0 开始的索引或名称。

也可提供 `current_mA,time_s` 或 `current_A,time_s` 来推算电荷，前提是该电流能够代表整个给定时段；变电流实验应先得到积分总电荷。支持明确的单位声明，例如 `Product Moles (mmol)`、`Charge (mC)`；不支持或互相冲突的声明会报错，不要用单位名掩盖实际数值。每个样品的各产物必须对应同一总电荷；同一样品的重复产物行会被拒绝。不同时间点或独立实验应使用可区分的样品标识。

### 从信号峰定量

将 `coupled_input_mode` 设为 `peak_analysis`，`coupled_products_file` 指向测量表。文件方法使用 `coupled_peak_method_source: "file"` 和 `coupled_peak_method_file`；面板方法使用 `coupled_peak_method_source: "panel"` 和对象 `coupled_peak_method`。可从内置静态模板开始：

- [测量表模板](../src/electrochem_v6/ui/static/fe_peak_measurements_template.csv)：`sample_name`、`signal_file`、`charge_C`，以及体积等实验信息。
- [方法模板](../src/electrochem_v6/ui/static/fe_peak_method_template.json)：内标、峰位、积分窗口、定量核数、电子数、体积和响应修正等。
- [总电荷表模板](../src/electrochem_v6/ui/static/coupled_template_charge.csv)及[电流/时间表模板](../src/electrochem_v6/ui/static/coupled_template_current_time.csv)。运行中也可通过 `/ui/static/` 下的同名文件读取。

模板中的化合物、浓度、体积和反应信息必须按实验修改。核对预检的峰方法检查及输出的诊断 CSV/JSON；自动寻峰、偏移校正或峰拟合选项以当前 schema 为准。

## 5. 数据分析助手与明确确认

先在软件中配置可用的模型供应商。`GET /api/v1/llm/config` 返回脱敏配置。`POST /api/v1/llm/models` 接受 `provider`、可选的 `base_url` 和 `api_key`，返回 `models` 字符串列表；它只查询该地址的 `/models`，不保存新密钥或发送对话。未提供新密钥时，仅允许向已保存地址的同源端点使用保存的密钥；支持 HTTPS 和回环 HTTP，不跟随重定向。不支持列表的服务仍可手动指定模型。失败返回 HTTP 400 及稳定 `code`，例如 `unauthorized`、`unsupported`、`timeout`；不要将空列表或列表可见性等同于对话调用权限。

对话可指定 `provider`、`model`，否则按当前配置选择。以下代码复用上节 `api` 和 `wait_job`；`processing_result` 绑定刚完成的具体结果，避免依赖“最新记录”：

```python
submitted = api("/api/v1/agent/jobs", {
    "message": "请说明这次结果的质量告警和分析局限。",
    "data_type": "LSV",
    "processing_result": result,
})
reply = wait_job(submitted["job_id"], kind="agent")
conversation_id = reply["conversation_id"]
print(reply.get("agent_reply"))
print(reply.get("pending_approvals", []))
print(reply.get("action_cards", []))
```

同步方式为 `POST /api/v1/agent/messages`，返回对话响应；异步方式为 `POST /api/v1/agent/jobs`，返回 202，再从 `GET /api/v1/agent/jobs/{job_id}` 的 `job.result` 取响应。后续消息传回原 `conversation_id`。完整持久会话可从 `GET /api/v1/agent/conversations/{conversation_id}` 查询，后台任务结果不重复存储整个历史。

有两种不同的交互：

1. **`pending_approvals`**：助手提出需要确认的写操作。展示其摘要、绑定参数、目录和项目，由用户确认具体项。只有用户批准后，才将同一 `conversation_id`、该项 `approval_id`、`approval_action: "approve"` 发到消息或任务接口；拒绝用 `"decline"`。不要遍历列表自动批准。执行使用服务器保存的确认参数，不能通过同时夹带参数修改批准内容。确认过期或服务重启后，应重新生成操作。已确认写入阶段可能不可取消。
2. **`action_cards`**：`parameter_changes`、`compare_records`、`replay_run`、`report_records` 等操作预览，以及 `open_results` 结果定位卡。生成卡不等于执行。内置 UI 在点击后核对上下文、应用参数或调用对应业务接口；参数卡只改变界面设置，不直接运行处理。自定义客户端也应展示绑定的项目、记录、运行和参数差异，再经用户操作调用明确接口。不要把 action card 的 `id` 当作 `approval_id`。

示意批准请求（占位值须来自同次真实回复）：

```json
{
  "conversation_id": "<conversation_id>",
  "approval_id": "<approval_id>",
  "approval_action": "approve"
}
```

助手的科学建议依赖已确认参数或保存配方。缺少面积、列映射、单位或参比条件时会要求补全；Tafel 给出带诊断和局限的候选区间，不承诺“最优”。自定义客户端提供 `professional_context` 时，应传真实的当前选择，不能伪造确认状态或用默认值填实验事实。

## 6. 项目、历史、复算与导出

| 需求 | 接口与范围 |
| --- | --- |
| 项目 | `GET /api/v1/projects`；`POST /api/v1/projects` 创建项目。 |
| 历史分页 | `GET /api/v1/history?project=<project_id>&limit=50&cursor=<next_cursor>`；注意筛选键是 `project`。持续读取响应的 `next_cursor`，避免只取第一页。 |
| 具体记录 | `GET /api/v1/history/{record_key}`；含路径的键须作为一个路径段进行 URL 编码。 |
| 项目统计 | `GET /api/v1/stats?project=<project_id>`。 |
| 运行与配方 | `GET /api/v1/runs?project_id=<id>&limit=100&offset=0`；`GET /api/v1/runs/{run_id}`，响应为 `{status, run}`。 |
| 复算预检与提交 | `POST /api/v1/runs/{run_id}/replay-plan`，检查 `plan.can_replay`；再发 `/replay`，返回新的后台任务。可传 `record_key`、`params`、`source_paths`。 |
| 精确比较 | `POST /api/v1/history/compare`，传 `left_record_key`、`right_record_key` 和可选 `project_id`。 |
| 所选范围报告 | `POST /api/v1/projects/{project_id}/report`，传 `record_keys` **或** `run_ids`、可选 `include_archived` 和 `format: "html" | "markdown"`；单次运行用 `POST /api/v1/runs/{run_id}/report`。 |
| 独立重复统计 | 项目下 `/replicate-preview`、`/replicate-groups`，详见 OpenAPI。复算版本不等于独立重复；缺失或变化的分析条件需针对当前签名确认。 |
| 异常中断恢复 | `GET /api/v1/process/recovery`，然后 `/plan`、`/resume`。检查原进程状态、输入与配方，恢复生成新任务和输出；未知旧进程只能在人工确认其已停止后继续。 |
| 本机打开结果 | `POST /api/v1/system/open-path`，请求 `{"path":"<返回的本地路径>","reveal_only":true}`。 |

报告响应含 `path`、`html_path` / `markdown_path` 和 `scope`，应显示实际范围和计数。COUPLED 运行可能没有普通 history 行，完整结果应从运行配方及报告读取。旧记录缺配方或指纹时，不能假设可以按当前默认参数准确复现。复算和恢复均保存原结果，并产生新的运行标识。

## 7. ZIP 与错误处理

`POST /api/v1/process-zip` 为同步 multipart 上传：文件字段 `file`，模块字段 `data_type`，`params` 为 JSON 字符串，可带 `project_name`。助手的 `/agent/messages` 与 `/agent/jobs` 也接受带 ZIP 的 multipart 请求；上传处理会先执行，再将处理结果交给助手，**不会等待助手另行提出处理确认**。提交上传请求本身应来自用户明确的处理操作。JSON 形式的 `/process/jobs` 不接受二进制文件。

常见 HTTP 状态：400 为输入或参数错误，403 为请求来源/会话不允许，404 为资源不存在，409 为当前状态不能取消、复算或恢复，503 为任务服务不可用。某些计划接口用 HTTP 200 返回 `can_replay: false` / `can_recover: false`，因此始终同时检查业务字段。上传大小和 ZIP 展开限制也会返回错误；不要只按 HTTP 202/200 判断最终任务成功。

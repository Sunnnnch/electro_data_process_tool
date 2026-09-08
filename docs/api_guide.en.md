# ElectroChem Developer API Guide

The local HTTP API for **ElectroChem — Intelligent Electrochemical Data Processing Software** (智能电化学数据处理软件) supports scripts, batch processing, and custom clients. See the [user manual](../src/electrochem_v6/ui/static/help_manual.en.md) for desktop workflows and [OpenAPI](openapi.yaml) for endpoint fields. [中文](api_guide.zh.md)

## 1. Starting the service and making requests

Install the dependencies described in the [README](../README.en.md), then run from the repository root:

```shell
python run_v6.py --port 8010
```

The default address is `http://127.0.0.1:8010`; the UI is at `/ui`. The display-name change does not rename the `electrochem_v6` package, `run_v6.py`, API paths, or default port. File paths refer to files **on the computer running the service**. Returned output paths are local paths, not download URLs.

```shell
curl.exe http://127.0.0.1:8010/health
curl.exe "http://127.0.0.1:8010/api/v1/process/schema?data_types=LSV,EIS"
```

`/health` returns `{"status":"ok","version":"…"}`. Business endpoints normally use `status: "success" | "error"`; health, job, and business statuses are different contracts. Send JSON as UTF-8 with `Content-Type: application/json`. For a POST that needs no options, send `{}`.

### Local access and session checks

- The service binds to loopback. `Host` must use an allowed local hostname and service port. Browser `Origin` must also pass loopback-origin and port checks; cross-site requests are rejected.
- Local non-browser clients such as Python and curl normally send neither `Origin` nor `Sec-Fetch-Site` and can call the API without a Bearer token.
- Browser writes require `X-Electrochem-Session`, generated when the service starts. The bundled `/ui` page's `ElectrochemApi.fetch(...)` reads it from the page metadata and adds it automatically. Reload the page after a service restart. The header does not bypass origin validation.
- This protects local requests; it is not multi-user login or public API authentication. A model provider's API key belongs to assistant configuration and is not the HTTP session credential.

Input directories must also be within the application's allowed roots: normally the working tree, non-sensitive paths under the user's home, or directories registered through the local picker. If a path is outside the allowed roots, select it in the UI or use `POST /api/v1/system/select-folder` to open the local picker. This is an interactive picker, not an unattended path-authorization endpoint.

## 2. Parameter schema and exact inputs

`GET /api/v1/process/modules` lists processing modules. `GET /api/v1/process/schema?data_types=LSV,EIS` returns `schema.parameters`, including each parameter's `key`, `value_type`, defaults, limits, options, module scope, and UI guidance. This is a **parameter catalog**, not a complete request schema that can be passed directly to a JSON Schema validator.

A processing request contains `folder_path` / `input_files`, `data_types`, optional `project_id` or `project_name`, and `params`. Use the stable `project_id` for an existing project; it takes precedence over the name. Do not infer unique project identity from display names. Undeclared parameters are rejected. Software defaults are not evidence of the actual area, units, reference electrode, or experimental conditions.

| Input mode | Behavior |
| --- | --- |
| `folder_path` only | Discover files using each module's matching rules; recursion depends on the parameters. |
| Explicit `input_files` | Process only enabled primary inputs in the list, without adding nearby primary files. Each object specifies `path` and `data_type`; `enabled` defaults to `true`. |

Use absolute paths. Primary data currently accepts `.txt` / `.csv`; generated result files cannot be selected as primary input. A file cannot be assigned to two modules, and an empty enabled selection is an error. With exact inputs, `folder_path` may be omitted: the first input's directory becomes the context. Keeping it explicit helps resolve relative auxiliary paths.

`input_files` constrains **primary data only**. EIS for iR correction, COUPLED tables, method files, and signals are resolved through their own parameters. For a specific iR pairing, use `ir_eis_search_scope: "specified_file"` and `ir_eis_file`. Put the COUPLED table in `params.coupled_products_file`, not in `input_files`.

### LSV request example

Save this as UTF-8 `request.json` and replace the paths with actual inputs. The example explicitly assumes column 1 is V, column 2 is A, an area of 1 cm², absolute current, no potential offset, and no iR correction. It disables Tafel and overpotential calculations. **These are demonstration settings; replace them using the experimental record.** Column numbers start at 1.

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

Preflight first, then submit the same request:

```shell
curl.exe -H "Content-Type: application/json" --data-binary @request.json http://127.0.0.1:8010/api/v1/process/preflight
curl.exe -H "Content-Type: application/json" --data-binary @request.json http://127.0.0.1:8010/api/v1/process/jobs
```

A preflight response includes `preflight.by_type`, `matched_counts`, `warnings`, `checks`, and `runnable`. HTTP 200 / `status: "success"` means that the preflight request completed: also check **`preflight.runnable`** and the recognized files. Preflight does not guarantee that every input will process successfully or that a fit will be valid.

LSV current density is in mA/cm². `lsv_target_current` and `tafel_range` use that unit; Tafel slopes use mV/dec. Before enabling overpotential, verify the potential reference and `eq_potential`; overpotential metrics are in mV. Candidate ranges or high fit scores do not replace scientific review of conditions and diagnostics.

## 3. Synchronous calls, background jobs, and results

| Purpose | Request | Successful response |
| --- | --- | --- |
| Synchronous processing | `POST /api/v1/process` | HTTP 200 with the full `{status, result}` processing response. |
| Background processing | `POST /api/v1/process/jobs` | HTTP 202 with `{status, job_id, job}`; acceptance only. |
| Full job result | `GET /api/v1/process/jobs/{job_id}` | `{status, job}`; the processing response is in `job.result`. |
| Unified task list | `GET /api/v1/tasks?kind=all&status=active&limit=30&offset=0` | Summaries, progress, cancellation availability, and stable result references; not full results. |
| Request cancellation | `POST /api/v1/tasks/{job_id}/cancel` | Cancellation requested, or HTTP 409; continue polling for the final state. |

Job states are `queued`, `running`, `succeeded`, `failed`, `cancelled`, and `interrupted`. Stop ordinary polling on any of the last four. Cancellation is cooperative and may not be immediate. A client timeout does not justify blindly submitting the same work again; use replay or recovery when a new run is needed.

This standard-library Python example reads `request.json`, checks preflight, and polls a background job. For synchronous processing, replace the submission and polling lines with `body = api("/api/v1/process", payload)`.

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

Successful processing may still contain skipped files, quality warnings, or report-writing errors. Retain the `manifest`, input fingerprints, and `run_id`; inspect `quality_summary`, `skipped_errors`, and actual outputs. Job completion is not scientific approval of the results.

## 4. COUPLED / FE

### Quantified product table

Save `products.csv` in the input directory:

```csv
sample_name,product_name,product_moles,electron_count,charge_C
sample-A,H2,0.000002,2,1.0
sample-A,CO,0.000001,2,1.0
```

`product_moles` is in mol, `electron_count` is the electron-transfer count for that product, and `charge_C` is positive total charge in C. This example gives H₂ FE ≈ 38.5941% and CO FE ≈ 19.2971%. Mole-based selectivities are 66.6667% and 33.3333%, respectively, and are distinct from FE. These values demonstrate the calculation, not experimental findings.

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

Send this to `/process/preflight`, followed by `/process/jobs` or `/process`. Relative table paths resolve from `folder_path`. CSV ignores the sheet setting; for Excel, `coupled_products_sheet` accepts a zero-based index or sheet name.

Alternatively, provide `current_mA,time_s` or `current_A,time_s` to derive charge, provided that the current represents the stated interval. For varying-current experiments, supply integrated total charge. Explicit declarations such as `Product Moles (mmol)` and `Charge (mC)` are supported; unsupported or conflicting declarations are errors. Each product for a sample must use the same total charge. Duplicate product rows within a sample are rejected. Give different time points or independent experiments distinct sample identifiers.

### Quantification from signal peaks

Set `coupled_input_mode` to `peak_analysis` and point `coupled_products_file` at the measurement table. A file-based method uses `coupled_peak_method_source: "file"` and `coupled_peak_method_file`. An inline method uses `coupled_peak_method_source: "panel"` and the `coupled_peak_method` object. Start from the bundled templates:

- [Measurement template](../src/electrochem_v6/ui/static/fe_peak_measurements_template.csv): `sample_name`, `signal_file`, `charge_C`, and experimental information such as volumes.
- [Method template](../src/electrochem_v6/ui/static/fe_peak_method_template.json): internal standard, positions, integration windows, nuclei counts, electrons, volumes, and response corrections.
- [Total-charge table](../src/electrochem_v6/ui/static/coupled_template_charge.csv) and [current/time table](../src/electrochem_v6/ui/static/coupled_template_current_time.csv). The running service also exposes these filenames under `/ui/static/`.

Replace the template compounds, concentrations, volumes, and reaction information with the actual experimental values. Inspect peak-method preflight checks and diagnostic CSV/JSON outputs. Use the current parameter schema for peak search, alignment, and fitting options.

## 5. Data analysis assistant and explicit confirmation

Configure a working model provider in the application first. `GET /api/v1/llm/config` returns masked settings. `POST /api/v1/llm/models` accepts `provider`, optional `base_url`, and optional `api_key`, returning a `models` array of IDs. It only queries that address's `/models` endpoint, without saving a new key or sending a chat. Without an entered key, saved credentials may only be used at the saved origin. HTTPS and loopback HTTP are supported; redirects are not followed. Services without a catalogue can still use a manually entered model. Errors return HTTP 400 and a stable `code`, such as `unauthorized`, `unsupported`, or `timeout`. Listing a model does not establish chat compatibility or inference access.

A conversation can specify `provider` and `model`, or use the current configuration. The example reuses `api` and `wait_job` above; `processing_result` binds the exact completed result rather than relying on a “latest record” lookup:

```python
submitted = api("/api/v1/agent/jobs", {
    "message": "Explain the quality warnings and analytical limitations of this result.",
    "data_type": "LSV",
    "processing_result": result,
})
reply = wait_job(submitted["job_id"], kind="agent")
conversation_id = reply["conversation_id"]
print(reply.get("agent_reply"))
print(reply.get("pending_approvals", []))
print(reply.get("action_cards", []))
```

`POST /api/v1/agent/messages` returns a synchronous conversation response. `POST /api/v1/agent/jobs` returns HTTP 202; retrieve the response from `job.result` at `GET /api/v1/agent/jobs/{job_id}`. Pass the original `conversation_id` on follow-ups. Retrieve the full persisted conversation from `GET /api/v1/agent/conversations/{conversation_id}`; job results do not duplicate its entire history.

Two different interactions can appear:

1. **`pending_approvals`** represent proposed write operations. Show the summary and bound parameters, directory, and project for the user to review. Only after approval, send the same `conversation_id`, that item's `approval_id`, and `approval_action: "approve"` to the message or job endpoint. Use `"decline"` to reject. Never automatically approve every item. Execution uses server-stored parameters; adding new parameters to the approval request cannot change the approved action. Expired approvals or approvals from before a service restart must be regenerated. An approved write phase may no longer be cancellable.
2. **`action_cards`** contain previews such as `parameter_changes`, `compare_records`, `replay_run`, and `report_records`, plus `open_results` navigation cards. Producing a card does not execute it. When clicked, the built-in UI checks the current context and applies settings or calls the corresponding business endpoint. A parameter card updates GUI settings without starting processing. Custom clients should likewise show the bound project, records, run, and parameter differences before the user invokes an explicit endpoint. An action card's `id` is not an `approval_id`.

Example approval request, using values from an actual reply:

```json
{
  "conversation_id": "<conversation_id>",
  "approval_id": "<approval_id>",
  "approval_action": "approve"
}
```

Scientific recommendations require confirmed parameters or a saved recipe. Missing area, column mapping, units, or reference conditions must be supplied. Tafel suggestions are candidate ranges with diagnostics and limitations, not promised “optimal” ranges. If a custom client sends `professional_context`, it must reflect the actual current selection; do not fabricate confirmation state or substitute defaults for experimental facts.

## 6. Projects, history, replay, and exports

| Purpose | Endpoint and scope |
| --- | --- |
| Projects | `GET /api/v1/projects`; create with `POST /api/v1/projects`. |
| Paginated history | `GET /api/v1/history?project=<project_id>&limit=50&cursor=<next_cursor>`; the filter key is `project`. Follow the returned `next_cursor` rather than stopping at the first page. |
| Exact record | `GET /api/v1/history/{record_key}`; URL-encode the entire key as one path segment, including any file-path characters. |
| Project statistics | `GET /api/v1/stats?project=<project_id>`. |
| Runs and recipes | `GET /api/v1/runs?project_id=<id>&limit=100&offset=0`; `GET /api/v1/runs/{run_id}` returns `{status, run}`. |
| Checked replay | `POST /api/v1/runs/{run_id}/replay-plan`; inspect `plan.can_replay`, then submit `/replay` to create a background job. Options include `record_key`, `params`, and `source_paths`. |
| Exact comparison | `POST /api/v1/history/compare` with `left_record_key`, `right_record_key`, and optional `project_id`. |
| Scoped report | `POST /api/v1/projects/{project_id}/report` with `record_keys` **or** `run_ids`, optional `include_archived`, and `format: "html" | "markdown"`. For a single run use `POST /api/v1/runs/{run_id}/report`. |
| Independent replicates | Project `/replicate-preview` and `/replicate-groups`; see OpenAPI. Replay versions are not independent repeats. Missing or differing analysis conditions require confirmation against the current signature. |
| Interrupted-work recovery | `GET /api/v1/process/recovery`, followed by `/plan` and `/resume`. Check the original process, inputs, and recipe. Recovery creates a new job and outputs; an unknown legacy process requires human confirmation that it has stopped. |
| Open a local result | `POST /api/v1/system/open-path` with `{"path":"<returned local path>","reveal_only":true}`. |

Report responses include `path`, `html_path` / `markdown_path`, and `scope`; show the actual scope and counts. A COUPLED run may have no ordinary history rows, so use its recipe and report for the complete results. Older records without recipes or fingerprints cannot be assumed reproducible with today's defaults. Replay and recovery preserve original results and create new run identifiers.

## 7. ZIP uploads and errors

`POST /api/v1/process-zip` accepts a synchronous multipart upload: `file` for the ZIP, `data_type` for the module, `params` as a JSON string, and optional `project_name`. Assistant `/agent/messages` and `/agent/jobs` also accept multipart ZIP uploads. Uploaded data is processed first, then sent to the assistant; it **does not wait for a separate assistant-generated processing approval**. Submitting an upload must itself follow the user's explicit processing action. JSON `/process/jobs` does not accept binary files.

Common HTTP codes are 400 for input or parameter errors, 403 for rejected origin/session context, 404 for missing resources, 409 for cancellation/replay/recovery conflicts, and 503 for an unavailable job manager. Some plan endpoints return HTTP 200 with `can_replay: false` or `can_recover: false`, so always inspect the business fields. Upload and ZIP expansion limits can also produce errors. HTTP 202/200 alone is not evidence that the final task succeeded.

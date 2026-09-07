"""Official FastMCP stdio tools backed exclusively by the existing HTTP service."""

from __future__ import annotations

import asyncio
import json
from functools import wraps
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote

from jsonschema import Draft202012Validator, ValidationError
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, model_validator

from .client import ElectroChemClient, MCPClientError

DataType = Literal["LSV", "CV", "ECSA", "EIS", "COUPLED"]
Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
RecordKey = Annotated[str, Field(strict=True, min_length=1, max_length=4096)]
SourcePath = Annotated[str, Field(strict=True, min_length=1, max_length=4096)]
Limit = Annotated[int, Field(strict=True, ge=1, le=100)]
Offset = Annotated[int, Field(strict=True, ge=0, le=100000)]


class InputFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: SourcePath
    data_type: DataType


class ProcessingRequest(BaseModel):
    """Explicit scientific inputs; output location and run identity are server-owned."""

    model_config = ConfigDict(extra="forbid", strict=True)
    data_types: Annotated[list[DataType], Field(min_length=1, max_length=5)]
    folder_path: SourcePath | None = None
    input_files: Annotated[list[InputFile], Field(min_length=1, max_length=500)] | None = None
    params: Annotated[dict[str, JsonValue], Field(max_length=256)] = Field(default_factory=dict)
    project_id: Identifier | None = None
    project_name: Annotated[str, Field(strict=True, min_length=1, max_length=256)] | None = None

    @model_validator(mode="after")
    def validate_selection(self):
        if not self.folder_path and not self.input_files:
            raise ValueError("Provide folder_path or exact input_files.")
        if len(set(self.data_types)) != len(self.data_types):
            raise ValueError("data_types must not contain duplicates.")
        if self.project_id and self.project_name:
            raise ValueError("Choose project_id or project_name, not both.")
        if self.input_files and any(item.data_type not in self.data_types for item in self.input_files):
            raise ValueError("Every input file must belong to a selected data_type.")
        if "output_dir" in self.params or any(key.startswith("_") for key in self.params):
            raise ValueError("Output directories and internal processing fields cannot be supplied through MCP.")
        if self.params.get("output_run_dir_enabled", True) is not True:
            raise ValueError("MCP processing always creates a new isolated output directory.")
        filename = self.params.get("coupled_results_csv_filename")
        if filename is not None and (not isinstance(filename, str) or len(filename) > 128
                or any(char in filename for char in '/\\:\x00') or not filename.lower().endswith(".csv")):
            raise ValueError("coupled_results_csv_filename must be a plain CSV filename, without a directory.")
        # Limit nested method/config tables too; JsonValue alone permits large trees.
        if len(json.dumps(self.model_dump(), ensure_ascii=False, allow_nan=False).encode("utf-8")) > 256 * 1024:
            raise ValueError("Processing input exceeds 256 KiB; reduce the selected files or parameters.")
        return self


def _path_id(value: str) -> str:
    if value in {".", ".."} or any(ord(char) < 32 for char in value):
        raise MCPClientError("invalid_id", "Identifiers cannot contain control characters or directory traversal markers.")
    return quote(value, safe="")


def _processing_payload(connection, request: ProcessingRequest) -> dict[str, Any]:
    schema = connection.request("GET", "/api/v1/process/schema", query={"data_types": ",".join(request.data_types)})
    known = {item["key"] for item in schema.get("schema", {}).get("parameters", []) if isinstance(item, dict) and "key" in item}
    if not known:
        raise MCPClientError("invalid_schema", "The running service did not provide its processing parameter schema.")
    unknown = sorted(set(request.params) - known)
    if unknown:
        raise MCPClientError("unknown_parameters", "Use parameter keys returned by get_processing_schema; input and output control fields are not accepted as parameters.", {"keys": unknown})
    payload = request.model_dump(exclude_none=True)
    payload["params"] = {**request.params, "output_run_dir_enabled": True}
    return payload


def _result(payload: dict[str, Any], *, error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, allow_nan=False))],
                          structuredContent=payload, isError=error)


class _StrictFastMCP(FastMCP):
    """Validate wire JSON before FastMCP's backwards-compatible string coercion."""

    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema["additionalProperties"] = False
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = next((item for item in await self.list_tools() if item.name == name), None)
        if tool is None:
            return _result({"status": "error", "code": "unknown_tool", "message": "This tool is unavailable. Write tools require an explicit --allow-write launch."}, error=True)
        try:
            Draft202012Validator(tool.inputSchema).validate(arguments)
        except ValidationError:
            return _result({"status": "error", "code": "invalid_input", "message": "Arguments must match the tool's JSON types, limits and allowed fields."}, error=True)
        return await super().call_tool(name, arguments)


def create_server(client: ElectroChemClient, allow_write: bool = False) -> FastMCP:
    """Create a stdio server without contacting HTTP or starting a processing engine."""
    server = _StrictFastMCP(
        "ElectroChem", log_level="WARNING",
        instructions="Connect to the user's running local ElectroChem workspace. Start with get_processing_schema and preflight_process. "
                     "Do not invent experimental conditions. Exact input_files select primary files only; auxiliary sources are schema parameters. "
                     "Only start_process and export_report write results, and they exist only when the user enabled --allow-write. "
                     "After starting a job, poll get_job and use its reference.run_id/record_keys. Never infer the latest result belongs to that job. "
                     "This adapter never invokes the built-in AI, changes credentials, or deletes data.",
    )

    def register(*, write: bool = False):
        def decorate(function):
            @wraps(function)
            async def guarded(*args, **kwargs):
                try:
                    payload = await asyncio.to_thread(function, *args, **kwargs)
                    return _result(payload)
                except MCPClientError as exc:
                    return _result(exc.payload(), error=True)
                except (ValueError, TypeError):
                    return _result({"status": "error", "code": "invalid_input", "message": "Invalid tool input. Review the tool schema and processing preflight."}, error=True)
                except Exception:
                    return _result({"status": "error", "code": "adapter_error", "message": "The local adapter could not complete the operation. Refresh the service and job status before retrying a write."}, error=True)
            server.add_tool(guarded, annotations=ToolAnnotations(readOnlyHint=not write, destructiveHint=False,
                            idempotentHint=not write, openWorldHint=False), structured_output=False)
            return function
        return decorate

    @register()
    def list_projects(status: Literal["active", "archived", "all"] = "active", limit: Limit = 50, offset: Offset = 0) -> dict[str, Any]:
        """List a bounded page of local projects, including explicit total and has_more."""
        result = client.connect().request("GET", "/api/v1/projects", query={"status": status})
        projects = result.get("projects") or []
        return {"status": "success", "projects": projects[offset:offset + limit], "total": len(projects),
                "offset": offset, "limit": limit, "has_more": offset + limit < len(projects)}

    @register()
    def search_results(project_id: Identifier | None = None, data_type: DataType | None = None,
                       query: Annotated[str, Field(strict=True, max_length=256)] = "",
                       limit: Limit = 30, cursor: Annotated[str, Field(strict=True, max_length=8192)] | None = None,
                       include_archived: StrictBool = False) -> dict[str, Any]:
        """Find stored scientific results by project/type/text; follow next_cursor without assuming all records fit a page."""
        return client.connect().request("GET", "/api/v1/history", query={"project": project_id, "type": data_type,
                                       "q": query, "limit": limit, "cursor": cursor, "include_archived": int(include_archived)})

    @register()
    def get_result(record_key: RecordKey) -> dict[str, Any]:
        """Read one exact history record, with saved metrics, quality information and output paths."""
        return client.connect().request("GET", "/api/v1/history/" + _path_id(record_key))

    @register()
    def get_run(run_id: Identifier) -> dict[str, Any]:
        """Read the saved run recipe, effective parameters, input fingerprints, formulas and provenance; absent legacy fields stay absent."""
        return client.connect().request("GET", "/api/v1/runs/" + _path_id(run_id))

    @register()
    def get_processing_schema(data_types: Annotated[list[DataType], Field(min_length=1, max_length=5)] | None = None) -> dict[str, Any]:
        """Read the running engine's parameter keys, units, types, defaults and module descriptions; defaults are not inferred experimental facts."""
        return client.connect().request("GET", "/api/v1/process/schema", query={"data_types": ",".join(data_types) if data_types else None})

    @register()
    def list_templates(limit: Limit = 50, offset: Offset = 0) -> dict[str, Any]:
        """List saved processing templates without applying them or replacing scientific conditions."""
        result = client.connect().request("GET", "/api/v1/process/templates")
        templates = result.get("templates") or []
        return {"status": "success", "templates": templates[offset:offset + limit], "total": len(templates),
                "offset": offset, "limit": limit, "has_more": offset + limit < len(templates)}

    @register()
    def preflight_process(request: ProcessingRequest) -> dict[str, Any]:
        """Validate file selection and parameters without computing results. Existing engine preflight may create temporary permission/check files."""
        connection = client.connect()
        payload = _processing_payload(connection, request)
        return connection.request("POST", "/api/v1/process/preflight", payload=payload)

    @register()
    def list_jobs(status: Literal["all", "active", "queued", "running", "succeeded", "failed", "cancelled", "interrupted"] = "all",
                  limit: Limit = 30, offset: Offset = 0) -> dict[str, Any]:
        """List bounded processing task summaries, without assistant messages, raw payloads or credentials."""
        return client.connect().request("GET", "/api/v1/tasks", query={"kind": "process", "status": status, "limit": limit, "offset": offset})

    @register()
    def get_job(job_id: Identifier) -> dict[str, Any]:
        """Poll one processing job; reference.run_id/record_keys identify its exact results after completion."""
        result = client.connect().request("GET", "/api/v1/tasks/" + _path_id(job_id))
        if result.get("task", {}).get("kind") != "process":
            raise MCPClientError("unsupported_job", "Only scientific processing jobs are exposed by this adapter.")
        return result

    @register()
    def compare_results(left_record_key: RecordKey, right_record_key: RecordKey, project_id: Identifier | None = None) -> dict[str, Any]:
        """Compare two explicit saved records and their parameters, input identities and metrics; this POST creates no result or chart."""
        return client.connect().request("POST", "/api/v1/history/compare", payload={"left_record_key": left_record_key,
                                       "right_record_key": right_record_key, "project_id": project_id})

    if allow_write:
        @register(write=True)
        def start_process(request: ProcessingRequest) -> dict[str, Any]:
            """Recheck this exact payload, then start one asynchronous processing job in a new server-generated output directory. Do not retry blindly."""
            connection = client.connect()
            payload = _processing_payload(connection, request)
            preflight = connection.request("POST", "/api/v1/process/preflight", payload=payload)
            if preflight.get("preflight", {}).get("runnable") is not True:
                raise MCPClientError("preflight_failed", "The selected inputs or parameters are not runnable. Resolve the preflight issues before starting a job.", preflight)
            submitted = connection.request("POST", "/api/v1/process/jobs", payload=payload)
            job_id = submitted.get("job_id") or submitted.get("job", {}).get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise MCPClientError("invalid_service_response", "The service did not return a job identifier. Check list_jobs before retrying.")
            return {"status": "success", "job_id": job_id, "job_status": submitted.get("job", {}).get("status", "queued"),
                    "next_step": "Poll get_job(job_id); use its reference.run_id and record_keys for exact results."}

        @register(write=True)
        def export_report(run_id: Identifier | None = None, project_id: Identifier | None = None,
                          record_keys: Annotated[list[RecordKey], Field(min_length=1, max_length=100)] | None = None,
                          run_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)] | None = None,
                          format: Literal["html", "markdown"] = "html", include_archived: StrictBool = False) -> dict[str, Any]:
            """Create a local report for one run or an explicitly selected project scope; return the application's generated file paths."""
            if bool(run_id) == bool(project_id):
                raise MCPClientError("invalid_scope", "Choose exactly one run_id or project_id.")
            if run_id:
                if record_keys or run_ids or include_archived:
                    raise MCPClientError("invalid_scope", "Single-run reports do not accept project record/run selections or archived overrides.")
                return client.connect().request("POST", f"/api/v1/runs/{_path_id(run_id)}/report", payload={"format": format})
            if bool(record_keys) == bool(run_ids):
                raise MCPClientError("invalid_scope", "A project report requires exactly one explicit record_keys or run_ids selection.")
            result = client.connect().request("POST", f"/api/v1/projects/{_path_id(project_id or '')}/report",
                        payload={"record_keys": record_keys, "run_ids": run_ids, "format": format, "include_archived": include_archived})
            # Preview HTML is large and duplicates the generated files.
            result.pop("preview_html", None)
            return result

    return server


def run_server(*, base_url: str | None = None, data_dir: str | Path | None = None, allow_write: bool = False) -> None:
    """Run only MCP stdio. No engine imports, local HTTP listener, database or AI client."""
    create_server(ElectroChemClient(base_url=base_url, data_dir=data_dir), allow_write=allow_write).run(transport="stdio")


__all__ = ["ProcessingRequest", "create_server", "run_server"]

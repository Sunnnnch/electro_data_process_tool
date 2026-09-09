"""Validate and exercise a real frozen macOS bundle with isolated synthetic data."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import plistlib
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from macos_support import artifact_prefix, check_macho, read_app_version, sha256


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def bundle_snapshot(app: Path) -> dict:
    return {path.relative_to(app).as_posix(): {"link": os.readlink(path)} if path.is_symlink() else {"sha256": sha256(path)}
            for path in app.rglob("*") if path.is_file() or path.is_symlink()}


def isolated_environment(scratch: Path) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith("ELECTROCHEM_") and key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
    home = scratch / "home"
    home.mkdir()
    environment.update({"HOME": str(home), "ELECTROCHEM_V6_DATA_DIR": str(scratch / "data"),
                        "MPLCONFIGDIR": str(scratch / "matplotlib"), "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8"})
    return environment


def wait_for_service(process: subprocess.Popen, data: Path, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        require(process.poll() is None, "Frozen desktop exited before publishing its service")
        try:
            descriptor = json.loads((data / "desktop-service.json").read_text(encoding="utf-8"))
            require(descriptor.get("pid") == process.pid, "Service descriptor belongs to another process")
            url = str(descriptor["url"])
            require(url.startswith("http://127.0.0.1:") and url.rsplit(":", 1)[-1].isdigit(), "Invalid owned service URL")
            with opener.open(Request(url + "/health", headers={"X-Electrochem-Session": descriptor["session_token"]}), timeout=2) as response:
                payload = json.load(response)
            require(payload.get("status") in {"ok", "success"}, "Owned service health check failed")
            return descriptor
        except (FileNotFoundError, json.JSONDecodeError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.2)
    raise RuntimeError("Frozen desktop did not become ready within the startup limit")


def tool_output(result) -> dict:
    require(not result.isError and isinstance(result.structuredContent, dict), "MCP returned an error or invalid structured result")
    return result.structuredContent


async def exercise_mcp(executable: Path, data: Path, scratch: Path, environment: dict[str, str], *, prefix_args: tuple[str, ...] = ()) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    source = scratch / "CV_synthetic_selected.txt"
    rows = []
    for _ in range(2):
        rows.extend((k / 60, 0.001 * (k / 60)) for k in range(61))
        rows.extend((k / 60, -0.001 * (k / 60)) for k in range(59, -1, -1))
    source.write_text("\n".join(f"{v:.9f}\t{i:.9f}" for v, i in rows), encoding="utf-8")
    source_hash = sha256(source)
    (scratch / "CV_synthetic_unselected.txt").write_bytes(source.read_bytes())
    request = {"data_types": ["CV"], "folder_path": str(scratch), "project_name": "macOS synthetic MCP verification",
               "input_files": [{"path": str(source), "data_type": "CV"}],
               "params": {"cv_potential_column": 1, "cv_current_column": 2, "cv_potential_unit": "V",
                          "cv_current_unit": "A", "cv_scan_rate_v_s": 0.05}}
    evidence = {}
    for allow_write in (False, True):
        arguments = [*prefix_args, "--data-dir", str(data)] + (["--allow-write"] if allow_write else [])
        parameters = StdioServerParameters(command=str(executable), args=arguments, env=environment, cwd=str(scratch))
        with (scratch / f"mcp-{'write' if allow_write else 'read'}-stderr.log").open("w", encoding="utf-8") as stderr:
            async with stdio_client(parameters, errlog=stderr) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    initialized = await session.initialize()
                    require(initialized.serverInfo.name == "ElectroChem", "Unexpected MCP server identity")
                    tools = {tool.name for tool in (await session.list_tools()).tools}
                    require({"list_projects", "get_result", "get_job", "get_processing_schema"} <= tools, "Required MCP tools missing")
                    if not allow_write:
                        require("start_process" not in tools and "export_report" not in tools, "Read-only MCP exposed write tools")
                        require(tool_output(await session.call_tool("list_projects"))["total"] == 0, "Synthetic workspace is not empty")
                        evidence["read_only_handshake"] = "passed"
                        continue
                    require({"start_process", "export_report"} <= tools, "Opt-in MCP write tools missing")
                    checked = tool_output(await session.call_tool("preflight_process", {"request": request}))["preflight"]
                    require(checked["runnable"] and checked["selected_matched"] == 1, "CV preflight did not select the exact source")
                    submitted = tool_output(await session.call_tool("start_process", {"request": request}))
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        job = tool_output(await session.call_tool("get_job", {"job_id": submitted["job_id"]}))["task"]
                        if job["status"] not in {"queued", "running"}:
                            break
                        await asyncio.sleep(0.2)
                    require(job["status"] == "succeeded", "Frozen CV processing did not succeed")
                    reference = job["reference"]
                    require(len(reference["record_keys"]) == 1, "CV selected/unselected input isolation failed")
                    record = tool_output(await session.call_tool("get_result", {"record_key": reference["record_keys"][0]}))["record"]
                    run = tool_output(await session.call_tool("get_run", {"run_id": reference["run_id"]}))["run"]
                    require(Path(record["file_path"]).resolve() == source.resolve(), "CV record is not from the selected input")
                    require(run["params"]["cv_scan_rate_v_s"] == 0.05, "Saved recipe differs from actual request")
                    output = Path(run["output_dir"]).resolve()
                    require(output.is_relative_to(scratch.resolve()), "CV output escaped the isolated workspace")
                    files = [path for path in output.rglob("*") if path.is_file()]
                    require(any(path.suffix == ".png" and path.stat().st_size > 100 for path in files), "No real CV plot was generated")
                    results = record.get("results")
                    require(isinstance(results, dict) and results.get("data_points") == len(rows), "CV numerical result/input row count mismatch")
                    require(math.isfinite(float(results.get("charge_mC", float("nan")))) and results["charge_mC"] > 0,
                            "CV integration did not produce finite positive charge")
                    require(sha256(source) == source_hash, "Processing modified the synthetic input")
                    evidence.update({"write_opt_in": "passed", "synthetic_cv": "passed", "output_files": len(files),
                                     "record_count": 1, "data_points": results["data_points"], "charge_mC": results["charge_mC"],
                                     "input_sha256_unchanged": True})
    return evidence


def verify(app: Path, arch: str, evidence_dir: Path) -> dict:
    require(sys.platform == "darwin" and platform.machine() == arch, "Verification requires the matching native macOS runner")
    version = read_app_version(Path(__file__).resolve().parents[1])
    require(app.is_dir() and app.name == "ElectroChem.app", "Expected an ElectroChem.app directory")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    require(info.get("CFBundleExecutable") == "ElectroChem" and info.get("CFBundleShortVersionString") == version
            and info.get("CFBundleVersion") == version and info.get("LSMinimumSystemVersion") == "13.0", "Bundle metadata mismatch")
    main, mcp = app / "Contents/MacOS/ElectroChem", app / "Contents/MacOS/ElectroChem-MCP"
    for binary in (main, mcp):
        require(binary.is_file() and os.access(binary, os.X_OK), "Executable missing or not executable")
        check_macho(binary, arch, executable=True)
    count = 0
    for path in app.rglob("*"):
        if path.is_symlink():
            require(path.resolve().is_relative_to(app.resolve()), "Bundle contains a link outside itself")
        elif path.is_file() and check_macho(path, arch):
            count += 1
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", "--all-architectures", str(app)], check=True)
    signature = subprocess.run(["/usr/bin/codesign", "--display", "--verbose=4", str(app)], check=True, capture_output=True, text=True)
    require("Signature=adhoc" in signature.stderr and "Authority=" not in signature.stderr, "Unexpected signature mode")
    before = bundle_snapshot(app)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    environment = isolated_environment(evidence_dir)
    version_result = subprocess.run([str(main), "--version"], capture_output=True, text=True, check=True, timeout=60, env=environment, cwd=evidence_dir)
    require(version_result.stdout.strip() == version, "Frozen executable version mismatch")
    diagnostic_path = evidence_dir / "environment.json"
    subprocess.run([str(main), "--environment-check", "--json", "--output", str(diagnostic_path)], check=True,
                   capture_output=True, timeout=60, env=environment, cwd=evidence_dir)
    diagnostics = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    require(diagnostics["app_version"] == version and diagnostics["distribution"] == "packaged", "Diagnostic identity mismatch")
    require(diagnostics["can_start"] and diagnostics["can_use_embedded_window"], "Frozen Cocoa/WebKit diagnostics failed")
    data = evidence_dir / "data"
    require(Path(diagnostics["data_dir"]).resolve() == data.resolve() and not data.exists(), "Diagnostic data isolation failed")
    with (evidence_dir / "desktop-stdout.log").open("w", encoding="utf-8") as stdout, (evidence_dir / "desktop-stderr.log").open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen([str(main)], env=environment, cwd=evidence_dir, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            descriptor = wait_for_service(process, data)
            # Real TCP owner check prevents accidentally exercising another open client.
            ownership = subprocess.run(["/usr/sbin/lsof", "-nP", "-t", f"-iTCP:{descriptor['url'].rsplit(':', 1)[-1]}", "-sTCP:LISTEN"],
                                       check=True, capture_output=True, text=True)
            require(set(ownership.stdout.split()) == {str(process.pid)}, "TCP listener does not belong exclusively to the tested desktop")
            mcp_report = asyncio.run(asyncio.wait_for(exercise_mcp(mcp, data, evidence_dir, environment), timeout=240))
            require(process.poll() is None, "Desktop exited during MCP processing")
        finally:
            if process.poll() is None:
                # Cleanup only this newly spawned process group, never another app.
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
    require(bundle_snapshot(app) == before, "The app bundle was modified during execution")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    prefix = artifact_prefix(version, arch)
    build_report = json.loads((app.parent / f"{prefix}.build.json").read_text(encoding="utf-8"))
    expected_artifacts = {f"{prefix}.zip", f"{prefix}.dmg"}
    require({entry["name"] for entry in build_report["artifacts"]} == expected_artifacts, "Unexpected distribution assets")
    for entry in build_report["artifacts"]:
        artifact = app.parent / entry["name"]
        require(sha256(artifact) == entry["sha256"] and artifact.stat().st_size == entry["size_bytes"], "Distribution asset changed after building")
        require(artifact.with_name(artifact.name + ".sha256").read_text(encoding="ascii").strip()
                == f"{entry['sha256']}  {artifact.name}", "Distribution checksum mismatch")
    unpacked = evidence_dir / "zip-unpacked"
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(app.parent / f"{prefix}.zip"), str(unpacked)], check=True)
    require(bundle_snapshot(unpacked / "ElectroChem.app") == before, "ZIP did not preserve the validated app or its symlinks")
    subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(unpacked / "ElectroChem.app")], check=True)
    subprocess.run(["/usr/bin/hdiutil", "verify", str(app.parent / f"{prefix}.dmg")], check=True)
    return {"status": "passed", "app_version": version, "architecture": arch, "runner_macos": platform.mac_ver()[0],
            "minimum_macos": "13.0", "minimum_os_device_tested": False, "native_binary_count": count,
            "executable_version": "passed", "environment_check": "passed", "data_outside_bundle": True,
            "bundle_unchanged": True, "zip_roundtrip": "passed", "dmg_integrity": "passed",
            "mcp": mcp_report, "signature": "ad-hoc", "notarized": False,
            "native_window_lifecycle": "separate smoke required; SIGTERM used only for test cleanup",
            "public_release_eligible": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--arch", choices=["arm64", "x86_64"], required=True)
    parser.add_argument("--output", type=Path, required=True, help="New JSON report; related evidence is stored beside it")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    require(not output.exists(), "Verification report exists; choose a fresh output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = verify(args.app.expanduser().resolve(), args.arch, output.with_suffix(".evidence"))
    except Exception as exc:
        # Avoid copying data/credentials from nested MCP/HTTP exception strings.
        report = {"status": "failed", "architecture": args.arch, "error_type": type(exc).__name__,
                  "message": str(exc) if type(exc) in {RuntimeError, ValueError} else "See preserved build/runtime diagnostics"}
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

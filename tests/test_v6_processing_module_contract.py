from electrochem_v6.core.processing_module_contract import (
    ModuleRunContext,
    ModuleRunResult,
    ProcessingModule,
)
from electrochem_v6.core.processing_registry import ProcessingModuleSpec
from electrochem_v6.core.processing_result_models import MetricValue, ProcessingResult


class _DemoModule:
    spec = ProcessingModuleSpec("DEMO", "demo_enabled")

    def detect_files(self, context):
        return [context.folder_path + "/demo.txt"]

    def validate_params(self, context):
        return []

    def run(self, context, files):
        return ModuleRunResult(
            data_type="DEMO",
            results=(
                ProcessingResult(
                    data_type="DEMO",
                    sample_name="sample-a",
                    metrics=(MetricValue(key="demo_metric", value=1.0),),
                ),
            ),
            artifacts=("demo.png",),
            messages=("ok",),
        )


def test_processing_module_protocol_and_result_shape():
    module = _DemoModule()
    context = ModuleRunContext(folder_path="D:/data", params={"area": 1.0}, run_id="run-1")

    assert isinstance(module, ProcessingModule)
    files = module.detect_files(context)
    result = module.run(context, files)
    payload = result.to_dict()

    assert payload["data_type"] == "DEMO"
    assert payload["results"][0]["metrics"][0]["key"] == "demo_metric"
    assert payload["artifacts"] == ["demo.png"]
    assert payload["messages"] == ["ok"]


def test_module_run_result_metadata_is_json_ready():
    result = ModuleRunResult(
        data_type="DEMO",
        quality_reports=({"flags": {"ok", "check"}},),
        metadata={
            1: ("formula.a", "formula.b"),
            "nested": {"values": {2, 1}},
        },
    )

    payload = result.to_dict()

    assert payload["metadata"]["1"] == ["formula.a", "formula.b"]
    assert sorted(payload["metadata"]["nested"]["values"]) == [1, 2]
    assert sorted(payload["quality_reports"][0]["flags"]) == ["check", "ok"]

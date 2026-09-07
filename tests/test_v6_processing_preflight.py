from electrochem_v6.core.processing_preflight import (
    add_coupled_preflight,
    build_preflight_checks,
    finalize_preflight_scan,
    matched_counts_from_preflight,
)


def test_add_coupled_preflight_preserves_scan_and_adds_table_match():
    scan = {
        "selected_matched": 2,
        "by_type": {"LSV": {"matched": 2, "examples": ["LSV_1.txt"]}},
    }

    updated = add_coupled_preflight(scan, "D:/data/products.csv")

    assert updated["selected_matched"] == 3
    assert updated["by_type"]["LSV"]["matched"] == 2
    assert updated["by_type"]["COUPLED"]["matched"] == 1
    assert updated["by_type"]["COUPLED"]["match"] == "product_table"
    assert updated["by_type"]["COUPLED"]["examples"] == ["D:/data/products.csv"]


def test_finalize_preflight_scan_adds_counts_checks_and_runnable_state():
    scan = {
        "selected_matched": 1,
        "warnings": [],
        "by_type": {
            "LSV": {"matched": 1},
            "CV": {"matched": 0},
        },
    }

    finalized = finalize_preflight_scan(scan, data_types=["LSV", "CV"])

    assert matched_counts_from_preflight(finalized) == {"LSV": 1, "CV": 0}
    assert finalized["matched_counts"] == {"LSV": 1, "CV": 0}
    assert finalized["matched_files"] == 1
    assert finalized["runnable"] is True
    assert finalized["checks"]["file_recognition"]["status"] == "pass"
    assert finalized["checks"]["param_completeness"]["status"] == "pass"
    assert finalized["checks"]["output_dir"]["status"] == "normal"
    assert finalized["checks"]["runnable"]["status"] == "yes"


def test_build_preflight_checks_marks_warning_or_error_as_not_runnable():
    scan = {
        "selected_matched": 1,
        "warnings": ["EIS 未匹配到文件"],
        "by_type": {"EIS": {"matched": 0}},
    }

    checks = build_preflight_checks(scan, param_error="bad parameter")

    assert checks["file_recognition"]["ok"] is False
    assert checks["file_recognition"]["status"] == "check"
    assert checks["param_completeness"]["ok"] is False
    assert checks["runnable"]["ok"] is False
    assert checks["runnable"]["status"] == "no"

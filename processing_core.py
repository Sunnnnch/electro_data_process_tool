"""Backward-compatible shim for migrated v6 processing core."""

from __future__ import annotations

from electrochem_v6.core import processing_core_v6 as _impl

ElectroChemException = _impl.ElectroChemException
DataProcessingError = _impl.DataProcessingError
FileFormatError = _impl.FileFormatError
ParameterError = _impl.ParameterError
DataQualityError = _impl.DataQualityError
HISTORY_MANAGER_AVAILABLE = _impl.HISTORY_MANAGER_AVAILABLE
PROJECT_MANAGER_AVAILABLE = _impl.PROJECT_MANAGER_AVAILABLE
LOG_FILE_PATH = _impl.LOG_FILE_PATH

setup_logger = _impl.setup_logger
get_logger = _impl.get_logger
setup_chinese_font = _impl.setup_chinese_font
set_log_folder = _impl.set_log_folder
log = _impl.log
auto_detect_data_start = _impl.auto_detect_data_start
resolve_data_start_line = _impl.resolve_data_start_line
process_lsv = _impl.process_lsv
process_cv = _impl.process_cv
process_eis = _impl.process_eis
process_ecsa_for_subfolder = _impl.process_ecsa_for_subfolder
get_history_manager = _impl.get_history_manager
get_project_manager = _impl.get_project_manager
_matches_named_file = _impl._matches_named_file


def run_pipeline(*args, **kwargs):
    original = {
        "resolve_data_start_line": _impl.resolve_data_start_line,
        "process_lsv": _impl.process_lsv,
        "process_cv": _impl.process_cv,
        "process_eis": _impl.process_eis,
        "process_ecsa_for_subfolder": _impl.process_ecsa_for_subfolder,
        "get_history_manager": _impl.get_history_manager,
        "get_project_manager": _impl.get_project_manager,
    }
    _impl.resolve_data_start_line = resolve_data_start_line
    _impl.process_lsv = process_lsv
    _impl.process_cv = process_cv
    _impl.process_eis = process_eis
    _impl.process_ecsa_for_subfolder = process_ecsa_for_subfolder
    _impl.get_history_manager = get_history_manager
    _impl.get_project_manager = get_project_manager
    try:
        return _impl.run_pipeline(*args, **kwargs)
    finally:
        _impl.resolve_data_start_line = original["resolve_data_start_line"]
        _impl.process_lsv = original["process_lsv"]
        _impl.process_cv = original["process_cv"]
        _impl.process_eis = original["process_eis"]
        _impl.process_ecsa_for_subfolder = original["process_ecsa_for_subfolder"]
        _impl.get_history_manager = original["get_history_manager"]
        _impl.get_project_manager = original["get_project_manager"]

__all__ = [
    "ElectroChemException",
    "DataProcessingError",
    "FileFormatError",
    "ParameterError",
    "DataQualityError",
    "HISTORY_MANAGER_AVAILABLE",
    "PROJECT_MANAGER_AVAILABLE",
    "LOG_FILE_PATH",
    "setup_logger",
    "get_logger",
    "setup_chinese_font",
    "set_log_folder",
    "log",
    "auto_detect_data_start",
    "resolve_data_start_line",
    "process_lsv",
    "process_cv",
    "process_eis",
    "process_ecsa_for_subfolder",
    "run_pipeline",
    "get_history_manager",
    "get_project_manager",
    "_matches_named_file",
]

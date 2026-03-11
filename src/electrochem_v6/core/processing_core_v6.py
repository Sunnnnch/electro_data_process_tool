"""Compatibility entrypoint for ElectroChem processing modules.

This module now keeps shared utilities, logging, plotting helpers, and
re-exports the domain-specific processing functions from split modules.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use('Agg')  # non-interactive backend for headless environments
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.ft2font import FT2Font


def _safe_print(msg: str) -> None:
    """Log that never crashes on non-UTF-8 terminals (e.g. cp1252 in CI)."""
    _init_logger = logging.getLogger('ElectroChem')
    if _init_logger.handlers:
        _init_logger.info(msg)
        return
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", errors="replace").decode("ascii", errors="replace"))

from .processing_pipeline import (
    NumpyEncoder,
    _as_bool,
    auto_detect_data_start,
    natural_sort_key,
    resolve_data_start_line,
    run_pipeline,
)
from .processing_quality import DataQualityChecker


# ======================
# Custom Exception Classes
# ======================
class ElectroChemException(Exception):
    """Base exception for ElectroChem processing errors."""
    pass


class DataProcessingError(ElectroChemException):
    """Raised when data processing fails (calculation errors, invalid data)."""
    pass


class FileFormatError(ElectroChemException):
    """Raised when file format is invalid or cannot be parsed."""
    pass


class ParameterError(ElectroChemException):
    """Raised when parameters are invalid or missing."""
    pass


class DataQualityError(ElectroChemException):
    """Raised when data quality checks fail critically."""
    pass

# Optional numpy imports are performed lazily inside individual functions to
# keep import time low when the full scientific stack is unavailable.

# Import history and project manager
try:
    from electrochem_v6.store.legacy_runtime import get_history_manager_v6 as get_history_manager
    HISTORY_MANAGER_AVAILABLE = True
except ImportError:
    HISTORY_MANAGER_AVAILABLE = False
    get_history_manager = None

try:
    from electrochem_v6.store.legacy_runtime import get_project_manager_v6 as get_project_manager
    PROJECT_MANAGER_AVAILABLE = True
except ImportError:
    PROJECT_MANAGER_AVAILABLE = False
    get_project_manager = None

LOG_FILE_PATH: Optional[str] = None
PLOT_OUTPUT_SUBDIR = Path("artifacts") / "quality_plots"
_VISION_CLIENT_CACHE = None
_VISION_CFG_CACHE: Optional[Dict[str, Any]] = None
_VISION_DISABLED = False


# ======================
# Logging Configuration
# ======================
def setup_logger(log_dir: Optional[str] = None, log_level: int = logging.INFO) -> logging.Logger:
    """Configure structured logging system with file rotation.

    Args:
        log_dir: Directory for log files. If None, uses current directory.
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
                   Can also be overridden via the ``ELECTROCHEM_V6_LOG_LEVEL``
                   environment variable (e.g. ``DEBUG``, ``WARNING``).

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger('ElectroChem')

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    # Allow env-var override: ELECTROCHEM_V6_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
    env_level = os.environ.get('ELECTROCHEM_V6_LOG_LEVEL', '').upper()
    if env_level and hasattr(logging, env_level):
        log_level = getattr(logging, env_level)

    logger.setLevel(log_level)

    # File handler with rotation (max 10MB per file, keep 5 backups)
    if log_dir is None:
        log_dir = os.getcwd()
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, 'electrochem.log')
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)

    # Console handler (only warnings and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter('[%(levelname)s] %(message)s')
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("=" * 60)
    logger.info("ElectroChem Data Processing Logger Initialized")
    logger.info(f"Log file: {log_file}")
    logger.info("=" * 60)

    return logger


# Initialize logger
_logger = None

def get_logger() -> logging.Logger:
    """Get or create the global logger instance."""
    global _logger
    if _logger is None:
        _logger = setup_logger()
    return _logger


def setup_chinese_font():
    """设置matplotlib的中文字体支持"""
    try:
        # Windows系统常见中文字体
        chinese_fonts = [
            'Microsoft YaHei',  # 微软雅黑
            'SimHei',  # 黑体
            'SimSun',  # 宋体
            'KaiTi',  # 楷体
            'FangSong',  # 仿宋
            'DejaVu Sans',  # 备选字体
        ]

        # 查找可用的中文字体
        available_fonts = [f.name for f in fm.fontManager.ttflist]

        for font_name in chinese_fonts:
            if font_name in available_fonts:
                plt.rcParams['font.sans-serif'] = [font_name]
                plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
                _safe_print(f"成功设置中文字体: {font_name}")
                return font_name

        # 如果没有找到预设字体，尝试查找任何支持中文的字体
        for font in fm.fontManager.ttflist:
            if 'CJK' in font.name or '中文' in font.name or any(
                    cn in font.name for cn in ['微软', '宋体', '黑体', '楷体']):
                plt.rcParams['font.sans-serif'] = [font.name]
                plt.rcParams['axes.unicode_minus'] = False
                _safe_print(f"找到中文字体: {font.name}")
                return font.name

        _safe_print("警告: 未找到合适的中文字体，中文可能显示为方框")
        return 'Arial'  # 默认字体

    except Exception as e:
        _safe_print(f"设置中文字体时出错: {e}")
        return 'Arial'


CHINESE_FONT = setup_chinese_font()
_AVAILABLE_FONT_NAMES = {f.name for f in fm.fontManager.ttflist}
_FONT_TEXT_SUPPORT_CACHE: Dict[Tuple[str, str], bool] = {}


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))


def _matches_named_file(filename: str, mode: str, pattern: str) -> bool:
    """Return True when a file name matches the requested strategy."""
    name = str(filename or "")
    mode_norm = str(mode or "prefix").strip().lower()
    raw_pattern = str(pattern or "").strip()
    if not name or not raw_pattern:
        return False
    lower_name = name.lower()
    lower_pattern = raw_pattern.lower()
    if mode_norm == "prefix":
        return lower_name.startswith(lower_pattern)
    if mode_norm == "suffix":
        return lower_name.endswith(lower_pattern) or lower_name.endswith(lower_pattern + ".txt") or lower_name.endswith(lower_pattern + ".csv")
    if mode_norm == "contains":
        return lower_pattern in lower_name
    if mode_norm == "regex":
        try:
            return re.search(raw_pattern, name, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return lower_name.startswith(lower_pattern)


def _font_supports_text(font_name: str, text: str) -> bool:
    probe = "".join(sorted(set(ch for ch in str(text or "") if "\u4e00" <= ch <= "\u9fff")))
    if not probe:
        return True
    key = (font_name, probe)
    cached = _FONT_TEXT_SUPPORT_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        font_path = fm.findfont(font_name, fallback_to_default=False)
        cmap = FT2Font(font_path).get_charmap()
        supported = all(ord(ch) in cmap for ch in probe)
    except Exception:
        supported = False
    _FONT_TEXT_SUPPORT_CACHE[key] = supported
    return supported


def _resolve_plot_font(preferred_font: Any, fallback: str = CHINESE_FONT, text: str = "") -> str:
    """Resolve a plotting font that exists on current machine."""
    name = str(preferred_font or "").strip()
    fallback_name = str(fallback or "").strip() or "DejaVu Sans"

    if name and name in _AVAILABLE_FONT_NAMES:
        chosen = name
    elif fallback_name in _AVAILABLE_FONT_NAMES:
        chosen = fallback_name
    else:
        chosen = "DejaVu Sans"

    if _contains_cjk(text) and not _font_supports_text(chosen, text):
        cjk_candidates = [
            fallback_name,
            "Microsoft YaHei",
            "SimHei",
            "Noto Sans SC",
            "Noto Sans CJK SC",
            "WenQuanYi Zen Hei",
            "Arial Unicode MS",
            "DejaVu Sans",
        ]
        for candidate in cjk_candidates:
            if candidate in _AVAILABLE_FONT_NAMES and _font_supports_text(candidate, text):
                return candidate
    return chosen


def _sanitize_filename(name: str) -> str:
    """Convert arbitrary filename to filesystem-friendly format."""
    if not name:
        return "unknown"
    # Strip directory components to prevent path traversal
    base = os.path.basename(name)
    safe = re.sub(r"[^A-Za-z0-9_.\-]+", "_", base)
    # Prevent hidden files
    safe = safe.lstrip(".")
    return safe or "unknown"


def save_waveform_plot(
    df: pd.DataFrame,
    file_name: str,
    noise_analysis: Dict[str, Any],
    base_dir: Optional[Path] = None,
) -> Optional[str]:
    """Save waveform figure highlighting noisy sections."""
    try:
        if base_dir is None:
            base_dir = Path(os.getcwd()) / PLOT_OUTPUT_SUBDIR
        safe_name = _sanitize_filename(file_name)
        plot_path = base_dir / f"{safe_name}.png"
        counter = 1
        while plot_path.exists():
            plot_path = base_dir / f"{safe_name}_{counter}.png"
            counter += 1
        plot_path.parent.mkdir(parents=True, exist_ok=True)

        plt.figure(figsize=(8, 5))
        plt.plot(
            df["Potential"].to_numpy(),
            df["Current"].to_numpy(),
            label="Current vs Potential",
            color="#1f77b4",
        )
        plt.xlabel("Potential (V)")
        plt.ylabel("Current")
        plt.title(f"Waveform Quality Check - {file_name or 'unknown'}")
        plt.grid(True, alpha=0.3)

        segment = noise_analysis.get("issue_position")
        if isinstance(segment, (list, tuple)) and len(segment) == 2:
            start_idx = max(int(segment[0]), 0)
            end_idx = min(int(segment[1]), len(df) - 1)
            if end_idx > start_idx:
                potentials = df["Potential"].iloc[start_idx : end_idx + 1].values
                currents = df["Current"].iloc[start_idx : end_idx + 1].values
                plt.plot(
                    potentials,
                    currents,
                    color="#d62728",
                    linewidth=3,
                    label="Detected fluctuation",
                )

        quality = noise_analysis.get("overall_quality", "unknown")
        noise_level = noise_analysis.get("noise_level", "n/a")
        plt.legend()
        plt.text(
            0.02,
            0.98,
            f"Quality: {quality}\nNoise level: {noise_level}",
            transform=plt.gca().transAxes,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.7),
        )

        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()
        return str(plot_path)
    except Exception as exc:
        logger = get_logger()
        logger.warning(f"Failed to generate waveform plot for {file_name}: {exc}")
        return None


def _get_vision_client():
    global _VISION_CLIENT_CACHE, _VISION_CFG_CACHE, _VISION_DISABLED
    if _VISION_DISABLED:
        return None, None
    if _VISION_CLIENT_CACHE is not None:
        return _VISION_CLIENT_CACHE, _VISION_CFG_CACHE
    try:
        from electrochem_v6.llm.config import LLMConfig
        from electrochem_v6.llm.vision_client import VisionClient
    except Exception:
        _VISION_DISABLED = True
        return None, None
    cfg = LLMConfig()
    if not cfg.is_vision_enabled():
        _VISION_DISABLED = True
        return None, None
    api_key = cfg.get_vision_api_key()
    if not api_key:
        _VISION_DISABLED = True
        return None, None
    vision_cfg = cfg.get_vision_config()
    try:
        client = VisionClient(
            api_key=api_key,
            model=vision_cfg.get("model", "gpt-4o-mini"),
            base_url=vision_cfg.get("base_url", "https://api.openai.com/v1"),
            timeout=int(vision_cfg.get("timeout", 60)),
        )
    except Exception as exc:
        get_logger().warning(f"初始化视觉模型失败: {exc}")
        _VISION_DISABLED = True
        return None, None
    _VISION_CLIENT_CACHE = client
    _VISION_CFG_CACHE = vision_cfg
    return client, vision_cfg


def run_vision_analysis(image_path: str, file_name: str, noise_analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    client, vision_cfg = _get_vision_client()
    if client is None:
        return None

    context_parts = [
        f"文件: {file_name}",
        f"整体质量: {noise_analysis.get('overall_quality')}",
        f"噪声水平: {noise_analysis.get('noise_level')}",
        f"突变比例: {noise_analysis.get('jump_ratio')}",
    ]
    if noise_analysis.get('local_issue'):
        context_parts.append(f"局部抖动区域: {noise_analysis.get('issue_position')}")
    context = "\n".join([str(part) for part in context_parts if part and part != 'None'])

    max_tokens = int((vision_cfg or {}).get("max_tokens", 800))
    result = client.analyze_image(image_path=image_path, prompt=context, max_tokens=max_tokens)
    result["model"] = (vision_cfg or {}).get("model")
    result["image_path"] = image_path
    result["context"] = context
    return result


# ======================
# Data Quality Checker
# ======================

def set_log_folder(folder):
    global LOG_FILE_PATH
    try:
        os.makedirs(folder, exist_ok=True)
        LOG_FILE_PATH = os.path.join(folder, 'processing.log')
        with open(LOG_FILE_PATH, 'a', encoding='utf-8') as _f:
            _f.write('\n--- processing start ---\n')
    except Exception:
        LOG_FILE_PATH = None

def log(msg):
    """Legacy log function - now uses structured logger."""
    text = str(msg)
    try:
        get_logger().info(text)
    except Exception:
        pass  # Fallback to silent failure
    finally:
        try:
            if LOG_FILE_PATH:
                with open(LOG_FILE_PATH, 'a', encoding='utf-8') as _f:
                    _f.write(text + '\n')
        except Exception:
            pass



# Domain processing modules are re-exported here to preserve the historic
# `processing_core` import surface used by the server, tests, and shim layer.
from .processing_cv import process_cv
from .processing_ecsa import (
    _extract_sample_token,
    _match_eis_by_sample,
    process_ecsa_for_subfolder,
)
from .processing_eis import process_eis
from .processing_lsv import (
    _filter_outliers,
    _parse_tafel_range,
    get_ir_from_eis,
    interpolate_multiple_potentials,
    interpolate_potential,
    parse_target_currents,
    potential_at_current,
    process_lsv,
)

__all__ = [
    'CHINESE_FONT',
    'LOG_FILE_PATH',
    'DataQualityChecker',
    'setup_chinese_font',
    'natural_sort_key',
    'set_log_folder',
    'log',
    'interpolate_potential',
    'parse_target_currents',
    'interpolate_multiple_potentials',
    'potential_at_current',
    'get_ir_from_eis',
    'process_lsv',
    'process_cv',
    'process_eis',
    'process_ecsa_for_subfolder',
    'auto_detect_data_start',
    'resolve_data_start_line',
    'run_pipeline',
]

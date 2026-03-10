"""
Tool definitions for AI agent (OpenAI Function Calling format).
定义AI可调用的工具函数。
"""

# 基础工具:数据查询和管理
BASIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_lsv_summary",
            "description": "查询LSV数据汇总,获取所有样品的性能数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "项目ID,不提供则查询所有项目"
                    },
                    "sort_by": {
                        "type": "string",
                        "enum": ["eta", "tafel"],
                        "description": "排序方式"
                    },
                    "top_n": {
                        "type": "integer",
                        "description": "只返回性能最好的前N个"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_best_catalysts",
            "description": "找出性能最优的催化剂。如果不指定项目ID,则查询所有项目的数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "项目ID(可选)。如果要查询所有项目,不提供此参数或传null"
                    },
                    "count": {
                        "type": "integer",
                        "description": "返回前N个,默认5"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_catalysts",
            "description": "对比多个催化剂的性能",
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "样品名称列表"
                    }
                },
                "required": ["sample_names"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_project_summary",
            "description": "查询当前 v6 项目的摘要信息，包括统计、最近历史和主要 LSV 指标。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "v6 项目 ID。"
                    },
                    "project_name": {
                        "type": "string",
                        "description": "v6 项目名称；未提供项目 ID 时按名称匹配。"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_project_history",
            "description": "查询当前 v6 项目的最近历史记录，可按数据类型筛选。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "v6 项目 ID。"
                    },
                    "project_name": {
                        "type": "string",
                        "description": "v6 项目名称；未提供项目 ID 时按名称匹配。"
                    },
                    "record_type": {
                        "type": "string",
                        "enum": ["LSV", "CV", "EIS", "ECSA"],
                        "description": "可选的数据类型过滤。"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少条记录，默认 10。"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_compare_selection",
            "description": "获取当前 v6 项目的 LSV 对比候选数据。若不提供样品名，则返回项目内最适合对比的样品行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "v6 项目 ID。"
                    },
                    "project_name": {
                        "type": "string",
                        "description": "v6 项目名称；未提供项目 ID 时按名称匹配。"
                    },
                    "sample_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选的样品名称列表，用于缩小对比范围。"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "未提供样品名时最多返回多少个样品，默认 5。"
                    }
                },
                "required": []
            }
        }
    }
]

# 增强工具:让AI能"看"数据并自主处理
ENHANCED_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "scan_data_folder",
            "description": "扫描数据文件夹,返回文件列表和统计信息。这是分析数据的第一步",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "数据文件夹路径"
                    }
                },
                "required": ["folder_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "preview_data_file",
            "description": "预览数据文件的前N行,用于分析数据格式",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "预览行数,默认20"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_data_characteristics",
            "description": "深度分析数据文件特征(电流范围、电位窗口等),用于智能决定处理参数",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["LSV", "CV", "EIS", "ECSA"],
                        "description": "数据类型"
                    }
                },
                "required": ["file_path", "data_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "auto_process_with_smart_params",
            "description": "AI自主决定参数并处理数据。会先分析数据特征,然后自动选择最优参数执行处理。用户可以指定关键参数如电位偏移、电极面积等",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "数据文件夹路径"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["LSV", "CV", "EIS", "ECSA"],
                        "description": "数据类型"
                    },
                    "project_name": {
                        "type": "string",
                        "description": "项目名称,如不提供则使用文件夹名"
                    },
                    "potential_offset": {
                        "type": "number",
                        "description": "电位偏移(V),例如1.001表示vs RHE换算"
                    },
                    "electrode_area": {
                        "type": "number",
                        "description": "电极面积(cm²),默认1.0"
                    },
                    "target_current": {
                        "type": "string",
                        "description": "目标电流密度(mA/cm²),例如'10,100'"
                    },
                    "tafel_range": {
                        "type": "string",
                        "description": "Tafel拟合范围(mA/cm²),例如'1-10'"
                    }
                },
                "required": ["folder_path", "data_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_project",
            "description": "创建新项目",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "项目名称"
                    },
                    "description": {
                        "type": "string",
                        "description": "项目描述"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_processing_history",
            "description": "获取处理历史记录",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "项目ID,不提供则返回所有"
                    },
                    "record_type": {
                        "type": "string",
                        "enum": ["LSV", "CV", "EIS", "ECSA"],
                        "description": "记录类型筛选"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回最近N条,默认20"
                    }
                }
            }
        }
    }
]

# 智能分析工具:质量报告和总结
ANALYSIS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_quality_report",
            "description": "读取最近的数据质量检测报告,了解处理结果的质量情况",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "enum": ["latest", "all"],
                        "description": "报告类型:latest(最新)或all(所有)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_processing_results",
            "description": "综合分析最近的数据处理结果,包括质量报告和性能数据,给出专业总结",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_quality": {
                        "type": "boolean",
                        "description": "是否包含质量分析,默认true"
                    },
                    "include_performance": {
                        "type": "boolean",
                        "description": "是否包含性能分析,默认true"
                    }
                },
                "required": []
            }
        }
    }
]

# 催化剂中心工具:以样品为核心的查询
CATALYST_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_catalyst_info",
            "description": "获取催化剂的完整信息,自动查询该样品的所有可用数据(LSV/CV/EIS/ECSA)",
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_name": {
                        "type": "string",
                        "description": "样品名称,例如:Sample_A"
                    },
                    "include_details": {
                        "type": "boolean",
                        "description": "是否包含详细数据,默认true"
                    }
                },
                "required": ["sample_name"]
            }
        }
    }
]

# 视觉分析工具
VISION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_waveform_image",
            "description": "对诊断图进行视觉分析，判断波动是否异常并提供原因",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "诊断图像的绝对路径"
                    },
                    "context": {
                        "type": "string",
                        "description": "可选的上下文描述，例如噪声指标、文件名等"
                    }
                },
                "required": ["image_path"]
            }
        }
    }
]

# 合并所有工具
ALL_TOOLS = BASIC_TOOLS + ENHANCED_TOOLS + ANALYSIS_TOOLS + CATALYST_TOOLS + VISION_TOOLS

__all__ = ["BASIC_TOOLS", "ENHANCED_TOOLS", "ANALYSIS_TOOLS", "CATALYST_TOOLS", "VISION_TOOLS", "ALL_TOOLS"]



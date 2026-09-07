"""
Tool definitions for AI agent (OpenAI Function Calling format).
定义AI可调用的工具函数。
"""

# 基础工具:数据查询和管理
BASIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_professional_mode_context",
            "description": (
                "按需读取用户当前界面的专业模式摘要，包括已选数据文件名和类型、模板、处理参数、"
                "预检状态及结果摘要，不包含原始文件内容。仅当用户询问当前设置、当前参数、当前预检、"
                "当前处理结果，或明确指代专业模式界面时调用；一般知识问答和纯数据库查询不要调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
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
                        "enum": ["LSV", "CV", "EIS", "ECSA", "COUPLED"],
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
            "description": "按明确实验条件分析数据并提供候选参数及限制。缺少条件时先补全；候选不代表最优参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件路径"
                    },
                    "params": {"type": "object", "description": "已确认的正式处理参数，含单位、面积、列映射和补偿条件，不推测缺失实验条件"},
                    "run_id": {"type": "string", "description": "可选，读取指定已保存运行的有效参数"},
                    "data_type": {
                        "type": "string",
                        "enum": ["LSV", "CV", "EIS", "ECSA", "COUPLED"],
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
            "description": "按用户明确的实验条件和处理参数准备处理确认。仅在用户确认后执行；不会自动推断缺失实验条件或保证最优参数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "folder_path": {
                        "type": "string",
                        "description": "数据文件夹路径"
                    },
                    "data_type": {
                        "type": "string",
                        "enum": ["LSV", "CV", "EIS", "ECSA", "COUPLED"],
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
                    },
                    "coupled_products_file": {
                        "type": "string",
                        "description": "Product quantification table path for COUPLED/FE calculation"
                    },
                    "coupled_products_sheet": {
                        "type": "string",
                        "description": "Excel sheet name or index for the product quantification table"
                    },
                    "coupled_results_csv_filename": {
                        "type": "string",
                        "description": "Output CSV file name for COUPLED/FE results"
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
                        "enum": ["LSV", "CV", "EIS", "ECSA", "COUPLED"],
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
                    "project_id": {"type": "string", "description": "明确的项目ID；同名样品跨项目时必须指定，复算版本不当作独立重复实验。"},
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

ACTION_TOOLS = [
    {"type": "function", "function": {
        "name": "propose_parameter_changes",
        "description": "生成当前专业模式参数建议卡，显示当前值、建议值和理由；不修改界面或处理数据。Tafel区间必须来自本轮已验证候选；缺实验条件时先补全。用户随后预览并确认应用，保留输入来源。",
        "parameters": {"type": "object", "properties": {"changes": {"type": "array", "items": {
            "type": "object", "properties": {"key": {"type": "string"}, "value": {}, "reason": {"type": "string"}},
            "required": ["key", "value", "reason"], "additionalProperties": False,
        }}}, "required": ["changes"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "prepare_record_comparison", "description": "为恰好两条明确历史记录生成比较预览卡。必须使用当前项目与所选record_keys，不以样品名称或最新记录替代。用户点击后打开比较视图。",
        "parameters": {"type": "object", "properties": {"project_id": {"type": "string"}, "record_keys": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2}}, "required": ["record_keys"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "prepare_run_replay", "description": "为明确运行或其单条记录生成复算计划卡，检查原来源与参数差异，不启动任务。用户打开既有复算对话框重新预检并确认，新结果保留旧版本。",
        "parameters": {"type": "object", "properties": {"project_id": {"type": "string"}, "run_id": {"type": "string"}, "record_key": {"type": "string"}, "params": {"type": "object"}}, "required": ["run_id"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "prepare_result_report", "description": "为当前项目明确勾选的历史record_keys生成报告范围卡。仅这些结果，不能扩大为整批次或整项目；用户点击后在报告界面确认导出。",
        "parameters": {"type": "object", "properties": {"project_id": {"type": "string"}, "record_keys": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 200}}, "required": ["record_keys"], "additionalProperties": False},
    }},
]

# 合并所有工具
ALL_TOOLS = BASIC_TOOLS + ENHANCED_TOOLS + ANALYSIS_TOOLS + CATALYST_TOOLS + VISION_TOOLS + ACTION_TOOLS

__all__ = ["BASIC_TOOLS", "ENHANCED_TOOLS", "ANALYSIS_TOOLS", "CATALYST_TOOLS", "VISION_TOOLS", "ALL_TOOLS"]

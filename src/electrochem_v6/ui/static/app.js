let currentConversationId = null;
let conversationItems = [];
let hasProcessResult = false;
let templateItems = [];
let historyRecords = [];
let selectedHistoryKey = "";
let currentConversationKeyword = "";
let llmModelsByProvider = {};
let renamingConversationId = null;
let projectItems = [];
let selectedProjectId = "";
let projectDetailState = null;
let selectedProjectHistoryKey = "";
let projectIncludeArchived = false;
let projectOutputTypeFilter = "";
let projectCompareSort = "eta";
let projectCompareOnlyEta = false;
let projectCompareOnlyTafel = false;
let projectCompareSelectedSamples = [];
let projectComparePlotData = null;
let projectComparePlotLoading = false;
let projectCompareChartType = "overlay";
let projectCompareMetric = "potential_at_target";
let projectCompareTargetCurrent = "10";
let projectCompareTargetCurrents = {
  target_currents: [],
  potential_target_currents: [],
  overpotential_target_currents: [],
};
let helpDocCache = {};
let activeHelpHeadingId = "";

const PROMPT_STORAGE_KEY = "electrochem_v6_prompt_settings";
const PROMPT_TEMPLATES = {
  analyst:
    "你是电化学数据分析助手。回答时请先给结论，再给证据；明确指出可能误差来源，并给下一步实验建议。",
  summary:
    "请用结构化方式总结本次结果：1)核心结论 2)关键指标 3)异常/风险 4)建议动作。每项不超过3条。",
  paper:
    "请用学术写作风格输出：背景一句、方法一句、结果三句、讨论两句，并保持术语严谨。",
};

const TEMPLATE_VALUE_IDS = [
  "plot-font-family",
  "plot-font-size",
  "pro-area",
  "pro-potential-mode",
  "pro-offset",
  "pro-rhe-ph",
  "pro-ref-preset",
  "pro-ref-custom",
  "pro-lsv-target",
  "pro-lsv-tafel",
  "pro-lsv-match",
  "pro-lsv-prefix",
  "pro-lsv-title",
  "pro-lsv-xlabel",
  "pro-lsv-ylabel",
  "pro-lsv-line-width",
  "pro-lsv-ir-method",
  "pro-lsv-ir-manual",
  "pro-lsv-ir-points",
  "pro-lsv-quality-min-points-issue",
  "pro-lsv-quality-min-points-warning",
  "pro-lsv-quality-outlier-warning-pct",
  "pro-lsv-quality-min-potential-span",
  "pro-lsv-quality-noise-warning",
  "pro-lsv-quality-noise-critical",
  "pro-lsv-quality-jump-warning",
  "pro-lsv-quality-jump-critical",
  "pro-lsv-quality-local-factor",
  "pro-lsv-onset-current",
  "pro-lsv-eq-potential",
  "pro-lsv-halfwave-current",
  "pro-cv-match",
  "pro-cv-prefix",
  "pro-cv-title",
  "pro-cv-xlabel",
  "pro-cv-ylabel",
  "pro-cv-line-width",
  "pro-cv-peaks-smooth",
  "pro-cv-peaks-height",
  "pro-cv-peaks-dist",
  "pro-cv-peaks-max",
  "pro-cv-quality-min-points-warning",
  "pro-cv-quality-cycle-tolerance",
  "pro-eis-match",
  "pro-eis-prefix",
  "pro-eis-title",
  "pro-eis-xlabel",
  "pro-eis-ylabel",
  "pro-eis-line-width",
  "pro-ecsa-match",
  "pro-ecsa-prefix",
  "pro-ecsa-title",
  "pro-ecsa-xlabel",
  "pro-ecsa-ylabel",
  "pro-ecsa-line-width",
  "pro-ecsa-ev",
  "pro-ecsa-last-n",
  "pro-ecsa-cs-value",
  "pro-ecsa-cs-unit",
];

const TEMPLATE_CHECK_IDS = [
  "pro-auto-detect",
  "pro-plot-grid",
  "pro-use-abs-current",
  "pro-lsv-tafel-enabled",
  "pro-lsv-mark-targets",
  "pro-lsv-export-data",
  "pro-lsv-combine-all",
  "pro-lsv-export-tafel",
  "pro-lsv-quality-check",
  "pro-lsv-ir-enabled",
  "pro-lsv-overpotential-enabled",
  "pro-lsv-onset-enabled",
  "pro-lsv-halfwave-enabled",
  "pro-cv-peaks-enabled",
  "pro-cv-quality-check",
  "pro-eis-plot-nyquist",
  "pro-eis-plot-bode",
  "pro-ecsa-avg-last-n",
  "pro-ecsa-use-abs",
];

const I18N = {
  zh: {
    badge: "电化学数据处理软件V6.0.1",
    lang_label: "语言",
    hero_title: "电化学数据处理工作台",
    hero_sub: "面向电化学实验的专业数据工作台，提供多类型批处理、项目管理与 AI 辅助分析。",
    tab_pro: "专业模式",
    tab_ai: "AI 对话模式",
    tab_project: "项目管理",
    label_match_mode_short: "文件匹配方式",
    match_value_prefix: "文件前缀",
    match_value_contains: "包含关键字",
    match_value_regex: "正则表达式",
    match_placeholder_prefix: "{key}_prefix，默认 {default}",
    match_placeholder_contains: "输入文件名中应包含的关键字，例如 {default}",
    match_placeholder_regex: "输入正则表达式，例如 ^{default}.*",
    match_title_prefix: "按文件名前缀匹配，例如 LSV、CV、EIS 等。",
    match_title_contains: "按文件名包含的关键字匹配，适合历史命名不统一的数据。",
    match_title_regex: "按正则表达式匹配文件名，适合复杂命名规则。",
    btn_help_docs: "\u4f7f\u7528\u8bf4\u660e",
    help_docs_title: "\u4f7f\u7528\u8bf4\u660e",
    help_docs_sub: "\u67e5\u770b\u8f6f\u4ef6\u624b\u518c\u3001\u6587\u4ef6\u7ec4\u7ec7\u89c4\u5219\u548c HTTP \u63a5\u53e3\u793a\u4f8b\u3002",
    help_docs_toc: "\u76ee\u5f55\u5bfc\u822a",
    help_docs_loading: "\u6b63\u5728\u52a0\u8f7d\u4f7f\u7528\u8bf4\u660e...",
    help_docs_failed: "\u4f7f\u7528\u8bf4\u660e\u52a0\u8f7d\u5931\u8d25",
    help_docs_empty: "\u5f53\u524d\u6ca1\u6709\u53ef\u663e\u793a\u7684\u8bf4\u660e\u5185\u5bb9\u3002",
    help_docs_toc_empty: "\u5f53\u524d\u6587\u6863\u6ca1\u6709\u53ef\u7528\u76ee\u5f55\u3002",
    guide_pro_summary: "专业模式使用说明",
    guide_pro_intro: "用于批量处理 LSV/CV/EIS/ECSA 数据，建议先用默认参数跑通再做细调。",
    guide_pro_step1: "先选择数据文件夹，可选填写项目名称，再勾选处理类型（支持多选）。",
    guide_pro_step2: "按需调整高级参数：文件匹配策略、iR 补偿、峰检测、ECSA 常数等。",
    guide_pro_step3: "运行后到“统计与历史”查看记录，并在“处理结果”中核对输出文件与质量摘要。",
    guide_ai_summary: "AI 对话模式使用说明",
    guide_ai_intro: "用于问题咨询、结果解读和报告撰写，支持附带 ZIP 数据包进行联动分析。",
    guide_ai_step1: "先在“AI设置”中配置模型、API Key 与提示词模板。",
    guide_ai_step2: "发送消息可选填写项目名/数据类型，必要时附加 ZIP 文件。",
    guide_ai_step3: "AI 回复支持 Markdown；关键结论建议同步到项目管理页统一归档。",
    service_status: "服务状态",
    sys_info: "系统信息",
    btn_close: "关闭",
    sys_health_label: "服务状态",
    sys_version_label: "版本",
    btn_refresh_status: "刷新状态",
    btn_refresh: "刷新",
    btn_save: "保存",
    btn_apply: "应用",
    btn_ai_settings: "AI设置",
    proc_title: "专业数据处理",
    btn_select_folder: "选择文件夹",
    btn_template_load: "加载模板",
    btn_template_save: "保存模板",
    btn_template_delete: "删除模板",
    template_title_optional: "参数模板（可选）",
    ph_template_name: "模板名称",
    template_none: "无模板",
    template_loaded: "模板已加载",
    template_saved: "模板已保存",
    template_deleted: "模板已删除",
    template_save_failed: "模板保存失败",
    template_delete_failed: "模板删除失败",
    template_load_failed: "模板加载失败",
    template_name_required: "请填写模板名称",
    template_confirm_overwrite: "模板已存在，是否覆盖？",
    template_confirm_delete: "确定删除该模板吗？",
    template_builtin_immutable: "内置模板不可删除",
    template_builtin_tag: "内置",
    template_restart_hint: "若仍提示 Not Found，请重启 v6 服务并刷新页面。",
    plot_settings: "绘图与字体设置",
    label_font_family: "字体",
    label_font_size: "字号",
    font_default: "默认（系统）",
    label_plot_title: "图标题",
    label_line_width: "线宽",
    label_x_axis: "X轴标题",
    label_y_axis: "Y轴标题",
    label_data_types: "处理类型（可多选）",
    quick_mode: "基础参数",
    pro_mode: "高级参数",
    quick_params: "基础参数",
    pro_params: "高级参数",
    pro_hint_intro: "建议先使用默认值，只调整你确定含义的参数。",
    pro_help_summary: "参数说明（简版）",
    pro_help_line1: "target_current: 目标电流点，支持逗号分隔多个值。",
    pro_help_line2: "tafel_range: Tafel 拟合区间，常见格式如 1-10。",
    pro_help_line3: "match/prefix: 文件匹配策略与前缀，用于自动识别数据文件。",
    pro_help_line4: "iR 补偿参数仅在电阻信息可靠时启用。",
    pro_help_line5: "ECSA 参数与测试流程强相关，建议和实验记录一致。",
    label_area: "电极面积 (cm2)",
    label_potential_mode: "电位换算方式",
    label_offset: "手动电位偏移 (V)",
    label_rhe_ph: "pH",
    label_ref_preset: "参比电极",
    label_ref_custom: "自定义参比电位 (V)",
    potential_convert_title: "电位换算设置",
    potential_convert_formula: "E_RHE = E_measured + E_ref + 0.0591 × pH",
    potential_offset_preview_empty: "当前未设置有效的换算偏移",
    potential_offset_preview_manual: "当前使用手动偏移：{value} V",
    potential_offset_preview_rhe: "当前换算到 RHE 的偏移：{value} V = {ref} V + 0.0591 × {ph}",
    opt_potential_manual: "手动偏移",
    opt_potential_formula_rhe: "按 RHE 公式换算",
    opt_ref_custom: "自定义",
    auto_detect: "自动识别起点",
    plot_grid: "绘图网格",
    abs_current: "使用绝对电流",
    enable_tafel: "启用 Tafel 拟合",
    mark_targets: "标记目标电流点",
    export_table: "导出 LSV 数据表",
    combine_curves: "合并曲线",
    export_tafel_plot: "导出 Tafel 图",
    enable_quality_check: "启用数据质量检测",
    enable_to_config: "启用后可配置",
    label_target_current: "目标电流",
    label_tafel_range: "Tafel 区间",
    label_lsv_match: "文件匹配策略（lsv_match）",
    label_lsv_prefix: "文件前缀（lsv_prefix）",
    label_ir_method: "iR 模式",
    label_ir_manual: "手动电阻（Ohm）",
    label_ir_points: "线性拟合点数",
    label_quality_min_points_issue: "最少点数（失败）",
    label_quality_min_points_warning: "最少点数（警告）",
    label_quality_outlier_warning_pct: "异常值比例警告 (%)",
    label_quality_min_potential_span: "最小扫描范围 (V)",
    label_quality_noise_warning: "噪声警告阈值",
    label_quality_noise_critical: "噪声失败阈值",
    label_quality_jump_warning: "跳变比例警告",
    label_quality_jump_critical: "跳变比例失败",
    label_quality_local_factor: "局部波动放大倍数",
    label_onset_current: "Onset 电流阈值",
    label_eq_potential: "平衡电位 (V)",
    label_halfwave_current: "Halfwave 电流阈值",
    label_cv_match: "文件匹配策略（cv_match）",
    label_cv_prefix: "文件前缀（cv_prefix）",
    label_eis_match: "文件匹配策略（eis_match）",
    label_eis_prefix: "文件前缀（eis_prefix）",
    label_ecsa_match: "文件匹配策略（ecsa_match）",
    label_ecsa_prefix: "文件前缀（ecsa_prefix）",
    label_ecsa_ev: "Ev 参数",
    label_ecsa_last_n: "最后 N 圈",
    label_ecsa_cs_value: "比电容 Cs",
    label_ecsa_cs_unit: "Cs 单位",
    label_cv_peaks_smooth: "平滑窗口",
    label_cv_peaks_height: "最小峰高",
    label_cv_peaks_dist: "最小峰间距",
    label_cv_peaks_max: "最大峰数",
    label_cv_quality_min_points_warning: "最少点数（警告）",
    label_cv_quality_cycle_tolerance: "循环闭合容差 (V)",
    tip_lsv_target: "推荐：常用 10,100；多个值用逗号分隔。",
    tip_lsv_tafel: "推荐：先从 1-10 开始；必须按你的线性区调整，不建议机械套用。",
    tip_lsv_ir_manual: "仅在已有可靠 Rs 时填写；常见量级约 0.1-10 Ohm。",
    tip_lsv_ir_points: "推荐：8-20 个点；过小不稳定，过大可能跨出线性区。",
    tip_lsv_quality_config: "默认阈值适合常规 LSV；数据更嘈杂时可适度放宽，但建议保守调整。",
    tip_lsv_eq_potential: "仅在计算过电位时填写；HER 常用 0.0 vs RHE，OER 常用 1.23 vs RHE。",
    tip_lsv_onset_current: "推荐：0.5-1.0 mA/cm2；阈值越低越容易受噪声影响。",
    tip_lsv_halfwave_current: "常用于 ORR；通常取扩散极限电流的一半，不确定时可留空自动估计。",
    tip_cv_peaks_smooth: "推荐：5-15；噪声大时增大，但会让峰变钝。",
    tip_cv_peaks_height: "推荐：先从 0.5-2.0 开始，再按噪声水平微调。",
    tip_cv_peaks_dist: "推荐：5-20 个点；采样越密，通常需要更大的间距。",
    tip_cv_peaks_max: "常用：2-4；设置过大会把噪声也识别成峰。",
    tip_cv_quality_config: "默认阈值适合常规 CV；若扫描窗口较大或噪声偏高，可适度放宽。",
    tip_ecsa_ev: "常见：0.05-0.10 V；必须与你的测试流程保持一致。",
    tip_ecsa_last_n: "常用：1-3 圈；如果前几圈明显活化，建议只取后几圈。",
    tip_ecsa_cs_value: "常见：20-60 uF/cm2；务必与材料体系和文献口径一致。",
    enable_ir: "启用 iR 补偿",
    enable_overpotential: "启用过电位",
    enable_onset: "启用 Onset",
    enable_halfwave: "启用 Halfwave",
    enable_peak: "启用峰检测",
    plot_nyquist: "绘制 Nyquist",
    plot_bode: "绘制 Bode",
    avg_last_n: "平均最后 N 圈",
    use_abs_delta: "使用绝对 DeltaI",
    btn_run: "运行处理",
    result_title: "处理结果",
    result_summary: "摘要",
    result_types: "处理类型",
    result_outputs: "输出文件",
    result_quality: "质量摘要",
    result_error: "错误详情",
    result_empty: "暂无结果",
    result_quality_total: "总文件数",
    result_quality_passed: "通过数",
    result_quality_failed: "失败数",
    result_quality_warnings: "警告数",
    stats_history: "统计与历史",
    stat_total: "总记录",
    no_history: "暂无历史记录",
    project_manage_title: "项目管理",
    project_manage_sub: "集中管理项目、历史结果与关键指标。",
    project_include_archived: "显示已归档",
    project_empty: "暂无项目",
    project_none: "未选择项目",
    project_pick_hint: "请先在左侧选择一个项目。",
    project_recent_history: "最近历史",
    project_no_history: "暂无该项目历史记录",
    project_lsv_summary: "LSV 指标摘要",
    project_no_lsv: "暂无 LSV 汇总",
    project_compare_title: "结果对比",
    project_compare_empty: "暂无可对比的结果",
    project_compare_sort_eta: "按 η@10 / E@10",
    project_compare_sort_tafel: "按 Tafel",
    project_compare_sort_latest: "按最新时间",
    project_compare_sort_sample: "按样品名",
    project_compare_only_eta: "仅看有过电位",
    project_compare_only_tafel: "仅看有 Tafel",
    project_compare_col_sample: "样品",
    project_compare_col_eta: "η@10 / E@10",
    project_compare_col_tafel: "Tafel",
    project_compare_col_count: "记录数",
    project_compare_col_time: "最新时间",
    project_compare_best_eta: "最低 η@10",
    project_compare_best_potential: "最低 E@10",
    project_compare_best_tafel: "最低 Tafel",
    project_compare_missing: "缺失项提醒",
    project_compare_missing_eta: "无 η@10",
    project_compare_missing_tafel: "无 Tafel",
    project_compare_selected_count: "已选 {count} 个样品",
    project_compare_selected_count_empty: "未选择样品",
    project_compare_plot_title: "LSV 对比图",
    project_compare_plot_empty: "请选择样品后生成对比图",
    project_compare_plot_loading: "正在生成叠加图...",
    project_compare_plot_failed: "生成叠加图失败",
    project_compare_plot_traces: "曲线数",
    project_compare_plot_generated_at: "生成时间",
    project_compare_plot_warnings: "提示",
    project_compare_chart_type_label: "图表类型",
    project_compare_metric_label: "指标",
    project_compare_chart_overlay: "叠加曲线图",
    project_compare_chart_bar: "指标柱状图",
    project_compare_metric_eta: "η@j",
    project_compare_metric_potential: "E@j",
    project_compare_metric_tafel: "Tafel",
    project_compare_target_current_label: "目标电流密度 (mA/cm²)",
    project_compare_target_current_empty: "暂无可用目标电流",
    project_compare_target_current_missing: "当前项目没有该目标电流密度的历史结果，请重新处理后再生成柱状图",
    btn_project_compare_select_all: "全选",
    btn_project_compare_clear: "清空",
    btn_project_compare_generate: "生成对比图",
    ph_project_create_name: "输入新项目名称",
    btn_project_create: "新建项目",
    btn_project_export_report: "导出项目报告",
    btn_project_use: "填入当前项目",
    btn_project_delete: "删除项目",
    btn_project_save: "保存项目",
    btn_project_open_result: "打开到处理结果",
    btn_project_archive_history: "归档记录",
    btn_project_delete_history: "删除记录",
    project_edit_title: "项目信息编辑",
    project_field_name: "项目名称",
    project_field_color: "项目颜色",
    project_field_tags: "标签",
    project_field_desc: "项目说明",
    ph_project_tags: "例如 LSV, HER, 2026",
    ph_project_desc: "项目用途、实验批次、备注说明",
    project_label_updated: "更新时间",
    project_label_created: "创建时间",
    project_label_files: "文件数",
    project_label_desc: "项目说明",
    project_name_required: "请输入项目名称",
    project_color_invalid: "项目颜色需为十六进制颜色，例如 #155e45",
    project_confirm_delete: "确定删除该项目吗？",
    project_history_confirm_archive: "确定归档这条历史记录吗？",
    project_history_confirm_delete: "确定删除这条历史记录吗？此操作不可恢复。",
    project_status_loading: "正在加载项目列表...",
    project_status_load_failed: "项目加载失败",
    project_status_create_running: "正在创建项目...",
    project_status_create_success: "项目已创建",
    project_status_create_failed: "项目创建失败",
    project_status_save_running: "正在保存项目信息...",
    project_status_save_success: "项目信息已保存",
    project_status_save_failed: "项目信息保存失败",
    project_status_delete_running: "正在删除项目...",
    project_status_delete_success: "项目已删除",
    project_status_delete_failed: "项目删除失败",
    project_status_detail_loading: "正在加载项目详情...",
    project_status_detail_failed: "项目详情加载失败",
    project_status_applied: "已填入专业模式与 AI 对话的项目名称",
    project_history_archive_running: "正在归档历史记录...",
    project_history_archive_success: "历史记录已归档",
    project_history_archive_failed: "历史记录归档失败",
    project_history_delete_running: "正在删除历史记录...",
    project_history_delete_success: "历史记录已删除",
    project_history_delete_failed: "历史记录删除失败",
    project_lsv_col_sample: "样品",
    project_lsv_col_eta: "η@10 / E@10",
    project_lsv_col_tafel: "Tafel",
    project_lsv_col_count: "记录数",
    project_lsv_col_time: "最近时间",
    project_history_detail: "历史详情",
    project_select_history: "请选择一条历史记录查看详情",
    project_output_files: "结果文件",
    project_no_output_files: "暂无结果文件",
    project_output_group_prefix: "处理批次",
    project_filter_all_types: "全部类型",
    project_export_report_success: "项目报告已导出",
    project_export_report_failed: "项目报告导出失败",
    project_related_files: "关联文件",
    project_result_metrics: "结果指标",
    project_open_result_done: "已切换到专业模式并打开该历史结果",
    project_open_result_empty: "请先选择一条历史记录",
    btn_copy_path: "复制路径",
    btn_open_file: "打开文件",
    btn_open_dir: "打开目录",
    project_copy_done: "路径已复制",
    project_copy_failed: "复制路径失败",
    project_open_dir_done: "已请求打开目录",
    project_open_dir_failed: "打开目录失败",
    conv_list: "会话列表",
    btn_new_conv: "新会话",
    msg_placeholder: "消息将显示在这里",
    data_type: "数据类型",
    btn_send: "发送",
    ph_proc_folder: "数据文件夹路径，例如 D:\\data\\demo",
    ph_proc_project: "项目名称（可选）",
    proc_project_optional: "不关联项目（可选）",
    llm_settings: "模型与 API 设置",
    ai_settings_sub: "统一配置模型连接、密钥与对话提示策略。",
    llm_settings_block: "模型与API",
    llm_section_sub: "设置服务商、模型与连接参数，保存后立即生效。",
    llm_provider: "服务商",
    llm_model: "模型",
    llm_base_url: "Base URL",
    llm_timeout: "超时(秒)",
    llm_api_key: "API Key",
    ph_llm_model: "例如 gpt-4o-mini",
    ph_llm_base_url: "例如 https://api.openai.com/v1",
    ph_llm_timeout: "例如 60",
    ph_llm_api_key: "留空表示不修改已保存 Key",
    llm_key_configured: "当前状态: 已配置 API Key",
    llm_key_missing: "当前状态: 未配置 API Key",
    status_llm_loading: "正在加载模型配置...",
    status_llm_loaded: "模型配置已加载",
    status_llm_load_failed: "模型配置加载失败",
    status_llm_save_running: "正在保存模型配置...",
    status_llm_save_success: "模型配置已保存",
    status_llm_save_failed: "模型配置保存失败",
    status_llm_provider_required: "请选择服务商",
    status_llm_no_changes: "未检测到可保存的修改",
    status_llm_timeout_invalid: "超时必须是正整数",
    prompt_settings_block: "提示词设置",
    prompt_section_sub: "可选模板与自定义前缀，用于规范 AI 输出风格。",
    prompt_enabled: "发送时附加提示词",
    prompt_template: "模板",
    prompt_prefix: "附加提示词",
    prompt_tpl_analyst: "电化学分析师",
    prompt_tpl_summary: "结果总结模式",
    prompt_tpl_paper: "论文写作模式",
    ph_prompt_prefix: "每次发送消息时会拼接到用户消息前",
    prompt_hint: "提示：保存后只保存在本地浏览器，不会上传到服务器。",
    status_prompt_saved: "提示词设置已保存",
    status_prompt_applied: "模板已应用到提示词",
    status_prompt_empty: "提示词为空，已关闭附加",
    ph_font_family: "例如 Arial / Microsoft YaHei",
    ph_font_size: "例如 12",
    ph_line_width: "例如 2.0",
    ph_lsv_title: "LSV of {sample}",
    ph_lsv_xlabel: "Potential (V)",
    ph_lsv_ylabel: "Current Density (mA/cm2)",
    ph_cv_title: "CV of {sample}",
    ph_cv_xlabel: "Potential (V)",
    ph_cv_ylabel: "Current (mA)",
    ph_eis_title: "EIS of {sample}",
    ph_eis_xlabel: "Z' (Ohm)",
    ph_eis_ylabel: "-Z'' (Ohm)",
    ph_ecsa_title: "ECSA of {sample}",
    ph_ecsa_xlabel: "Scan rate v (V/s)",
    ph_ecsa_ylabel: "ΔJ (mA/cm2)",
    ph_target: "目标电流，例如 10,100",
    ph_tafel: "Tafel 范围，例如 1-10",
    ph_area: "电极面积 cm2，默认 1.0",
    ph_offset: "电位偏移 V，默认 0.0",
    ph_rhe_ph: "例如 13.6",
    ph_ref_custom: "例如 0.197",
    ph_project_name: "项目名称（可选）",
    ph_msg: "输入消息，或附带 ZIP 数据包给 AI 分析",
    title_area: "用于电流密度换算，单位 cm2。",
    title_offset: "整体电位平移量（V），正负号请按参考电极方向确认。",
    title_potential_mode: "可选择手动偏移，或按参比电极与 pH 自动换算到 RHE。",
    title_rhe_ph: "用于计算 0.0591 × pH 项。",
    title_ref_preset: "选择常见参比电极，或使用自定义电位。",
    title_ref_custom: "请输入参比电极相对 SHE 的电位。",
    title_font_family: "仅对系统已安装字体生效，未安装会自动回退。",
    title_font_size: "用于图标题字体大小，建议 10-18。",
    title_line_width: "曲线线宽，建议 1.0-3.0。",
    title_target_current: "输入一个或多个目标电流值，使用逗号分隔。",
    title_tafel_range: "Tafel 拟合区间，建议与实验线性区一致。",
    title_match_mode: "prefix 更稳健；contains 更宽松；regex 适合复杂命名。",
    title_prefix: "与 match 配合筛选文件，例如 LSV、CV、EIS 等。",
    title_ir_method: "auto 自动估计；manual 使用手动输入电阻。",
    title_ir_manual: "手动补偿电阻值（Ohm），仅 manual 模式生效。",
    title_ir_points: "用于线性拟合估计电阻的点数，过小会不稳定。",
    title_quality_min_points_issue: "低于该点数时判为质量失败。",
    title_quality_min_points_warning: "低于该点数时给出警告，但仍允许处理。",
    title_quality_outlier_warning_pct: "异常值比例超过该百分比时给出警告。",
    title_quality_min_potential_span: "电位扫描范围低于该值时给出警告。",
    title_quality_noise_warning: "噪声水平高于该值时给出警告。",
    title_quality_noise_critical: "噪声水平高于该值时判为失败。",
    title_quality_jump_warning: "突变点比例超过该值时给出警告，使用 0-1 小数。",
    title_quality_jump_critical: "突变点比例超过该值时判为失败，使用 0-1 小数。",
    title_quality_local_factor: "局部波动超过平均水平的该倍数时给出警告。",
    title_onset_current: "定义 onset 的阈值电流。",
    title_eq_potential: "热力学平衡电位，用于电位修正与对比。",
    title_halfwave_current: "半波电位对应电流阈值，不填则按算法估计。",
    title_cv_peaks_smooth: "平滑窗口，增大可抑制噪声但会钝化峰形。",
    title_cv_peaks_height: "峰最小高度阈值，过低会引入噪声峰。",
    title_cv_quality_min_points_warning: "低于该点数时给出质量警告。",
    title_cv_quality_cycle_tolerance: "起始与终止电位差值大于该容差时判为循环不完整。",
    title_cv_peaks_dist: "相邻峰最小距离，防止单个峰被重复识别。",
    title_ecsa_ev: "电位扫描速率差或步进相关参数（依实验方案定义）。",
    title_ecsa_last_n: "取最后 N 圈用于计算，建议排除前几圈活化段。",
    title_ecsa_cs_value: "比电容常数，取值需与材料和文献口径一致。",
    health_checking: "检测中...",
    health_online: "在线",
    health_error: "异常",
    health_offline: "不可达",
    conv_none: "未选择会话",
    conv_auto_create: "发送消息后自动创建会话",
    conv_new: "新会话",
    conv_new_hint: "发送消息后自动创建",
    ph_conv_search: "搜索会话标题/项目",
    btn_search: "搜索",
    btn_clear: "清空",
    conv_rename_action: "重命名",
    conv_delete_action: "删除",
    conv_rename_prompt: "请输入新会话名称",
    conv_rename_default: "未命名会话",
    chat_no_messages: "暂无消息",
    chat_no_conversations: "暂无会话",
    result_from_history: "历史记录",
    status_loading_conversations: "正在加载会话...",
    status_load_failed: "会话加载失败",
    status_history_loaded: "已从历史记录载入结果",
    status_rename_running: "正在重命名会话...",
    status_rename_success: "会话已重命名",
    status_rename_failed: "重命名失败",
    status_rename_empty: "会话名称不能为空",
    status_delete_running: "正在删除会话...",
    status_delete_success: "会话已删除",
    status_delete_failed: "删除失败",
    status_send_empty: "请输入消息或选择 ZIP 文件",
    status_send_running: "发送中...",
    status_waiting_reply: "已发送，等待 AI 回复...",
    status_ai_typing: "AI 正在回复",
    typing_reply: "AI 正在思考",
    status_send_success: "已发送",
    status_send_failed: "发送失败",
    status_zip_only: "仅支持 ZIP 文件",
    msg_zip_attached: "已附加 ZIP 文件",
    proc_pick_opening: "正在打开文件夹选择器...",
    proc_pick_success: "已选择文件夹",
    proc_pick_failed: "文件夹选择失败",
    proc_folder_required: "请填写 folder_path",
    proc_type_required: "请至少选择一种处理类型",
    proc_param_invalid: "参数无效",
    proc_running: "处理中...",
    proc_success: "处理成功",
    proc_failed: "处理失败"
  },
  en: {
    badge: "Electrochemical Data Processing Software V6.0.1",
    lang_label: "Language",
    hero_title: "Electrochemical Data Workbench",
    hero_sub: "A professional electrochemistry workbench for multi-type processing, project tracking, and AI-assisted analysis.",
    tab_pro: "Professional",
    tab_ai: "AI Chat",
    tab_project: "Projects",
    label_match_mode_short: "Match mode",
    match_value_prefix: "File prefix",
    match_value_contains: "Contains keyword",
    match_value_regex: "Regular expression",
    match_placeholder_prefix: "{key}_prefix, default {default}",
    match_placeholder_contains: "Enter a keyword that should appear in the file name, e.g. {default}",
    match_placeholder_regex: "Enter a regex, e.g. ^{default}.*",
    match_title_prefix: "Match by file-name prefix, e.g. LSV, CV, EIS.",
    match_title_contains: "Match by keyword contained in the file name; useful when historical naming is inconsistent.",
    match_title_regex: "Match file names with a regular expression; useful for complex naming rules.",
    btn_help_docs: "Manual",
    help_docs_title: "Manual",
    help_docs_sub: "Read the software guide, file organization rules, and HTTP API examples.",
    help_docs_toc: "Contents",
    help_docs_loading: "Loading manual...",
    help_docs_failed: "Failed to load manual",
    help_docs_empty: "No manual content is available.",
    help_docs_toc_empty: "This manual has no navigable sections.",
    guide_pro_summary: "Professional Mode Guide",
    guide_pro_intro: "Use this mode for batch processing LSV/CV/EIS/ECSA data. Start with defaults, then tune parameters.",
    guide_pro_step1: "Select a data folder and optional project name, then choose one or more data types.",
    guide_pro_step2: "Adjust advanced parameters as needed: file matching, iR compensation, peak detection, ECSA constants.",
    guide_pro_step3: "After run, verify outputs and quality in Result, and review records in Stats/History.",
    guide_ai_summary: "AI Chat Mode Guide",
    guide_ai_intro: "Use this mode for Q&A, result interpretation, and writing support. ZIP input is supported.",
    guide_ai_step1: "Configure model, API key, and prompt template in AI Settings first.",
    guide_ai_step2: "Optionally set project/data type before sending; attach ZIP when needed.",
    guide_ai_step3: "AI responses support Markdown; sync key conclusions into project management.",
    service_status: "Service Status",
    sys_info: "System Info",
    btn_close: "Close",
    sys_health_label: "Service Status",
    sys_version_label: "Version",
    btn_refresh_status: "Refresh Status",
    btn_refresh: "Refresh",
    btn_save: "Save",
    btn_apply: "Apply",
    btn_ai_settings: "AI Settings",
    proc_title: "Professional Processing",
    btn_select_folder: "Select Folder",
    btn_template_load: "Load Template",
    btn_template_save: "Save Template",
    btn_template_delete: "Delete Template",
    template_title_optional: "Parameter Templates (Optional)",
    ph_template_name: "Template name",
    template_none: "No templates",
    template_loaded: "Template loaded",
    template_saved: "Template saved",
    template_deleted: "Template deleted",
    template_save_failed: "Failed to save template",
    template_delete_failed: "Failed to delete template",
    template_load_failed: "Failed to load template",
    template_name_required: "Template name is required",
    template_confirm_overwrite: "Template already exists. Overwrite?",
    template_confirm_delete: "Delete this template?",
    template_builtin_immutable: "Built-in template cannot be deleted",
    template_builtin_tag: "Built-in",
    template_restart_hint: "If Not Found persists, restart the v6 server and refresh page.",
    plot_settings: "Plot and Font Settings",
    label_font_family: "Font",
    label_font_size: "Font size",
    font_default: "Default (System)",
    label_plot_title: "Plot title",
    label_line_width: "Line width",
    label_x_axis: "X axis label",
    label_y_axis: "Y axis label",
    label_data_types: "Data types (multi-select)",
    quick_mode: "Basic Params",
    pro_mode: "Advanced Params",
    quick_params: "Basic Parameters",
    pro_params: "Advanced Parameters",
    pro_hint_intro: "Start from defaults and adjust only parameters you clearly understand.",
    pro_help_summary: "Parameter Guide (Brief)",
    pro_help_line1: "target_current: one or multiple current targets separated by commas.",
    pro_help_line2: "tafel_range: fitting range for Tafel, commonly like 1-10.",
    pro_help_line3: "match/prefix: file matching strategy and naming prefix for auto detection.",
    pro_help_line4: "Enable iR compensation only when resistance information is reliable.",
    pro_help_line5: "ECSA parameters are experiment-dependent; align with lab records.",
    label_area: "Electrode area (cm2)",
    label_potential_mode: "Potential conversion",
    label_offset: "Manual potential offset (V)",
    label_rhe_ph: "pH",
    label_ref_preset: "Reference electrode",
    label_ref_custom: "Custom reference potential (V)",
    potential_convert_title: "Potential conversion settings",
    potential_convert_formula: "E_RHE = E_measured + E_ref + 0.0591 × pH",
    potential_offset_preview_empty: "No valid potential conversion offset set",
    potential_offset_preview_manual: "Current manual offset: {value} V",
    potential_offset_preview_rhe: "Current RHE offset: {value} V = {ref} V + 0.0591 × {ph}",
    opt_potential_manual: "Manual offset",
    opt_potential_formula_rhe: "Convert to RHE",
    opt_ref_custom: "Custom",
    auto_detect: "Auto detect start",
    plot_grid: "Plot grid",
    abs_current: "Use absolute current",
    enable_tafel: "Enable Tafel fit",
    mark_targets: "Mark target current",
    export_table: "Export LSV table",
    combine_curves: "Combine curves",
    export_tafel_plot: "Export Tafel plot",
    enable_quality_check: "Enable quality check",
    enable_to_config: "Configure after enabled",
    label_target_current: "Target current",
    label_tafel_range: "Tafel range",
    label_lsv_match: "File matching (lsv_match)",
    label_lsv_prefix: "File prefix (lsv_prefix)",
    label_ir_method: "iR mode",
    label_ir_manual: "Manual resistance (Ohm)",
    label_ir_points: "Linear-fit points",
    label_quality_min_points_issue: "Min points (fail)",
    label_quality_min_points_warning: "Min points (warn)",
    label_quality_outlier_warning_pct: "Outlier warn ratio (%)",
    label_quality_min_potential_span: "Min span (V)",
    label_quality_noise_warning: "Noise warn threshold",
    label_quality_noise_critical: "Noise fail threshold",
    label_quality_jump_warning: "Jump warn ratio",
    label_quality_jump_critical: "Jump fail ratio",
    label_quality_local_factor: "Local variation factor",
    label_onset_current: "Onset current threshold",
    label_eq_potential: "Equilibrium potential (V)",
    label_halfwave_current: "Half-wave current threshold",
    label_cv_match: "File matching (cv_match)",
    label_cv_prefix: "File prefix (cv_prefix)",
    label_eis_match: "File matching (eis_match)",
    label_eis_prefix: "File prefix (eis_prefix)",
    label_ecsa_match: "File matching (ecsa_match)",
    label_ecsa_prefix: "File prefix (ecsa_prefix)",
    label_ecsa_ev: "Ev parameter",
    label_ecsa_last_n: "Last N cycles",
    label_ecsa_cs_value: "Specific capacitance Cs",
    label_ecsa_cs_unit: "Cs unit",
    label_cv_peaks_smooth: "Smoothing window",
    label_cv_peaks_height: "Minimum peak height",
    label_cv_peaks_dist: "Minimum peak distance",
    label_cv_peaks_max: "Maximum peaks",
    label_cv_quality_min_points_warning: "Min points (warn)",
    label_cv_quality_cycle_tolerance: "Cycle closure tolerance (V)",
    tip_lsv_target: "Recommended: common values are 10 and 100; separate multiple values with commas.",
    tip_lsv_tafel: "Recommended: start from 1-10, then adjust to your actual linear region.",
    tip_lsv_ir_manual: "Fill this only when you already have a reliable Rs value; common magnitude is about 0.1-10 Ohm.",
    tip_lsv_ir_points: "Recommended: 8-20 points; too few is unstable, too many may exceed the linear region.",
    tip_lsv_quality_config: "Defaults fit typical LSV runs; relax them only cautiously for noisy datasets.",
    tip_lsv_eq_potential: "Fill this only for overpotential; HER is often 0.0 vs RHE, OER is often 1.23 vs RHE.",
    tip_lsv_onset_current: "Recommended: 0.5-1.0 mA/cm2; lower thresholds are more noise-sensitive.",
    tip_lsv_halfwave_current: "Common for ORR; usually half of the diffusion-limited current. Leave blank to auto-estimate.",
    tip_cv_peaks_smooth: "Recommended: 5-15; increase for noisy data, but peaks will become broader.",
    tip_cv_peaks_height: "Recommended: start from 0.5-2.0, then tune based on noise level.",
    tip_cv_peaks_dist: "Recommended: 5-20 points; denser sampling often needs larger spacing.",
    tip_cv_peaks_max: "Common: 2-4; setting this too high may classify noise as peaks.",
    tip_cv_quality_config: "Defaults fit typical CV runs; relax them slightly for wider windows or noisier datasets.",
    tip_ecsa_ev: "Common: 0.05-0.10 V; keep it consistent with your test protocol.",
    tip_ecsa_last_n: "Common: 1-3 cycles; use later cycles if the early ones show activation.",
    tip_ecsa_cs_value: "Common: 20-60 uF/cm2; align it with your material system and literature basis.",
    enable_ir: "Enable iR compensation",
    enable_overpotential: "Enable overpotential",
    enable_onset: "Enable onset",
    enable_halfwave: "Enable halfwave",
    enable_peak: "Enable peak detection",
    plot_nyquist: "Plot Nyquist",
    plot_bode: "Plot Bode",
    avg_last_n: "Average last N cycles",
    use_abs_delta: "Use abs DeltaI",
    btn_run: "Run Processing",
    result_title: "Processing Result",
    result_summary: "Summary",
    result_types: "Data Types",
    result_outputs: "Output Files",
    result_quality: "Quality Summary",
    result_error: "Error Details",
    result_empty: "No result yet",
    result_quality_total: "Total files",
    result_quality_passed: "Passed",
    result_quality_failed: "Failed",
    result_quality_warnings: "Warnings",
    stats_history: "Stats and History",
    stat_total: "Total",
    no_history: "No history",
    project_manage_title: "Project Management",
    project_manage_sub: "Manage projects, history, and key metrics in one place.",
    project_include_archived: "Show Archived",
    project_empty: "No projects",
    project_none: "No project selected",
    project_pick_hint: "Select a project from the left list first.",
    project_recent_history: "Recent History",
    project_no_history: "No history in this project",
    project_lsv_summary: "LSV Summary",
    project_no_lsv: "No LSV summary",
    project_compare_title: "Comparison",
    project_compare_empty: "No comparable results yet",
    project_compare_sort_eta: "Sort by η@10 / E@10",
    project_compare_sort_tafel: "Sort by Tafel",
    project_compare_sort_latest: "Sort by latest time",
    project_compare_sort_sample: "Sort by sample name",
    project_compare_only_eta: "Only with overpotential",
    project_compare_only_tafel: "Only with Tafel",
    project_compare_col_sample: "Sample",
    project_compare_col_eta: "η@10 / E@10",
    project_compare_col_tafel: "Tafel",
    project_compare_col_count: "Records",
    project_compare_col_time: "Latest Time",
    project_compare_best_eta: "Lowest η@10",
    project_compare_best_potential: "Lowest E@10",
    project_compare_best_tafel: "Lowest Tafel",
    project_compare_missing: "Missing metrics",
    project_compare_missing_eta: "No η@10",
    project_compare_missing_tafel: "No Tafel",
    project_compare_selected_count: "{count} samples selected",
    project_compare_selected_count_empty: "No samples selected",
    project_compare_plot_title: "LSV Compare Plot",
    project_compare_plot_empty: "Select samples to generate a compare plot",
    project_compare_plot_loading: "Generating overlay plot...",
    project_compare_plot_failed: "Failed to generate overlay plot",
    project_compare_plot_traces: "Traces",
    project_compare_plot_generated_at: "Generated",
    project_compare_plot_warnings: "Warnings",
    project_compare_chart_type_label: "Chart Type",
    project_compare_metric_label: "Metric",
    project_compare_chart_overlay: "Overlay curves",
    project_compare_chart_bar: "Metric bars",
    project_compare_metric_eta: "η@j",
    project_compare_metric_potential: "E@j",
    project_compare_metric_tafel: "Tafel",
    project_compare_target_current_label: "Target current density (mA/cm²)",
    project_compare_target_current_empty: "No saved target currents",
    project_compare_target_current_missing: "No history result found for this target current. Reprocess data before generating a bar chart.",
    btn_project_compare_select_all: "Select all",
    btn_project_compare_clear: "Clear",
    btn_project_compare_generate: "Generate compare plot",
    ph_project_create_name: "Input new project name",
    btn_project_create: "Create",
    btn_project_export_report: "Export Report",
    btn_project_use: "Apply to Forms",
    btn_project_delete: "Delete Project",
    btn_project_save: "Save Project",
    btn_project_open_result: "Open in Results",
    btn_project_archive_history: "Archive Record",
    btn_project_delete_history: "Delete Record",
    project_edit_title: "Project Metadata",
    project_field_name: "Project name",
    project_field_color: "Project color",
    project_field_tags: "Tags",
    project_field_desc: "Description",
    ph_project_tags: "e.g. LSV, HER, 2026",
    ph_project_desc: "Project scope, batch note, or remarks",
    project_label_updated: "Updated",
    project_label_created: "Created",
    project_label_files: "Files",
    project_label_desc: "Description",
    project_name_required: "Project name is required",
    project_color_invalid: "Project color must be a hex color like #155e45",
    project_confirm_delete: "Delete this project?",
    project_history_confirm_archive: "Archive this history record?",
    project_history_confirm_delete: "Delete this history record? This cannot be undone.",
    project_status_loading: "Loading projects...",
    project_status_load_failed: "Failed to load projects",
    project_status_create_running: "Creating project...",
    project_status_create_success: "Project created",
    project_status_create_failed: "Failed to create project",
    project_status_save_running: "Saving project metadata...",
    project_status_save_success: "Project metadata saved",
    project_status_save_failed: "Failed to save project metadata",
    project_status_delete_running: "Deleting project...",
    project_status_delete_success: "Project deleted",
    project_status_delete_failed: "Failed to delete project",
    project_status_detail_loading: "Loading project details...",
    project_status_detail_failed: "Failed to load project details",
    project_status_applied: "Project name applied to Professional and AI forms",
    project_history_archive_running: "Archiving history record...",
    project_history_archive_success: "History record archived",
    project_history_archive_failed: "Failed to archive history record",
    project_history_delete_running: "Deleting history record...",
    project_history_delete_success: "History record deleted",
    project_history_delete_failed: "Failed to delete history record",
    project_lsv_col_sample: "Sample",
    project_lsv_col_eta: "eta@10 / E@10",
    project_lsv_col_tafel: "Tafel",
    project_lsv_col_count: "Records",
    project_lsv_col_time: "Latest Time",
    project_history_detail: "History Detail",
    project_select_history: "Select one history record to view details",
    project_output_files: "Output Files",
    project_no_output_files: "No output files",
    project_output_group_prefix: "Run",
    project_filter_all_types: "All Types",
    project_export_report_success: "Project report exported",
    project_export_report_failed: "Failed to export project report",
    project_related_files: "Related Files",
    project_result_metrics: "Result Metrics",
    project_open_result_done: "Switched to Professional tab and opened the selected history result",
    project_open_result_empty: "Select one history record first",
    btn_copy_path: "Copy Path",
    btn_open_file: "Open File",
    btn_open_dir: "Open Folder",
    project_copy_done: "Path copied",
    project_copy_failed: "Failed to copy path",
    project_open_dir_done: "Open folder requested",
    project_open_dir_failed: "Failed to open folder",
    conv_list: "Conversations",
    btn_new_conv: "New",
    msg_placeholder: "Messages will be shown here",
    data_type: "Data Type",
    btn_send: "Send",
    ph_proc_folder: "Folder path, e.g. D:\\data\\demo",
    ph_proc_project: "Project name (optional)",
    proc_project_optional: "No project (optional)",
    llm_settings: "Model and API Settings",
    ai_settings_sub: "Configure model connection, API key and prompting strategy in one panel.",
    llm_settings_block: "Model and API",
    llm_section_sub: "Set provider, model, and connection parameters. Changes apply after save.",
    llm_provider: "Provider",
    llm_model: "Model",
    llm_base_url: "Base URL",
    llm_timeout: "Timeout(s)",
    llm_api_key: "API Key",
    ph_llm_model: "e.g. gpt-4o-mini",
    ph_llm_base_url: "e.g. https://api.openai.com/v1",
    ph_llm_timeout: "e.g. 60",
    ph_llm_api_key: "Leave empty to keep saved key",
    llm_key_configured: "Current: API key configured",
    llm_key_missing: "Current: API key not configured",
    status_llm_loading: "Loading model config...",
    status_llm_loaded: "Model config loaded",
    status_llm_load_failed: "Failed to load model config",
    status_llm_save_running: "Saving model config...",
    status_llm_save_success: "Model config saved",
    status_llm_save_failed: "Failed to save model config",
    status_llm_provider_required: "Please select a provider",
    status_llm_no_changes: "No changes to save",
    status_llm_timeout_invalid: "Timeout must be a positive integer",
    prompt_settings_block: "Prompt Settings",
    prompt_section_sub: "Use template or custom prefix to enforce response style and structure.",
    prompt_enabled: "Attach prompt when sending",
    prompt_template: "Template",
    prompt_prefix: "Prompt Prefix",
    prompt_tpl_analyst: "Electrochem Analyst",
    prompt_tpl_summary: "Result Summary",
    prompt_tpl_paper: "Paper Writing",
    ph_prompt_prefix: "Will be prepended to each message before send",
    prompt_hint: "Saved in local browser only and not uploaded to server.",
    status_prompt_saved: "Prompt settings saved",
    status_prompt_applied: "Template applied",
    status_prompt_empty: "Prompt is empty, attach mode disabled",
    ph_font_family: "e.g. Arial / Microsoft YaHei",
    ph_font_size: "e.g. 12",
    ph_line_width: "e.g. 2.0",
    ph_lsv_title: "LSV of {sample}",
    ph_lsv_xlabel: "Potential (V)",
    ph_lsv_ylabel: "Current Density (mA/cm2)",
    ph_cv_title: "CV of {sample}",
    ph_cv_xlabel: "Potential (V)",
    ph_cv_ylabel: "Current (mA)",
    ph_eis_title: "EIS of {sample}",
    ph_eis_xlabel: "Z' (Ohm)",
    ph_eis_ylabel: "-Z'' (Ohm)",
    ph_ecsa_title: "ECSA of {sample}",
    ph_ecsa_xlabel: "Scan rate v (V/s)",
    ph_ecsa_ylabel: "Delta J (mA/cm2)",
    ph_target: "Target current, e.g. 10,100",
    ph_tafel: "Tafel range, e.g. 1-10",
    ph_area: "Electrode area cm2, default 1.0",
    ph_offset: "Potential offset V, default 0.0",
    ph_rhe_ph: "e.g. 13.6",
    ph_ref_custom: "e.g. 0.197",
    ph_project_name: "Project name (optional)",
    ph_msg: "Message to AI, or attach ZIP for analysis",
    title_area: "Electrode area for current-density conversion (cm2).",
    title_offset: "Global potential shift in volts. Verify sign with reference electrode convention.",
    title_potential_mode: "Choose manual shift or automatic conversion to RHE from reference electrode and pH.",
    title_rhe_ph: "Used to compute the 0.0591 × pH term.",
    title_ref_preset: "Select a common reference electrode or use a custom value.",
    title_ref_custom: "Reference electrode potential relative to SHE.",
    title_font_family: "Only works when the font is installed on this system.",
    title_font_size: "Font size used for plot titles. Recommended 10-18.",
    title_line_width: "Curve line width. Recommended 1.0-3.0.",
    title_target_current: "Input one or multiple target currents, separated by commas.",
    title_tafel_range: "Tafel fitting range; align with your linear region.",
    title_match_mode: "prefix is stricter; contains is looser; regex is for complex naming.",
    title_prefix: "Used with match mode to filter files, e.g. LSV/CV/EIS.",
    title_ir_method: "auto estimates resistance; manual uses your input resistance.",
    title_ir_manual: "Manual compensation resistance in Ohm (manual mode only).",
    title_ir_points: "Point count used for linear fit resistance estimation.",
    title_quality_min_points_issue: "Below this point count, the quality check fails.",
    title_quality_min_points_warning: "Below this point count, a warning is raised but processing continues.",
    title_quality_outlier_warning_pct: "Warn when outlier ratio exceeds this percentage.",
    title_quality_min_potential_span: "Warn when the potential span is smaller than this value.",
    title_quality_noise_warning: "Warn when noise level exceeds this value.",
    title_quality_noise_critical: "Fail when noise level exceeds this value.",
    title_quality_jump_warning: "Warn when jump-point ratio exceeds this value; use a 0-1 decimal.",
    title_quality_jump_critical: "Fail when jump-point ratio exceeds this value; use a 0-1 decimal.",
    title_quality_local_factor: "Warn when local variation exceeds this multiple of the average.",
    title_onset_current: "Current threshold used to define onset potential.",
    title_eq_potential: "Thermodynamic equilibrium potential for correction/comparison.",
    title_halfwave_current: "Current threshold for half-wave potential; blank uses auto estimation.",
    title_cv_peaks_smooth: "Smoothing window; larger values suppress noise but may flatten peaks.",
    title_cv_peaks_height: "Minimum peak height threshold; too low may include noise peaks.",
    title_cv_quality_min_points_warning: "Warn when point count is below this value.",
    title_cv_quality_cycle_tolerance: "Warn when start/end potential difference exceeds this tolerance.",
    title_cv_peaks_dist: "Minimum distance between peaks to avoid duplicate detection.",
    title_ecsa_ev: "Potential-step or scan related value (defined by your method).",
    title_ecsa_last_n: "Use the last N cycles; exclude activation cycles when needed.",
    title_ecsa_cs_value: "Specific capacitance constant; keep consistent with your literature basis.",
    health_checking: "Checking...",
    health_online: "Online",
    health_error: "Error",
    health_offline: "Offline",
    conv_none: "No conversation selected",
    conv_auto_create: "A new conversation will be created after sending.",
    conv_new: "New Conversation",
    conv_new_hint: "Will be created after next message",
    ph_conv_search: "Search title/project",
    btn_search: "Search",
    btn_clear: "Clear",
    conv_rename_action: "Rename",
    conv_delete_action: "Delete",
    conv_rename_prompt: "Input new conversation title",
    conv_rename_default: "Untitled",
    chat_no_messages: "No messages",
    chat_no_conversations: "No conversations",
    result_from_history: "History record",
    status_loading_conversations: "Loading conversations...",
    status_load_failed: "Failed to load conversations",
    status_history_loaded: "Loaded result from history",
    status_rename_running: "Renaming conversation...",
    status_rename_success: "Conversation renamed",
    status_rename_failed: "Rename failed",
    status_rename_empty: "Title cannot be empty",
    status_delete_running: "Deleting conversation...",
    status_delete_success: "Conversation deleted",
    status_delete_failed: "Delete failed",
    status_send_empty: "Enter a message or choose a ZIP file",
    status_send_running: "Sending...",
    status_waiting_reply: "Sent. Waiting for AI reply...",
    status_ai_typing: "AI is replying",
    typing_reply: "AI is thinking",
    status_send_success: "Sent",
    status_send_failed: "Send failed",
    status_zip_only: "Only ZIP files are supported",
    msg_zip_attached: "ZIP attached",
    proc_pick_opening: "Opening folder picker...",
    proc_pick_success: "Folder selected",
    proc_pick_failed: "Folder picker failed",
    proc_folder_required: "Please input folder_path",
    proc_type_required: "Please select at least one data type",
    proc_param_invalid: "Invalid parameter",
    proc_running: "Processing...",
    proc_success: "Success",
    proc_failed: "Processing failed"
  }
};

let currentLang = "zh";

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || I18N.zh[key] || key;
}

function byId(id) {
  return document.getElementById(id);
}

function textValue(id) {
  return String((byId(id) && byId(id).value) || "").trim();
}

function boolValue(id) {
  return Boolean(byId(id) && byId(id).checked);
}

function numberValue(id) {
  const raw = textValue(id);
  if (!raw) return undefined;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

function getPotentialMode() {
  return textValue("pro-potential-mode") || "manual";
}

function getReferenceElectrodePotential() {
  const presetEl = byId("pro-ref-preset");
  if (!presetEl) return undefined;
  const preset = String(presetEl.value || "").trim();
  if (preset === "custom") {
    return numberValue("pro-ref-custom");
  }
  const option = presetEl.selectedOptions && presetEl.selectedOptions[0] ? presetEl.selectedOptions[0] : null;
  if (!option) return undefined;
  const raw = option.getAttribute("data-potential");
  if (!raw) return undefined;
  const value = Number(raw);
  return Number.isFinite(value) ? value : undefined;
}

function renderPotentialOffsetPreview() {
  const el = byId("potential-offset-preview");
  if (!el) return;
  const mode = getPotentialMode();
  if (mode === "formula_rhe") {
    const ph = numberValue("pro-rhe-ph");
    const ref = getReferenceElectrodePotential();
    if (!Number.isFinite(ph) || !Number.isFinite(ref)) {
      el.textContent = t("potential_offset_preview_empty");
      return;
    }
    const value = ref + 0.0591 * ph;
    el.textContent = t("potential_offset_preview_rhe")
      .replace("{value}", value.toFixed(4))
      .replace("{ref}", ref.toFixed(4))
      .replace("{ph}", String(ph));
    return;
  }
  const offset = numberValue("pro-offset");
  if (!Number.isFinite(offset)) {
    el.textContent = t("potential_offset_preview_empty");
    return;
  }
  el.textContent = t("potential_offset_preview_manual").replace("{value}", offset.toFixed(4));
}

function syncPotentialConversionUI() {
  const mode = getPotentialMode();
  const manualPanel = byId("potential-manual-panel");
  const rhePanel = byId("potential-rhe-panel");
  const manualActive = mode !== "formula_rhe";
  if (manualPanel) {
    manualPanel.classList.toggle("hidden", !manualActive);
    manualPanel.querySelectorAll("input, select, textarea").forEach((el) => {
      el.disabled = !manualActive;
    });
  }
  if (rhePanel) {
    rhePanel.classList.toggle("hidden", manualActive);
    rhePanel.querySelectorAll("input, select, textarea").forEach((el) => {
      el.disabled = manualActive;
    });
  }
  const customWrap = byId("pro-ref-custom-wrap");
  const customInput = byId("pro-ref-custom");
  const showCustom = mode === "formula_rhe" && textValue("pro-ref-preset") === "custom";
  if (customWrap) customWrap.classList.toggle("hidden", !showCustom);
  if (customInput) customInput.disabled = !showCustom;
  renderPotentialOffsetPreview();
}

function validateNumericField(id, label, options = {}) {
  const raw = textValue(id);
  if (!raw) return null;
  const value = Number(raw);
  const integerOnly = Boolean(options.integerOnly);
  const min = options.min;
  const max = options.max;
  if (!Number.isFinite(value)) {
    return currentLang === "zh" ? `${label}必须是数字` : `${label} must be numeric`;
  }
  if (integerOnly && !Number.isInteger(value)) {
    return currentLang === "zh" ? `${label}必须是整数` : `${label} must be an integer`;
  }
  if (typeof min === "number" && value < min) {
    return currentLang === "zh" ? `${label}不能小于 ${min}` : `${label} must be >= ${min}`;
  }
  if (typeof max === "number" && value > max) {
    return currentLang === "zh" ? `${label}不能大于 ${max}` : `${label} must be <= ${max}`;
  }
  return null;
}

function collectProcessValidationErrors(dataTypes) {
  const errors = [];
  const addError = (err) => {
    if (err) errors.push(err);
  };

  addError(validateNumericField("plot-font-size", t("label_font_size"), { min: 6, max: 72, integerOnly: true }));
  addError(validateNumericField("pro-area", currentLang === "zh" ? "电极面积" : "Electrode area", { min: 0.000001 }));
  if (getPotentialMode() === "formula_rhe") {
    addError(validateNumericField("pro-rhe-ph", t("label_rhe_ph"), { min: 0, max: 14 }));
    const refPreset = textValue("pro-ref-preset");
    if (refPreset === "custom") {
      if (!textValue("pro-ref-custom")) {
        addError(currentLang === "zh" ? "请填写自定义参比电位" : "Custom reference potential is required");
      }
      addError(validateNumericField("pro-ref-custom", t("label_ref_custom"), { min: -2, max: 2 }));
    } else if (getReferenceElectrodePotential() === undefined) {
      addError(currentLang === "zh" ? "参比电极电位无效" : "Reference electrode potential is invalid");
    }
  } else {
    addError(validateNumericField("pro-offset", currentLang === "zh" ? "电位偏移" : "Potential offset", { min: -100, max: 100 }));
  }

  if (dataTypes.includes("LSV")) {
    addError(validateNumericField("pro-lsv-line-width", `LSV ${t("label_line_width")}`, { min: 0.1, max: 10 }));
    if (boolValue("pro-lsv-quality-check")) {
      addError(validateNumericField("pro-lsv-quality-min-points-issue", t("label_quality_min_points_issue"), { min: 1, max: 100000, integerOnly: true }));
      addError(validateNumericField("pro-lsv-quality-min-points-warning", t("label_quality_min_points_warning"), { min: 1, max: 100000, integerOnly: true }));
      addError(validateNumericField("pro-lsv-quality-outlier-warning-pct", t("label_quality_outlier_warning_pct"), { min: 0, max: 100 }));
      addError(validateNumericField("pro-lsv-quality-min-potential-span", t("label_quality_min_potential_span"), { min: 0, max: 100 }));
      addError(validateNumericField("pro-lsv-quality-noise-warning", t("label_quality_noise_warning"), { min: 0, max: 100000 }));
      addError(validateNumericField("pro-lsv-quality-noise-critical", t("label_quality_noise_critical"), { min: 0, max: 100000 }));
      addError(validateNumericField("pro-lsv-quality-jump-warning", t("label_quality_jump_warning"), { min: 0, max: 1 }));
      addError(validateNumericField("pro-lsv-quality-jump-critical", t("label_quality_jump_critical"), { min: 0, max: 1 }));
      addError(validateNumericField("pro-lsv-quality-local-factor", t("label_quality_local_factor"), { min: 1, max: 100000 }));
    }
    if (boolValue("pro-lsv-ir-enabled")) {
      addError(validateNumericField("pro-lsv-ir-manual", t("label_ir_manual"), { min: 0 }));
      addError(validateNumericField("pro-lsv-ir-points", t("label_ir_points"), { min: 2, max: 1000, integerOnly: true }));
    }
    if (boolValue("pro-lsv-overpotential-enabled")) {
      addError(validateNumericField("pro-lsv-eq-potential", t("label_eq_potential")));
    }
  }

  if (dataTypes.includes("CV")) {
    addError(validateNumericField("pro-cv-line-width", `CV ${t("label_line_width")}`, { min: 0.1, max: 10 }));
    if (boolValue("pro-cv-peaks-enabled")) {
      addError(validateNumericField("pro-cv-peaks-smooth", t("label_cv_peaks_smooth"), { min: 1, max: 999, integerOnly: true }));
      addError(validateNumericField("pro-cv-peaks-height", t("label_cv_peaks_height"), { min: 0 }));
      addError(validateNumericField("pro-cv-peaks-dist", t("label_cv_peaks_dist"), { min: 1, max: 10000, integerOnly: true }));
      addError(validateNumericField("pro-cv-peaks-max", t("label_cv_peaks_max"), { min: 1, max: 1000, integerOnly: true }));
    }
    if (boolValue("pro-cv-quality-check")) {
      addError(validateNumericField("pro-cv-quality-min-points-warning", t("label_cv_quality_min_points_warning"), { min: 1, max: 100000, integerOnly: true }));
      addError(validateNumericField("pro-cv-quality-cycle-tolerance", t("label_cv_quality_cycle_tolerance"), { min: 0, max: 100 }));
    }
  }

  if (dataTypes.includes("EIS")) {
    addError(validateNumericField("pro-eis-line-width", `EIS ${t("label_line_width")}`, { min: 0.1, max: 10 }));
  }

  if (dataTypes.includes("ECSA")) {
    addError(validateNumericField("pro-ecsa-line-width", `ECSA ${t("label_line_width")}`, { min: 0.1, max: 10 }));
    addError(validateNumericField("pro-ecsa-ev", t("label_ecsa_ev"), { min: 0.000001 }));
    addError(validateNumericField("pro-ecsa-last-n", t("label_ecsa_last_n"), { min: 1, max: 10000, integerOnly: true }));
    addError(validateNumericField("pro-ecsa-cs-value", t("label_ecsa_cs_value"), { min: 0.000001 }));
  }

  return errors;
}

function addIfSet(obj, key, value) {
  if (value !== undefined && value !== null && value !== "") {
    obj[key] = value;
  }
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function formatLocalTimestamp() {
  try {
    return new Date().toLocaleTimeString(currentLang === "zh" ? "zh-CN" : "en-US", {
      hour12: false,
    });
  } catch (_err) {
    return new Date().toISOString();
  }
}

function formatMetric(value, digits = 3) {
  if (value === undefined || value === null || value === "") return "-";
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  return String(num.toFixed(digits));
}

function formatTemplateString(template, values) {
  let out = String(template || "");
  Object.keys(values || {}).forEach((key) => {
    out = out.replaceAll(`{${key}}`, String(values[key] ?? ""));
  });
  return out;
}

function renderPlainText(text) {
  return escapeHtml(text).replaceAll("\n", "<br>");
}

function renderInlineMarkdown(escapedText) {
  const codeTokens = [];
  let out = String(escapedText || "");
  out = out.replace(/`([^`\n]+)`/g, (_m, code) => {
    const token = `@@INLINE_CODE_${codeTokens.length}@@`;
    codeTokens.push(`<code>${code}</code>`);
    return token;
  });

  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_m, label, url) => {
    const safeUrl = String(url || "").replaceAll('"', "%22");
    return `<a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${label}</a>`;
  });
  out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

  codeTokens.forEach((html, idx) => {
    out = out.replaceAll(`@@INLINE_CODE_${idx}@@`, html);
  });
  return out;
}

function renderMarkdownContent(text) {
  const raw = String(text || "").replaceAll("\r\n", "\n");
  const codeBlocks = [];
  const withTokens = raw.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    const token = `@@CODE_BLOCK_${codeBlocks.length}@@`;
    codeBlocks.push({
      lang: escapeHtml(lang || ""),
      code: escapeHtml(String(code || "").replace(/\n$/, "")),
    });
    return token;
  });

  const escaped = escapeHtml(withTokens);
  const lines = escaped.split("\n");
  const html = [];
  let paragraph = [];
  let listMode = null;
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map((line) => renderInlineMarkdown(line)).join("<br>")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listMode) return;
    const tag = listMode === "ol" ? "ol" : "ul";
    html.push(`<${tag}>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${tag}>`);
    listMode = null;
    listItems = [];
  };

  lines.forEach((line) => {
    const trimmed = line.trim();
    const codeMatch = trimmed.match(/^@@CODE_BLOCK_(\d+)@@$/);
    if (!trimmed) {
      flushParagraph();
      flushList();
      return;
    }

    if (codeMatch) {
      flushParagraph();
      flushList();
      const idx = Number.parseInt(codeMatch[1], 10);
      const block = codeBlocks[idx];
      if (!block) return;
      const langCls = block.lang ? ` class="language-${block.lang}"` : "";
      html.push(`<pre><code${langCls}>${block.code}</code></pre>`);
      return;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      return;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (listMode && listMode !== "ul") flushList();
      listMode = "ul";
      listItems.push(unorderedMatch[1]);
      return;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listMode && listMode !== "ol") flushList();
      listMode = "ol";
      listItems.push(orderedMatch[1]);
      return;
    }

    if (trimmed.startsWith("&gt;")) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${renderInlineMarkdown(trimmed.replace(/^&gt;\s?/, ""))}</blockquote>`);
      return;
    }

    flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  return html.join("") || renderPlainText(raw);
}

function stripInlineMarkdown(text) {
  return String(text || "")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1")
    .replace(/[`*_#>~-]/g, "")
    .trim();
}

function slugifyHeading(text, seen) {
  const base =
    stripInlineMarkdown(text)
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^\w\u4e00-\u9fff]+/g, "-")
      .replace(/^-+|-+$/g, "") || "section";
  let id = base;
  let idx = 2;
  while (seen.has(id)) {
    id = `${base}-${idx}`;
    idx += 1;
  }
  seen.add(id);
  return id;
}

function renderMarkdownDocument(text) {
  const raw = String(text || "").replaceAll("\r\n", "\n");
  const codeBlocks = [];
  const withTokens = raw.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    const token = `@@CODE_BLOCK_${codeBlocks.length}@@`;
    codeBlocks.push({
      lang: escapeHtml(lang || ""),
      code: escapeHtml(String(code || "").replace(/\n$/, "")),
    });
    return token;
  });

  const rawLines = withTokens.split("\n");
  const escapedLines = escapeHtml(withTokens).split("\n");
  const html = [];
  const toc = [];
  const seenIds = new Set();
  let paragraph = [];
  let listMode = null;
  let listItems = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map((line) => renderInlineMarkdown(line)).join("<br>")}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listMode) return;
    const tag = listMode === "ol" ? "ol" : "ul";
    html.push(`<${tag}>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</${tag}>`);
    listMode = null;
    listItems = [];
  };

  rawLines.forEach((rawLine, idx) => {
    const line = escapedLines[idx] || "";
    const trimmed = line.trim();
    const trimmedRaw = String(rawLine || "").trim();
    const codeMatch = trimmed.match(/^@@CODE_BLOCK_(\d+)@@$/);
    if (!trimmedRaw) {
      flushParagraph();
      flushList();
      return;
    }

    if (codeMatch) {
      flushParagraph();
      flushList();
      const block = codeBlocks[Number.parseInt(codeMatch[1], 10)];
      if (!block) return;
      const langCls = block.lang ? ` class="language-${block.lang}"` : "";
      html.push(`<pre><code${langCls}>${block.code}</code></pre>`);
      return;
    }

    const headingMatch = trimmedRaw.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      const titleRaw = headingMatch[2];
      const titleEscaped = escapeHtml(titleRaw);
      const id = slugifyHeading(titleRaw, seenIds);
      html.push(`<h${level} id="${id}" class="doc-heading level-${level}">${renderInlineMarkdown(titleEscaped)}</h${level}>`);
      if (level >= 2 && level <= 4) {
        toc.push({ id, level, text: stripInlineMarkdown(titleRaw) });
      }
      return;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (listMode && listMode !== "ul") flushList();
      listMode = "ul";
      listItems.push(unorderedMatch[1]);
      return;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listMode && listMode !== "ol") flushList();
      listMode = "ol";
      listItems.push(orderedMatch[1]);
      return;
    }

    if (trimmed.startsWith("&gt;")) {
      flushParagraph();
      flushList();
      html.push(`<blockquote>${renderInlineMarkdown(trimmed.replace(/^&gt;\s?/, ""))}</blockquote>`);
      return;
    }

    flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  return {
    html: html.join("") || renderPlainText(raw),
    toc,
  };
}

function roleTextByRole(role) {
  if (role === "agent") return "AI";
  return currentLang === "zh" ? "用户" : "User";
}

function renderMessageBody(role, content) {
  if (role === "agent") return renderMarkdownContent(content);
  return renderPlainText(content);
}

function renderMessageItem(role, content, timestamp) {
  return `
    <div class="msg ${role}">
      <div class="meta">${roleTextByRole(role)} | ${escapeHtml(timestamp || "")}</div>
      <div class="content">${renderMessageBody(role, content)}</div>
    </div>
  `;
}

function ensureChatLogReady() {
  const log = byId("chat-log");
  if (!log) return null;
  const placeholder = log.querySelector(".placeholder");
  if (placeholder) {
    log.innerHTML = "";
  }
  return log;
}

function appendLocalMessage(role, content) {
  const log = ensureChatLogReady();
  if (!log) return;
  const body = String(content || "").trim();
  if (!body) return;
  log.insertAdjacentHTML("beforeend", renderMessageItem(role, body, formatLocalTimestamp()));
  log.scrollTop = log.scrollHeight;
}

function removeTypingIndicator() {
  const el = byId("chat-typing");
  if (el) el.remove();
}

function showTypingIndicator() {
  const log = ensureChatLogReady();
  if (!log) return;
  removeTypingIndicator();
  log.insertAdjacentHTML(
    "beforeend",
    `
      <div id="chat-typing" class="msg agent typing">
        <div class="meta">AI | ${escapeHtml(t("status_ai_typing"))}</div>
        <div class="content">
          <span>${escapeHtml(t("typing_reply"))}</span>
          <span class="typing-dots"><span></span><span></span><span></span></span>
        </div>
      </div>
    `
  );
  log.scrollTop = log.scrollHeight;
}

function applyI18n() {
  document.documentElement.lang = currentLang === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    el.textContent = t(key);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    el.setAttribute("placeholder", t(key));
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    const key = el.getAttribute("data-i18n-title");
    el.setAttribute("title", t(key));
  });
  const langSelect = byId("lang-select");
  if (langSelect) langSelect.value = currentLang;
  if (byId("project-include-archived")) byId("project-include-archived").checked = projectIncludeArchived;
  if (byId("project-output-type-filter")) byId("project-output-type-filter").value = projectOutputTypeFilter;
  if (byId("project-compare-sort")) byId("project-compare-sort").value = projectCompareSort;
  if (byId("project-compare-only-eta")) byId("project-compare-only-eta").checked = projectCompareOnlyEta;
  if (byId("project-compare-only-tafel")) byId("project-compare-only-tafel").checked = projectCompareOnlyTafel;
  if (byId("project-compare-chart-type")) byId("project-compare-chart-type").value = projectCompareChartType;
  if (byId("project-compare-metric")) byId("project-compare-metric").value = projectCompareMetric;
  if (byId("project-compare-target-current")) byId("project-compare-target-current").value = projectCompareTargetCurrent;
  if (byId("help-panel") && !byId("help-panel").classList.contains("hidden")) loadHelpDocument(true);
  syncAllMatchFieldMeta();
  syncPotentialConversionUI();
  syncProjectCompareControls();
  renderPromptTemplateOptions();
  syncProcessProjectOptions();
  renderProjectList(projectItems);
  renderSelectedProjectDetail();
}

function setSendStatus(text) {
  byId("send-status").textContent = text || "";
}

function setLLMStatus(text) {
  const el = byId("llm-status");
  if (el) el.textContent = text || "";
}

function setProcStatus(text) {
  byId("proc-status").textContent = text || "";
}

function setProjectStatus(text) {
  const el = byId("project-status");
  if (el) el.textContent = text || "";
}

function setFileActionStatus(text) {
  setProcStatus(text);
  setProjectStatus(text);
}

function setTemplateStatus(text) {
  const el = byId("tmpl-status");
  if (el) el.textContent = text || "";
}

function syncProcessProjectOptions() {
  const select = byId("proc-project");
  if (!select) return;
  const previous = String(select.value || "").trim();
  const options = [
    `<option value="">${escapeHtml(t("proc_project_optional"))}</option>`,
    ...projectItems
      .map((item) => {
        const name = String(item && item.name ? item.name : "").trim();
        if (!name) return "";
        return `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`;
      })
      .filter(Boolean),
  ];
  select.innerHTML = options.join("");
  const hasPrevious = projectItems.some(
    (item) => String(item && item.name ? item.name : "").trim() === previous
  );
  select.value = hasPrevious ? previous : "";
}

function syncMatchFieldMeta(baseId, defaultToken) {
  const matchEl = byId(`pro-${baseId}-match`);
  const valueEl = byId(`pro-${baseId}-prefix`);
  const labelEl = byId(`pro-${baseId}-prefix-label`);
  if (!matchEl || !valueEl || !labelEl) return;
  const mode = String(matchEl.value || "prefix").toLowerCase();
  let labelKey = "match_value_prefix";
  let titleKey = "match_title_prefix";
  let placeholderKey = "match_placeholder_prefix";
  if (mode === "contains") {
    labelKey = "match_value_contains";
    titleKey = "match_title_contains";
    placeholderKey = "match_placeholder_contains";
  } else if (mode === "regex") {
    labelKey = "match_value_regex";
    titleKey = "match_title_regex";
    placeholderKey = "match_placeholder_regex";
  }
  labelEl.textContent = t(labelKey);
  valueEl.title = t(titleKey);
  valueEl.placeholder = formatTemplateString(t(placeholderKey), {
    key: baseId,
    default: defaultToken,
  });
}

function syncAllMatchFieldMeta() {
  [
    ["lsv", "LSV"],
    ["cv", "CV"],
    ["eis", "EIS"],
    ["ecsa", "ECSA"],
  ].forEach(([baseId, defaultToken]) => syncMatchFieldMeta(baseId, defaultToken));
}

function setActiveHelpToc(targetId) {
  activeHelpHeadingId = targetId || "";
  document.querySelectorAll(".help-toc-link").forEach((el) => {
    el.classList.toggle("active", el.dataset.target === activeHelpHeadingId);
  });
}

function renderHelpToc(items) {
  const tocEl = byId("help-doc-toc-items");
  if (!tocEl) return;
  const entries = Array.isArray(items) ? items : [];
  if (!entries.length) {
    tocEl.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_toc_empty"))}</div>`;
    setActiveHelpToc("");
    return;
  }
  tocEl.innerHTML = entries
    .map(
      (item) =>
        `<button class="help-toc-link level-${item.level}" type="button" data-target="${escapeHtml(item.id)}">${escapeHtml(item.text)}</button>`
    )
    .join("");
  setActiveHelpToc(entries[0].id);
}

function refreshHelpTocActive() {
  const scrollEl = byId("help-doc-scroll");
  if (!scrollEl) return;
  const headings = [...scrollEl.querySelectorAll(".doc-heading[id]")];
  if (!headings.length) {
    setActiveHelpToc("");
    return;
  }
  const currentTop = scrollEl.scrollTop + 36;
  let activeId = headings[0].id;
  headings.forEach((heading) => {
    if (heading.offsetTop <= currentTop) activeId = heading.id;
  });
  setActiveHelpToc(activeId);
}

function jumpToHelpHeading(targetId) {
  const target = byId(targetId);
  if (!target) return;
  target.scrollIntoView({
    behavior: "smooth",
    block: "start",
    inline: "nearest",
  });
  setActiveHelpToc(targetId);
}

function getCurrentTemplateState() {
  const state = {
    selected_types: getSelectedProcessTypes(),
    values: {},
    checks: {},
  };
  TEMPLATE_VALUE_IDS.forEach((id) => {
    const el = byId(id);
    if (el) state.values[id] = el.value;
  });
  TEMPLATE_CHECK_IDS.forEach((id) => {
    const el = byId(id);
    if (el) state.checks[id] = Boolean(el.checked);
  });
  return state;
}

function applyTemplateState(state) {
  if (!state || typeof state !== "object") return;
  const selected = Array.isArray(state.selected_types) ? state.selected_types.map((x) => String(x).toUpperCase()) : [];
  document.querySelectorAll(".proc-type-check").forEach((el) => {
    el.checked = selected.includes(String(el.value || "").toUpperCase());
  });
  if (!getSelectedProcessTypes().length) {
    const defaultType = document.querySelector('.proc-type-check[value="LSV"]');
    if (defaultType) defaultType.checked = true;
  }
  const values = state.values && typeof state.values === "object" ? state.values : {};
  Object.keys(values).forEach((id) => {
    const el = byId(id);
    if (el && typeof values[id] !== "undefined") {
      el.value = String(values[id]);
    }
  });
  const checks = state.checks && typeof state.checks === "object" ? state.checks : {};
  Object.keys(checks).forEach((id) => {
    const el = byId(id);
    if (el) el.checked = Boolean(checks[id]);
  });
  toggleDataTypePanels();
  syncFeatureBlocks();
  syncPotentialConversionUI();
}

function renderTemplateOptions() {
  const select = byId("tmpl-select");
  if (!select) return;
  const prev = select.value;
  select.innerHTML = "";
  if (!Array.isArray(templateItems) || !templateItems.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = t("template_none");
    select.appendChild(opt);
    select.value = "";
    return;
  }
  templateItems.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = String(item.name || "");
    const suffix = item.builtin ? ` [${t("template_builtin_tag")}]` : "";
    opt.textContent = `${item.name || ""}${suffix}`;
    select.appendChild(opt);
  });
  if (prev && templateItems.some((x) => x.name === prev)) {
    select.value = prev;
  }
}

async function loadTemplates() {
  try {
    const resp = await fetch("/api/v1/process/templates");
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("template_load_failed"));
    }
    templateItems = Array.isArray(data.templates) ? data.templates : [];
    renderTemplateOptions();
    setTemplateStatus("");
  } catch (err) {
    templateItems = [];
    renderTemplateOptions();
    setTemplateStatus(`${t("template_load_failed")}: ${err.message}`);
  }
}

async function saveTemplate(overwrite = false) {
  const name = textValue("tmpl-name") || byId("tmpl-select").value;
  if (!name) {
    setTemplateStatus(t("template_name_required"));
    return;
  }
  try {
    const resp = await fetch("/api/v1/process/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        state: getCurrentTemplateState(),
        overwrite,
      }),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      if (data.code === "already_exists" && !overwrite && window.confirm(t("template_confirm_overwrite"))) {
        await saveTemplate(true);
        return;
      }
      throw new Error(data.message || t("template_save_failed"));
    }
    await loadTemplates();
    byId("tmpl-name").value = name;
    byId("tmpl-select").value = name;
    setTemplateStatus(t("template_saved"));
  } catch (err) {
    const msg = String(err && err.message ? err.message : "");
    if (msg.toLowerCase().includes("not found")) {
      setTemplateStatus(`${t("template_save_failed")}: ${msg}. ${t("template_restart_hint")}`);
    } else {
      setTemplateStatus(`${t("template_save_failed")}: ${msg}`);
    }
  }
}

function loadSelectedTemplate() {
  const name = byId("tmpl-select").value;
  if (!name) return;
  const found = templateItems.find((item) => item.name === name);
  if (!found) {
    setTemplateStatus(t("template_load_failed"));
    return;
  }
  applyTemplateState(found.state || {});
  byId("tmpl-name").value = name;
  setTemplateStatus(t("template_loaded"));
}

async function deleteSelectedTemplate() {
  const name = byId("tmpl-select").value;
  if (!name) return;
  const found = templateItems.find((item) => item.name === name);
  if (found && found.builtin) {
    setTemplateStatus(t("template_builtin_immutable"));
    return;
  }
  if (!window.confirm(t("template_confirm_delete"))) return;
  try {
    const resp = await fetch(`/api/v1/process/templates/${encodeURIComponent(name)}/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("template_delete_failed"));
    }
    await loadTemplates();
    byId("tmpl-name").value = "";
    setTemplateStatus(t("template_deleted"));
  } catch (err) {
    setTemplateStatus(`${t("template_delete_failed")}: ${err.message}`);
  }
}

function renderResultPlaceholder() {
  hasProcessResult = false;
  byId("proc-result-summary").textContent = t("result_empty");
  byId("proc-result-types").textContent = "-";
  byId("proc-result-files").classList.remove("action-list");
  byId("proc-result-files").innerHTML = "<li>-</li>";
  byId("proc-result-quality").innerHTML = "<li>-</li>";
  byId("proc-result-error-wrap").classList.add("hidden");
  byId("proc-result-error").textContent = "-";
}

function renderProcessResult(result) {
  hasProcessResult = true;
  const panel = byId("proc-result-panel");
  const summaryEl = byId("proc-result-summary");
  const typesEl = byId("proc-result-types");
  const filesEl = byId("proc-result-files");
  const qualityEl = byId("proc-result-quality");
  const errWrap = byId("proc-result-error-wrap");
  const errText = byId("proc-result-error");

  panel.classList.remove("hidden");
  errWrap.classList.add("hidden");
  errText.textContent = "-";

  const summary = (result && result.summary) || t("result_empty");
  summaryEl.textContent = summary;

  const dataTypes = Array.isArray(result && result.data_types)
    ? result.data_types
    : result && result.data_type
      ? [String(result.data_type)]
      : [];
  typesEl.textContent = dataTypes.length ? dataTypes.join(", ") : "-";

  const files = ((result && result.processing) || {}).output_files || [];
  if (Array.isArray(files) && files.length) {
    filesEl.classList.add("action-list");
    filesEl.innerHTML = files
      .map((f) => {
        const pathText = String(f || "").trim();
        const fileName = pathText.split(/[\\/]/).pop() || pathText;
        return `
          <li class="output-file-item proc-output-file-item">
            <div class="name">${escapeHtml(fileName)}</div>
            <div class="path">${escapeHtml(pathText)}</div>
            <div class="file-actions">
              <button class="btn mini" type="button" data-copy-path="${escapeHtml(pathText)}">${escapeHtml(t("btn_copy_path"))}</button>
              <button class="btn mini" type="button" data-open-path="${escapeHtml(pathText)}">${escapeHtml(t("btn_open_file"))}</button>
              <button class="btn mini" type="button" data-open-dir="${escapeHtml(pathText)}">${escapeHtml(t("btn_open_dir"))}</button>
            </div>
          </li>
        `;
      })
      .join("");
    bindProjectFileActions(filesEl);
  } else {
    filesEl.classList.remove("action-list");
    filesEl.innerHTML = "<li>-</li>";
  }

  const quality = (result && result.quality_summary) || {};
  const qItems = [];
  const consumed = new Set();
  if (quality.total_files !== undefined) qItems.push(`${t("result_quality_total")}: ${quality.total_files}`);
  if (quality.total_files !== undefined) consumed.add("total_files");
  if (quality.passed !== undefined) qItems.push(`${t("result_quality_passed")}: ${quality.passed}`);
  if (quality.passed !== undefined) consumed.add("passed");
  if (quality.failed !== undefined) qItems.push(`${t("result_quality_failed")}: ${quality.failed}`);
  if (quality.failed !== undefined) consumed.add("failed");
  if (quality.warnings !== undefined) qItems.push(`${t("result_quality_warnings")}: ${quality.warnings}`);
  if (quality.warnings !== undefined) consumed.add("warnings");
  Object.keys(quality || {}).forEach((key) => {
    if (consumed.has(key)) return;
    const val = quality[key];
    if (val === undefined || val === null) return;
    const text = typeof val === "object" ? JSON.stringify(val) : String(val);
    qItems.push(`${key}: ${text}`);
  });
  qualityEl.innerHTML = qItems.length ? qItems.map((it) => `<li>${escapeHtml(it)}</li>`).join("") : "<li>-</li>";
}

function renderProcessError(message) {
  hasProcessResult = true;
  const panel = byId("proc-result-panel");
  const summaryEl = byId("proc-result-summary");
  const typesEl = byId("proc-result-types");
  const filesEl = byId("proc-result-files");
  const qualityEl = byId("proc-result-quality");
  const errWrap = byId("proc-result-error-wrap");
  const errText = byId("proc-result-error");

  panel.classList.remove("hidden");
  summaryEl.textContent = t("proc_failed");
  typesEl.textContent = "-";
  filesEl.classList.remove("action-list");
  filesEl.innerHTML = "<li>-</li>";
  qualityEl.innerHTML = "<li>-</li>";
  errWrap.classList.remove("hidden");
  errText.textContent = message || t("proc_failed");
}

function setSystemStatus(state, text, version) {
  const btn = byId("sys-status-btn");
  const textEl = byId("sys-status-text");
  const panelHealth = byId("sys-panel-health");
  const panelVersion = byId("sys-panel-version");

  if (btn) {
    btn.classList.remove("pending", "ok", "error");
    btn.classList.add(state);
  }
  if (textEl) textEl.textContent = text || "-";
  if (panelHealth) panelHealth.textContent = text || "-";
  if (panelVersion) panelVersion.textContent = version || "-";
}

function openSystemPanel() {
  byId("sys-panel-mask").classList.remove("hidden");
  byId("sys-panel").classList.remove("hidden");
}

function closeSystemPanel() {
  byId("sys-panel-mask").classList.add("hidden");
  byId("sys-panel").classList.add("hidden");
}

function getHelpDocUrls() {
  if (currentLang === "en") {
    return ["/ui/static/help_manual.en.md", "/ui/static/help_manual.zh.md"];
  }
  return ["/ui/static/help_manual.zh.md"];
}

async function loadHelpDocument(force = false) {
  const body = byId("help-doc-body");
  const tocEl = byId("help-doc-toc-items");
  const scrollEl = byId("help-doc-scroll");
  if (!body || !tocEl || !scrollEl) return;
  const cacheKey = currentLang;
  if (!force && helpDocCache[cacheKey]) {
    const rendered = renderMarkdownDocument(helpDocCache[cacheKey]);
    body.innerHTML = rendered.html || `<div class="placeholder">${escapeHtml(t("help_docs_empty"))}</div>`;
    renderHelpToc(rendered.toc);
    scrollEl.scrollTop = 0;
    refreshHelpTocActive();
    return;
  }
  body.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_loading"))}</div>`;
  tocEl.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_loading"))}</div>`;
  let loaded = "";
  let lastError = null;
  for (const url of getHelpDocUrls()) {
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const text = await resp.text();
      if (text.trim()) {
        loaded = text;
        break;
      }
    } catch (err) {
      lastError = err;
    }
  }
  if (!loaded.trim()) {
    body.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_failed"))}${lastError ? `: ${escapeHtml(lastError.message || "")}` : ""}</div>`;
    tocEl.innerHTML = `<div class="placeholder">${escapeHtml(t("help_docs_toc_empty"))}</div>`;
    return;
  }
  helpDocCache[cacheKey] = loaded;
  const rendered = renderMarkdownDocument(loaded);
  body.innerHTML = rendered.html || `<div class="placeholder">${escapeHtml(t("help_docs_empty"))}</div>`;
  renderHelpToc(rendered.toc);
  scrollEl.scrollTop = 0;
  refreshHelpTocActive();
}

function openHelpPanel() {
  byId("help-panel-mask").classList.remove("hidden");
  byId("help-panel").classList.remove("hidden");
  loadHelpDocument();
}

function closeHelpPanel() {
  byId("help-panel-mask").classList.add("hidden");
  byId("help-panel").classList.add("hidden");
}

function openAISettingsPanel() {
  byId("ai-settings-mask").classList.remove("hidden");
  byId("ai-settings-panel").classList.remove("hidden");
}

function closeAISettingsPanel() {
  byId("ai-settings-mask").classList.add("hidden");
  byId("ai-settings-panel").classList.add("hidden");
}

function loadPromptSettings() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(PROMPT_STORAGE_KEY) || "null");
  } catch (_err) {
    saved = null;
  }
  const enabled = saved && typeof saved.enabled === "boolean" ? saved.enabled : true;
  const template = saved && typeof saved.template === "string" ? saved.template : "analyst";
  const prefix =
    saved && typeof saved.prefix === "string" && saved.prefix.trim()
      ? saved.prefix
      : PROMPT_TEMPLATES[template] || PROMPT_TEMPLATES.analyst;
  byId("prompt-enabled").checked = enabled;
  byId("prompt-template").value = template;
  byId("prompt-prefix").value = prefix;
}

function renderPromptTemplateOptions() {
  const select = byId("prompt-template");
  if (!select) return;
  const current = select.value || "analyst";
  select.innerHTML = "";
  const options = [
    { key: "analyst", label: t("prompt_tpl_analyst") },
    { key: "summary", label: t("prompt_tpl_summary") },
    { key: "paper", label: t("prompt_tpl_paper") },
  ];
  options.forEach((it) => {
    const op = document.createElement("option");
    op.value = it.key;
    op.textContent = it.label;
    select.appendChild(op);
  });
  select.value = options.some((it) => it.key === current) ? current : "analyst";
}

function savePromptSettings() {
  const enabled = Boolean(byId("prompt-enabled").checked);
  const template = textValue("prompt-template") || "analyst";
  const prefix = String(byId("prompt-prefix").value || "").trim();
  localStorage.setItem(
    PROMPT_STORAGE_KEY,
    JSON.stringify({
      enabled,
      template,
      prefix,
    })
  );
  if (!prefix && enabled) {
    byId("prompt-enabled").checked = false;
    setLLMStatus(t("status_prompt_empty"));
    return;
  }
  setLLMStatus(t("status_prompt_saved"));
}

function applyPromptTemplate() {
  const template = textValue("prompt-template") || "analyst";
  const text = PROMPT_TEMPLATES[template] || PROMPT_TEMPLATES.analyst;
  byId("prompt-prefix").value = text;
  setLLMStatus(t("status_prompt_applied"));
}

function buildPromptedMessage(message) {
  const raw = String(message || "").trim();
  const enabled = Boolean(byId("prompt-enabled") && byId("prompt-enabled").checked);
  const prefix = String((byId("prompt-prefix") && byId("prompt-prefix").value) || "").trim();
  if (!enabled || !prefix) return raw;
  if (!raw) return prefix;
  return `${prefix}\n\n${raw}`;
}

function switchTab(tabName) {
  const tabs = ["pro", "ai", "project"];
  tabs.forEach((name) => {
    const active = tabName === name;
    const btn = byId(`tab-btn-${name}`);
    const panel = byId(`tab-${name}`);
    if (btn) btn.classList.toggle("active", active);
    if (panel) panel.classList.toggle("active", active);
  });
}

function renderMessages(messages) {
  const log = byId("chat-log");
  removeTypingIndicator();
  if (!Array.isArray(messages) || messages.length === 0) {
    log.innerHTML = `<div class="placeholder">${t("chat_no_messages")}</div>`;
    return;
  }
  log.innerHTML = messages
    .map((m) => {
      const role = m.role === "agent" ? "agent" : "user";
      return renderMessageItem(role, m.content || "", m.timestamp || "");
    })
    .join("");
  log.scrollTop = log.scrollHeight;
}

async function deleteConversation(conversationId) {
  if (!conversationId) return;
  setSendStatus(t("status_delete_running"));
  try {
    const resp = await fetch(`/api/v1/agent/conversations/${conversationId}/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_delete_failed"));
    }
    if (conversationId === currentConversationId) {
      currentConversationId = null;
      byId("conv-title").textContent = t("conv_new");
      byId("conv-meta").textContent = t("conv_new_hint");
      renderMessages([]);
    }
    await loadConversations();
    setSendStatus(t("status_delete_success"));
  } catch (err) {
    setSendStatus(`${t("status_delete_failed")}: ${err.message}`);
  }
}

async function renameConversation(conversationId, nextTitleInput) {
  if (!conversationId) return;
  const target = (conversationItems || []).find((it) => it.conversation_id === conversationId);
  const oldTitle = (target && target.title) || t("conv_rename_default");
  const title = String(nextTitleInput || "").trim();
  if (!title) {
    setSendStatus(t("status_rename_empty"));
    return;
  }
  setSendStatus(t("status_rename_running"));
  try {
    const resp = await fetch(`/api/v1/agent/conversations/${conversationId}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_rename_failed"));
    }
    if (conversationId === currentConversationId) {
      byId("conv-title").textContent = title;
    }
    renamingConversationId = null;
    await loadConversations();
    setSendStatus(t("status_rename_success"));
  } catch (err) {
    setSendStatus(`${t("status_rename_failed")}: ${err.message}`);
  }
}

function renderConversations(items) {
  const listEl = byId("conv-list");
  conversationItems = Array.isArray(items) ? items : [];
  if (renamingConversationId && !conversationItems.some((it) => it.conversation_id === renamingConversationId)) {
    renamingConversationId = null;
  }
  if (conversationItems.length === 0) {
    listEl.innerHTML = `<div class="placeholder">${t("chat_no_conversations")}</div>`;
    return;
  }

  listEl.innerHTML = conversationItems
    .map((it) => {
      const active = it.conversation_id === currentConversationId ? "active" : "";
      const title = it.title || t("conv_rename_default");
      const editing = it.conversation_id === renamingConversationId;
      return `
        <div class="conv-item ${active}" data-id="${it.conversation_id}">
          <div class="conv-actions">
            ${
              editing
                ? `
                  <button class="conv-save" data-save="${it.conversation_id}" title="${escapeHtml(t("btn_save"))}">${escapeHtml(t("btn_save"))}</button>
                  <button class="conv-cancel" data-cancel="${it.conversation_id}" title="${escapeHtml(t("btn_close"))}">${escapeHtml(t("btn_close"))}</button>
                `
                : `
                  <button class="conv-rename" data-rename="${it.conversation_id}" title="${escapeHtml(t("conv_rename_action"))}">${escapeHtml(t("conv_rename_action"))}</button>
                  <button class="conv-del" data-del="${it.conversation_id}" title="${escapeHtml(t("conv_delete_action"))}">${escapeHtml(t("conv_delete_action"))}</button>
                `
            }
          </div>
          ${
            editing
              ? `<input class="conv-title-input" data-rename-input="${it.conversation_id}" value="${escapeHtml(title)}" maxlength="80">`
              : `<div class="title">${escapeHtml(title)}</div>`
          }
          <div class="meta">${escapeHtml(it.provider || "-")} | ${escapeHtml(it.updated_at || "")}</div>
        </div>
      `;
    })
    .join("");

  listEl.querySelectorAll(".conv-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".conv-actions") || e.target.closest(".conv-title-input")) return;
      openConversation(el.dataset.id);
    });
  });

  listEl.querySelectorAll(".conv-del").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteConversation(btn.dataset.del);
    });
  });

  listEl.querySelectorAll(".conv-rename").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      renamingConversationId = btn.dataset.rename;
      renderConversations(conversationItems);
      const input = listEl.querySelector(`.conv-title-input[data-rename-input="${renamingConversationId}"]`);
      if (input) {
        input.focus();
        try {
          input.setSelectionRange(0, input.value.length);
        } catch (_err) {}
      }
    });
  });

  listEl.querySelectorAll(".conv-save").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const cid = btn.dataset.save;
      const input = listEl.querySelector(`.conv-title-input[data-rename-input="${cid}"]`);
      renameConversation(cid, input ? input.value : "");
    });
  });

  listEl.querySelectorAll(".conv-cancel").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      renamingConversationId = null;
      renderConversations(conversationItems);
    });
  });

  listEl.querySelectorAll(".conv-title-input").forEach((input) => {
    input.addEventListener("click", (e) => e.stopPropagation());
    input.addEventListener("keydown", (e) => {
      const cid = input.getAttribute("data-rename-input") || "";
      if (e.key === "Enter") {
        e.preventDefault();
        renameConversation(cid, input.value);
      } else if (e.key === "Escape") {
        e.preventDefault();
        renamingConversationId = null;
        renderConversations(conversationItems);
      }
    });
  });
}

async function fetchHealth() {
  setSystemStatus("pending", t("health_checking"), "-");
  try {
    const resp = await fetch("/health");
    const data = await resp.json();
    if (resp.ok && data.status === "ok") {
      setSystemStatus("ok", t("health_online"), data.version || "unknown");
      return;
    }
    setSystemStatus("error", t("health_error"), "-");
  } catch (_err) {
    setSystemStatus("error", t("health_offline"), "-");
  }
}

function listLLMProviders() {
  return Object.keys(llmModelsByProvider || {}).filter((k) => {
    const v = llmModelsByProvider[k];
    return v && typeof v === "object";
  });
}

function updateLLMKeyHint(provider) {
  const hintEl = byId("llm-key-hint");
  if (!hintEl) return;
  const entry = (provider && llmModelsByProvider[provider]) || {};
  hintEl.textContent = entry && entry.has_api_key ? t("llm_key_configured") : t("llm_key_missing");
}

function applyLLMProviderPreset(provider) {
  const entry = (provider && llmModelsByProvider[provider]) || {};
  if (Object.keys(entry).length === 0) {
    updateLLMKeyHint(provider);
    return;
  }
  if (byId("llm-model")) byId("llm-model").value = String(entry.model || "");
  if (byId("llm-base-url")) byId("llm-base-url").value = String(entry.base_url || "");
  if (byId("llm-timeout")) byId("llm-timeout").value = entry.timeout !== undefined ? String(entry.timeout) : "";
  updateLLMKeyHint(provider);
}

function renderLLMProviders(defaultProvider) {
  const select = byId("llm-provider");
  if (!select) return;
  const providers = listLLMProviders();
  const previous = select.value;
  if (!providers.length) {
    select.innerHTML = '<option value="">-</option>';
    select.value = "";
    applyLLMProviderPreset("");
    return;
  }
  select.innerHTML = "";
  providers.forEach((p) => {
    const op = document.createElement("option");
    op.value = p;
    op.textContent = p;
    select.appendChild(op);
  });
  const pick = providers.includes(previous)
    ? previous
    : providers.includes(defaultProvider)
      ? defaultProvider
      : providers[0];
  select.value = pick;
  applyLLMProviderPreset(pick);
}

async function loadLLMConfig() {
  setLLMStatus(t("status_llm_loading"));
  try {
    const resp = await fetch("/api/v1/llm/config");
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_llm_load_failed"));
    }
    llmModelsByProvider = data.models || {};
    renderLLMProviders(data.default_provider || "");
    setLLMStatus(t("status_llm_loaded"));
  } catch (err) {
    setLLMStatus(`${t("status_llm_load_failed")}: ${err.message}`);
  }
}

async function saveLLMConfig() {
  const provider = textValue("llm-provider");
  if (!provider) {
    setLLMStatus(t("status_llm_provider_required"));
    return;
  }
  const payload = { provider };
  let hasChanges = false;

  const model = textValue("llm-model");
  if (model) {
    payload.model = model;
    hasChanges = true;
  }

  const baseUrl = textValue("llm-base-url");
  if (baseUrl) {
    payload.base_url = baseUrl;
    hasChanges = true;
  }

  const timeoutRaw = textValue("llm-timeout");
  if (timeoutRaw) {
    const timeout = Number.parseInt(timeoutRaw, 10);
    if (!Number.isInteger(timeout) || timeout <= 0) {
      setLLMStatus(t("status_llm_timeout_invalid"));
      return;
    }
    payload.timeout = timeout;
    hasChanges = true;
  }

  const apiKey = textValue("llm-api-key");
  if (apiKey) {
    payload.api_key = apiKey;
    hasChanges = true;
  }

  if (!hasChanges) {
    setLLMStatus(t("status_llm_no_changes"));
    return;
  }

  setLLMStatus(t("status_llm_save_running"));
  try {
    const resp = await fetch("/api/v1/llm/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_llm_save_failed"));
    }
    const current = llmModelsByProvider[provider] || {};
    const nextCfg = data.config || {};
    llmModelsByProvider[provider] = { ...current, ...nextCfg };
    if (apiKey) {
      llmModelsByProvider[provider].has_api_key = true;
      byId("llm-api-key").value = "";
    }
    renderLLMProviders(provider);
    setLLMStatus(t("status_llm_save_success"));
  } catch (err) {
    setLLMStatus(`${t("status_llm_save_failed")}: ${err.message}`);
  }
}

function buildConversationListUrl() {
  const query = new URLSearchParams();
  query.set("page", "1");
  query.set("page_size", "30");
  if (currentConversationKeyword) {
    query.set("keyword", currentConversationKeyword);
  }
  return `/api/v1/agent/conversations?${query.toString()}`;
}

function applyConversationFilter() {
  currentConversationKeyword = textValue("conv-search");
  loadConversations();
}

function clearConversationFilter() {
  currentConversationKeyword = "";
  byId("conv-search").value = "";
  loadConversations();
}

async function loadConversations() {
  setSendStatus(t("status_loading_conversations"));
  try {
    const resp = await fetch(buildConversationListUrl());
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_load_failed"));
    }
    const items = data.items || [];
    renderConversations(items);
    if (!currentConversationId && items.length > 0) {
      await openConversation(items[0].conversation_id, true);
    } else if (currentConversationId) {
      const exists = items.some((i) => i.conversation_id === currentConversationId);
      if (!exists) currentConversationId = null;
    }
    setSendStatus("");
  } catch (err) {
    setSendStatus(`${t("status_load_failed")}: ${err.message}`);
  }
}

async function openConversation(conversationId, skipListReload = false) {
  if (!conversationId) return;
  currentConversationId = conversationId;
  const resp = await fetch(`/api/v1/agent/conversations/${conversationId}`);
  const data = await resp.json();
  if (!resp.ok || data.status !== "success") {
    setSendStatus(data.message || t("status_load_failed"));
    return;
  }
  const conv = data.conversation || {};
  byId("conv-title").textContent = conv.title || conv.project_name || t("conv_rename_default");
  byId("conv-meta").textContent = `ID: ${conv.conversation_id || "-"} | ${conv.provider || "-"}`;
  renderMessages(conv.messages || []);

  if (!skipListReload) {
    await loadConversations();
  }
}

async function sendMessage() {
  const msgEl = byId("msg-input");
  const fileEl = byId("zip-file");
  const projectEl = byId("project-name");
  const dataTypeEl = byId("data-type");
  const sendBtn = byId("send-btn");
  const provider = textValue("llm-provider");
  const model = textValue("llm-model");

  if (sendBtn && sendBtn.disabled) return;

  const message = (msgEl.value || "").trim();
  const promptedMessage = buildPromptedMessage(message);
  const file = fileEl.files && fileEl.files[0] ? fileEl.files[0] : null;

  if (!promptedMessage && !file) {
    setSendStatus(t("status_send_empty"));
    return;
  }

  if (file && !file.name.toLowerCase().endsWith(".zip")) {
    setSendStatus(t("status_zip_only"));
    return;
  }

  const localText = message || `${t("msg_zip_attached")}: ${file ? file.name : "-"}`;
  appendLocalMessage("user", localText);
  showTypingIndicator();
  setSendStatus(t("status_waiting_reply"));
  if (sendBtn) sendBtn.disabled = true;
  msgEl.value = "";
  fileEl.value = "";

  try {
    let resp;
    if (file) {
      const fd = new FormData();
      if (promptedMessage) fd.append("message", promptedMessage);
      fd.append("file", file);
      if (currentConversationId) fd.append("conversation_id", currentConversationId);
      if (projectEl.value.trim()) fd.append("project_name", projectEl.value.trim());
      if (dataTypeEl.value) fd.append("data_type", dataTypeEl.value);
      if (provider) fd.append("provider", provider);
      if (model) fd.append("model", model);
      resp = await fetch("/api/v1/agent/messages", { method: "POST", body: fd });
    } else {
      resp = await fetch("/api/v1/agent/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: promptedMessage,
          conversation_id: currentConversationId,
          project_name: projectEl.value.trim() || undefined,
          data_type: dataTypeEl.value || undefined,
          provider: provider || undefined,
          model: model || undefined,
        }),
      });
    }

    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("status_send_failed"));
    }

    currentConversationId = data.conversation_id || currentConversationId;
    const conv = data.conversation || null;

    if (conv) {
      byId("conv-title").textContent = conv.title || conv.project_name || t("conv_rename_default");
      byId("conv-meta").textContent = `ID: ${conv.conversation_id || "-"} | ${conv.provider || "-"}`;
      renderMessages(conv.messages || []);
    } else if (Array.isArray(data.messages)) {
      renderMessages(data.messages);
    } else {
      removeTypingIndicator();
    }

    setSendStatus(t("status_send_success"));
    await loadConversations();
  } catch (err) {
    removeTypingIndicator();
    setSendStatus(`${t("status_send_failed")}: ${err.message}`);
  } finally {
    if (sendBtn) sendBtn.disabled = false;
  }
}

function historyRecordKey(record) {
  if (!record) return "";
  const file = record.file_path || record.file_name || record.sample_name || "";
  return `${record.timestamp || ""}|${record.type || ""}|${file}`;
}

function buildResultFromHistoryRecord(record) {
  const type = String(record.type || "").toUpperCase();
  const sample = record.sample_name || record.file_name || record.file_path || "-";
  const results = record && typeof record.results === "object" && record.results ? record.results : {};
  const quality = {
    status: record.status || "-",
    project: record.project_name || "-",
    timestamp: record.timestamp || "-",
  };
  let count = 0;
  Object.keys(results).forEach((key) => {
    if (count >= 8) return;
    const value = results[key];
    if (typeof value === "object") return;
    quality[key] = value;
    count += 1;
  });
  const files = Array.isArray(record.output_files) && record.output_files.length
    ? record.output_files.map((item) => String(item))
    : record.summary_path
      ? [String(record.summary_path)]
      : record.file_path || record.file_name
        ? [String(record.file_path || record.file_name)]
        : [];
  return {
    summary: `${t("result_from_history")}: ${sample}`,
    data_type: type || undefined,
    data_types: type ? [type] : [],
    processing: { output_files: files },
    quality_summary: quality,
  };
}

function viewHistoryRecord(index) {
  const i = Number(index);
  if (!Number.isInteger(i) || i < 0 || i >= historyRecords.length) return;
  const record = historyRecords[i];
  selectedHistoryKey = historyRecordKey(record);
  renderProcessResult(buildResultFromHistoryRecord(record));
  setProcStatus(t("status_history_loaded"));
  byId("history-list").querySelectorAll(".history-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.key === selectedHistoryKey);
  });
}

function renderHistory(records) {
  const listEl = byId("history-list");
  historyRecords = Array.isArray(records) ? records : [];
  if (historyRecords.length === 0) {
    listEl.innerHTML = `<div class="placeholder">${t("no_history")}</div>`;
    return;
  }
  listEl.innerHTML = historyRecords
    .slice(0, 20)
    .map((r, idx) => {
      const key = historyRecordKey(r);
      const active = key === selectedHistoryKey ? "active" : "";
      const name = r.sample_name || r.file_name || r.file_path || "unknown";
      return `
        <div class="history-item ${active}" data-index="${idx}" data-key="${escapeHtml(key)}">
          <div class="name">${escapeHtml(name)}</div>
          <div class="meta">${escapeHtml(r.type || "-")} | ${escapeHtml(r.timestamp || "")}</div>
        </div>
      `;
    })
    .join("");
  listEl.querySelectorAll(".history-item").forEach((el) => {
    el.addEventListener("click", () => viewHistoryRecord(el.dataset.index));
  });
}

function renderStats(data) {
  byId("stat-total").textContent = String(data.total_files || 0);
  byId("stat-lsv").textContent = String(data.lsv_count || 0);
  byId("stat-cv").textContent = String(data.cv_count || 0);
  byId("stat-eis").textContent = String(data.eis_count || 0);
  byId("stat-ecsa").textContent = String(data.ecsa_count || 0);
}

function renderProjectStats(data) {
  const safe = data && typeof data === "object" ? data : {};
  byId("project-stat-total").textContent = String(safe.total_files || 0);
  byId("project-stat-lsv").textContent = String(safe.lsv_count || 0);
  byId("project-stat-cv").textContent = String(safe.cv_count || 0);
  byId("project-stat-eis").textContent = String(safe.eis_count || 0);
  byId("project-stat-ecsa").textContent = String(safe.ecsa_count || 0);
}

function setProjectEditForm(project) {
  const saveBtn = byId("project-save-btn");
  const safe = project && typeof project === "object" ? project : null;
  if (byId("project-edit-name")) byId("project-edit-name").value = safe ? String(safe.name || "") : "";
  if (byId("project-edit-color")) byId("project-edit-color").value = safe ? String(safe.color || "") : "";
  if (byId("project-edit-tags")) {
    const tags = safe && Array.isArray(safe.tags) ? safe.tags.join(", ") : "";
    byId("project-edit-tags").value = tags;
  }
  if (byId("project-edit-desc")) byId("project-edit-desc").value = safe ? String(safe.description || "") : "";
  if (saveBtn) saveBtn.disabled = !safe;
}

function getSelectedProjectHistoryRecord() {
  const state = projectDetailState && typeof projectDetailState === "object" ? projectDetailState : {};
  const history = Array.isArray(state.history) ? state.history : [];
  return history.find((item) => historyRecordKey(item) === selectedProjectHistoryKey) || null;
}

function renderProjectHistoryDetail(record) {
  const wrap = byId("project-history-detail");
  const openBtn = byId("project-open-result-btn");
  const archiveBtn = byId("project-archive-history-btn");
  const deleteBtn = byId("project-delete-history-btn");
  if (!wrap) return;
  if (!record) {
    wrap.innerHTML = `<div class="placeholder">${t("project_select_history")}</div>`;
    if (openBtn) openBtn.disabled = true;
    if (archiveBtn) archiveBtn.disabled = true;
    if (deleteBtn) deleteBtn.disabled = true;
    return;
  }
  if (openBtn) openBtn.disabled = false;
  if (archiveBtn) archiveBtn.disabled = false;
  if (deleteBtn) deleteBtn.disabled = false;
  const results = record && typeof record.results === "object" && record.results ? record.results : {};
  const resultItems = Object.keys(results).length
    ? Object.keys(results)
        .map((key) => {
          const value = results[key];
          const text = typeof value === "object" ? JSON.stringify(value) : String(value);
          return `<li><strong>${escapeHtml(String(key))}</strong>: ${escapeHtml(text)}</li>`;
        })
        .join("")
    : "<li>-</li>";
  const related = [];
  if (record.file_path) related.push(String(record.file_path));
  if (record.file_name && record.file_name !== record.file_path) related.push(String(record.file_name));
  if (record.summary_path) related.push(String(record.summary_path));
  if (Array.isArray(record.output_files)) {
    record.output_files.forEach((item) => {
      const text = String(item || "").trim();
      if (text) related.push(text);
    });
  }
  const uniqueRelated = Array.from(new Set(related));
  wrap.innerHTML = `
    <div class="project-history-meta">
      <div><strong>${escapeHtml(String(record.sample_name || "-"))}</strong></div>
      <div>${escapeHtml(String(record.type || "-"))} | ${escapeHtml(String(record.timestamp || "-"))} | ${escapeHtml(
        String(record.status || "-")
      )}</div>
    </div>
    <div class="project-history-sections">
      <section class="project-history-subblock">
        <div class="proc-block-title">${escapeHtml(t("project_related_files"))}</div>
        <ul class="proc-list">
          ${uniqueRelated.length ? uniqueRelated.map((item) => `<li>${escapeHtml(item)}</li>`).join("") : "<li>-</li>"}
        </ul>
      </section>
      <section class="project-history-subblock">
        <div class="proc-block-title">${escapeHtml(t("project_result_metrics"))}</div>
        <ul class="proc-list">${resultItems}</ul>
      </section>
    </div>
  `;
}

function selectProjectHistory(index) {
  const state = projectDetailState && typeof projectDetailState === "object" ? projectDetailState : {};
  const history = Array.isArray(state.history) ? state.history : [];
  const i = Number(index);
  if (!Number.isInteger(i) || i < 0 || i >= history.length) return;
  const record = history[i];
  selectedProjectHistoryKey = historyRecordKey(record);
  renderProjectHistory(history);
  renderProjectHistoryDetail(record);
}

function renderProjectHistory(records) {
  const listEl = byId("project-history-list");
  if (!listEl) return;
  const items = Array.isArray(records) ? records : [];
  if (!items.length) {
    listEl.innerHTML = `<div class="placeholder">${t("project_no_history")}</div>`;
    renderProjectHistoryDetail(null);
    return;
  }
  if (!items.some((r) => historyRecordKey(r) === selectedProjectHistoryKey)) {
    selectedProjectHistoryKey = historyRecordKey(items[0]);
  }
  listEl.innerHTML = items
    .slice(0, 20)
    .map((r, idx) => {
      const name = r.sample_name || r.file_name || r.file_path || "unknown";
      const type = r.type || "-";
      const time = r.timestamp || "-";
      const status = r.status || "-";
      const key = historyRecordKey(r);
      const active = key === selectedProjectHistoryKey ? "active" : "";
      return `
        <div class="history-item ${active}" data-project-history-index="${idx}" data-key="${escapeHtml(key)}">
          <div class="name">${escapeHtml(name)}</div>
          <div class="meta">${escapeHtml(type)} | ${escapeHtml(time)} | ${escapeHtml(status)}</div>
        </div>
      `;
    })
    .join("");
  listEl.querySelectorAll(".history-item").forEach((el) => {
    el.addEventListener("click", () => {
      selectProjectHistory(el.getAttribute("data-project-history-index"));
    });
  });
  const selected = items.find((r) => historyRecordKey(r) === selectedProjectHistoryKey) || items[0];
  renderProjectHistoryDetail(selected);
}

function renderProjectLSVSummary(summary) {
  const wrap = byId("project-lsv-table");
  if (!wrap) return;
  const payload = summary && typeof summary === "object" ? summary : {};
  const samples = Array.isArray(payload.samples) ? payload.samples : [];
  if (!samples.length) {
    wrap.innerHTML = `<div class="placeholder">${t("project_no_lsv")}</div>`;
    return;
  }
  wrap.innerHTML = `
    <table class="lsv-summary-table">
      <thead>
        <tr>
          <th>${escapeHtml(t("project_lsv_col_sample"))}</th>
          <th>${escapeHtml(t("project_lsv_col_eta"))}</th>
          <th>${escapeHtml(t("project_lsv_col_tafel"))}</th>
          <th>${escapeHtml(t("project_lsv_col_count"))}</th>
          <th>${escapeHtml(t("project_lsv_col_time"))}</th>
        </tr>
      </thead>
      <tbody>
        ${samples
          .slice(0, 15)
          .map((it) => {
            const eta = it.overpotential_10 !== undefined && it.overpotential_10 !== null
              ? `${formatMetric(it.overpotential_10, 3)} mV`
              : it.potential_10 !== undefined && it.potential_10 !== null
                ? `${formatMetric(it.potential_10, 3)} V`
                : "-";
            const tafel = formatMetric(it.tafel_slope, 3);
            const count = it.record_count === undefined || it.record_count === null ? "-" : String(it.record_count);
            const latest = it.latest_time || "-";
            return `
              <tr>
                <td>${escapeHtml(String(it.sample_name || "-"))}</td>
                <td>${escapeHtml(eta)}</td>
                <td>${escapeHtml(tafel)}</td>
                <td>${escapeHtml(count)}</td>
                <td>${escapeHtml(String(latest))}</td>
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

function getFilteredProjectCompareSamples(summary) {
  const payload = summary && typeof summary === "object" ? summary : {};
  let samples = Array.isArray(payload.samples) ? [...payload.samples] : [];
  if (projectCompareOnlyEta) {
    samples = samples.filter((it) => it.overpotential_10 !== undefined && it.overpotential_10 !== null);
  }
  if (projectCompareOnlyTafel) {
    samples = samples.filter((it) => it.tafel_slope !== undefined && it.tafel_slope !== null);
  }
  if (projectCompareSort === "tafel") {
    samples.sort((a, b) => {
      const av = a.tafel_slope ?? Number.POSITIVE_INFINITY;
      const bv = b.tafel_slope ?? Number.POSITIVE_INFINITY;
      return av - bv;
    });
  } else if (projectCompareSort === "latest") {
    samples.sort((a, b) => String(b.latest_time || "").localeCompare(String(a.latest_time || "")));
  } else if (projectCompareSort === "sample") {
    samples.sort((a, b) => String(a.sample_name || "").localeCompare(String(b.sample_name || "")));
  } else {
    samples.sort((a, b) => {
      const aEta = a.overpotential_10;
      const bEta = b.overpotential_10;
      if (aEta !== undefined && aEta !== null && bEta !== undefined && bEta !== null) return aEta - bEta;
      if (aEta !== undefined && aEta !== null) return -1;
      if (bEta !== undefined && bEta !== null) return 1;
      const aPot = a.potential_10 ?? Number.POSITIVE_INFINITY;
      const bPot = b.potential_10 ?? Number.POSITIVE_INFINITY;
      return aPot - bPot;
    });
  }
  return samples;
}

function syncProjectCompareSelection(summary) {
  const samples = getFilteredProjectCompareSamples(summary);
  const visibleNames = samples.map((it) => String(it.sample_name || "").trim()).filter(Boolean);
  if (!visibleNames.length) {
    projectCompareSelectedSamples = [];
    projectComparePlotData = null;
    projectComparePlotLoading = false;
    return samples;
  }
  const visibleSet = new Set(visibleNames);
  const nextSelected = visibleNames.filter((name) => projectCompareSelectedSamples.includes(name));
  if (!nextSelected.length) {
    projectCompareSelectedSamples = visibleNames.slice(0, Math.min(3, visibleNames.length));
    projectComparePlotData = null;
  } else {
    if (nextSelected.length !== projectCompareSelectedSamples.length || projectCompareSelectedSamples.some((name) => !visibleSet.has(name))) {
      projectComparePlotData = null;
    }
    projectCompareSelectedSamples = nextSelected;
  }
  return samples;
}

function renderProjectCompareSelectionCount() {
  const el = byId("project-compare-selected-count");
  if (!el) return;
  const count = projectCompareSelectedSamples.length;
  el.textContent = count
    ? t("project_compare_selected_count").replace("{count}", String(count))
    : t("project_compare_selected_count_empty");
}

function projectCompareNeedsTargetCurrent() {
  return projectCompareChartType === "bar" && projectCompareMetric !== "tafel_slope";
}

function formatProjectCompareTargetCurrentOption(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return "";
  if (Number.isInteger(numeric)) return String(numeric);
  return String(numeric);
}

function getProjectCompareAvailableTargetCurrents(metric = projectCompareMetric) {
  const state = projectCompareTargetCurrents && typeof projectCompareTargetCurrents === "object" ? projectCompareTargetCurrents : {};
  if (metric === "overpotential_at_target") {
    return Array.isArray(state.overpotential_target_currents) ? state.overpotential_target_currents : [];
  }
  if (metric === "potential_at_target") {
    return Array.isArray(state.potential_target_currents) ? state.potential_target_currents : [];
  }
  return Array.isArray(state.target_currents) ? state.target_currents : [];
}

function syncProjectCompareTargetOptions() {
  const targetEl = byId("project-compare-target-current");
  if (!targetEl) return;
  const options = getProjectCompareAvailableTargetCurrents(projectCompareMetric);
  const normalizedOptions = options
    .map((item) => {
      const numeric = Number(item);
      return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
    })
    .filter((item) => item !== null);
  const uniqueOptions = [...new Set(normalizedOptions)];
  const preferred = uniqueOptions.includes(10) ? 10 : uniqueOptions[0];
  const currentValue = Number(projectCompareTargetCurrent);
  const nextValue = uniqueOptions.includes(currentValue) ? currentValue : preferred;
  projectCompareTargetCurrent = nextValue !== undefined ? formatProjectCompareTargetCurrentOption(nextValue) : "";
  if (!uniqueOptions.length) {
    targetEl.innerHTML = `<option value="">${escapeHtml(t("project_compare_target_current_empty"))}</option>`;
    targetEl.value = "";
    return;
  }
  targetEl.innerHTML = uniqueOptions
    .map((item) => {
      const text = formatProjectCompareTargetCurrentOption(item);
      return `<option value="${escapeHtml(text)}">${escapeHtml(text)}</option>`;
    })
    .join("");
  targetEl.value = projectCompareTargetCurrent;
}

function syncProjectCompareControls() {
  const metricEl = byId("project-compare-metric");
  const targetEl = byId("project-compare-target-current");
  const targetWrap = byId("project-compare-target-wrap");
  if (metricEl) {
    metricEl.disabled = projectCompareChartType !== "bar";
  }
  const needsTarget = projectCompareNeedsTargetCurrent();
  syncProjectCompareTargetOptions();
  if (targetEl) {
    targetEl.disabled = !needsTarget || !getProjectCompareAvailableTargetCurrents(projectCompareMetric).length;
  }
  if (targetWrap) {
    targetWrap.style.opacity = needsTarget ? "1" : "0.55";
  }
}

function bindProjectCompareSelection() {
  document.querySelectorAll(".project-compare-sample").forEach((input) => {
    input.addEventListener("change", () => {
      const sampleName = decodeURIComponent(input.getAttribute("data-sample-name") || "");
      if (!sampleName) return;
      if (input.checked) {
        if (!projectCompareSelectedSamples.includes(sampleName)) {
          projectCompareSelectedSamples = [...projectCompareSelectedSamples, sampleName];
        }
      } else {
        projectCompareSelectedSamples = projectCompareSelectedSamples.filter((item) => item !== sampleName);
      }
      projectComparePlotData = null;
      renderProjectCompareSelectionCount();
      renderProjectComparePlot();
    });
  });
}

function renderProjectCompareSummary(summary) {
  const wrap = byId("project-compare-summary");
  if (!wrap) return;
  const samples = getFilteredProjectCompareSamples(summary);
  if (!samples.length) {
    wrap.innerHTML = `<div class="placeholder">${t("project_compare_empty")}</div>`;
    return;
  }
  const bestEta = [...samples]
    .filter((it) => it.overpotential_10 !== undefined && it.overpotential_10 !== null)
    .sort((a, b) => a.overpotential_10 - b.overpotential_10)[0];
  const bestPotential = [...samples]
    .filter((it) => it.potential_10 !== undefined && it.potential_10 !== null)
    .sort((a, b) => a.potential_10 - b.potential_10)[0];
  const bestTafel = [...samples]
    .filter((it) => it.tafel_slope !== undefined && it.tafel_slope !== null)
    .sort((a, b) => a.tafel_slope - b.tafel_slope)[0];
  const missingEta = samples.filter((it) => it.overpotential_10 === undefined || it.overpotential_10 === null).map((it) => it.sample_name || "-");
  const missingTafel = samples.filter((it) => it.tafel_slope === undefined || it.tafel_slope === null).map((it) => it.sample_name || "-");

  const cards = [];
  if (bestEta) {
    cards.push(`<div class="compare-chip"><strong>${escapeHtml(t("project_compare_best_eta"))}</strong><span>${escapeHtml(String(bestEta.sample_name || "-"))} | ${escapeHtml(formatMetric(bestEta.overpotential_10, 3))} mV</span></div>`);
  } else if (bestPotential) {
    cards.push(`<div class="compare-chip"><strong>${escapeHtml(t("project_compare_best_potential"))}</strong><span>${escapeHtml(String(bestPotential.sample_name || "-"))} | ${escapeHtml(formatMetric(bestPotential.potential_10, 3))} V</span></div>`);
  }
  if (bestTafel) {
    cards.push(`<div class="compare-chip"><strong>${escapeHtml(t("project_compare_best_tafel"))}</strong><span>${escapeHtml(String(bestTafel.sample_name || "-"))} | ${escapeHtml(formatMetric(bestTafel.tafel_slope, 3))}</span></div>`);
  }
  if (missingEta.length || missingTafel.length) {
    const missingParts = [];
    if (missingEta.length) missingParts.push(`${t("project_compare_missing_eta")}: ${missingEta.slice(0, 4).join(", ")}`);
    if (missingTafel.length) missingParts.push(`${t("project_compare_missing_tafel")}: ${missingTafel.slice(0, 4).join(", ")}`);
    cards.push(`<div class="compare-chip muted"><strong>${escapeHtml(t("project_compare_missing"))}</strong><span>${escapeHtml(missingParts.join(" | "))}</span></div>`);
  }
  wrap.innerHTML = cards.join("") || `<div class="placeholder">${t("project_compare_empty")}</div>`;
}

function renderProjectCompareTable(summary) {
  const wrap = byId("project-compare-table");
  if (!wrap) return;
  const samples = getFilteredProjectCompareSamples(summary);
  if (!samples.length) {
    wrap.innerHTML = `<div class="placeholder">${t("project_compare_empty")}</div>`;
    renderProjectCompareSelectionCount();
    return;
  }
  wrap.innerHTML = `
    <table class="lsv-summary-table compare-table">
      <thead>
        <tr>
          <th>${escapeHtml(t("project_compare_col_sample"))}</th>
          <th>${escapeHtml(t("project_compare_col_eta"))}</th>
          <th>${escapeHtml(t("project_compare_col_tafel"))}</th>
          <th>${escapeHtml(t("project_compare_col_count"))}</th>
          <th>${escapeHtml(t("project_compare_col_time"))}</th>
        </tr>
      </thead>
      <tbody>
        ${samples
          .map((it) => {
            const sampleName = String(it.sample_name || "-");
            const sampleToken = encodeURIComponent(sampleName);
            const checked = projectCompareSelectedSamples.includes(sampleName) ? "checked" : "";
            const etaText =
              it.overpotential_10 !== undefined && it.overpotential_10 !== null
                ? `${formatMetric(it.overpotential_10, 3)} mV`
                : it.potential_10 !== undefined && it.potential_10 !== null
                  ? `${formatMetric(it.potential_10, 3)} V`
                  : "-";
            const tafelText = it.tafel_slope !== undefined && it.tafel_slope !== null ? formatMetric(it.tafel_slope, 3) : "-";
            return `
              <tr>
                <td>
                  <label class="compare-sample-cell compare-sample-check">
                    <input class="project-compare-sample" type="checkbox" data-sample-name="${sampleToken}" ${checked}>
                    <span>${escapeHtml(sampleName)}</span>
                  </label>
                </td>
                <td>${escapeHtml(etaText)}</td>
                <td>${escapeHtml(tafelText)}</td>
                <td>${escapeHtml(String(it.record_count ?? "-"))}</td>
                <td>${escapeHtml(String(it.latest_time || "-"))}</td>
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
  renderProjectCompareSelectionCount();
  bindProjectCompareSelection();
}

function renderProjectComparePlot() {
  const wrap = byId("project-compare-plot");
  if (!wrap) return;
  syncProjectCompareControls();
  if (projectComparePlotLoading) {
    wrap.innerHTML = `<div class="placeholder">${t("project_compare_plot_loading")}</div>`;
    return;
  }
  if (!projectCompareSelectedSamples.length) {
    wrap.innerHTML = `<div class="placeholder">${t("project_compare_plot_empty")}</div>`;
    return;
  }
  if (!projectComparePlotData || !projectComparePlotData.image_data_url) {
    wrap.innerHTML = `<div class="placeholder">${t("project_compare_plot_empty")}</div>`;
    return;
  }
  const plot = projectComparePlotData;
  const warnings = Array.isArray(plot.warnings) ? plot.warnings.filter((item) => String(item || "").trim()) : [];
  wrap.innerHTML = `
    <div class="project-compare-plot-preview">
      <img alt="${escapeHtml(t("project_compare_plot_title"))}" src="${plot.image_data_url}">
      <div class="project-compare-plot-meta">
        <span>${escapeHtml(t("project_compare_plot_traces"))}: ${escapeHtml(String(plot.trace_count || 0))}</span>
        ${plot.metric_label ? `<span>${escapeHtml(String(plot.metric_label))}</span>` : ""}
        <span>${escapeHtml(t("project_compare_plot_generated_at"))}: ${escapeHtml(String(plot.generated_at || "-"))}</span>
      </div>
      <div class="project-compare-plot-actions">
        <button class="btn mini" type="button" data-copy-path="${escapeHtml(String(plot.plot_path || ""))}">${escapeHtml(t("btn_copy_path"))}</button>
        <button class="btn mini" type="button" data-open-path="${escapeHtml(String(plot.plot_path || ""))}">${escapeHtml(t("btn_open_file"))}</button>
        <button class="btn mini" type="button" data-open-dir="${escapeHtml(String(plot.plot_path || ""))}">${escapeHtml(t("btn_open_dir"))}</button>
      </div>
      ${warnings.length ? `<ul class="project-compare-plot-warnings">${warnings.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>` : ""}
    </div>
  `;
  bindProjectFileActions(wrap);
}

async function generateProjectComparePlot() {
  if (!selectedProjectId) return;
  if (!projectCompareSelectedSamples.length) {
    setProjectStatus(t("project_compare_plot_empty"));
    renderProjectComparePlot();
    return;
  }
  if (projectCompareNeedsTargetCurrent()) {
    const availableTargets = getProjectCompareAvailableTargetCurrents(projectCompareMetric);
    if (!availableTargets.length || !projectCompareTargetCurrent) {
      setProjectStatus(t("project_compare_target_current_missing"));
      renderProjectComparePlot();
      return;
    }
  }
  projectComparePlotLoading = true;
  projectComparePlotData = null;
  renderProjectComparePlot();
  setProjectStatus(t("project_compare_plot_loading"));
  try {
    const params = new URLSearchParams();
    params.set("include_archived", projectIncludeArchived ? "1" : "0");
    params.set("chart_type", projectCompareChartType);
    params.set("metric", projectCompareMetric);
    if (projectCompareNeedsTargetCurrent()) {
      params.set("target_current", projectCompareTargetCurrent);
    }
    projectCompareSelectedSamples.forEach((name) => params.append("sample", name));
    const resp = await fetch(`/api/v1/projects/${encodeURIComponent(selectedProjectId)}/lsv-compare-plot?${params.toString()}`);
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_compare_plot_failed"));
    }
    projectComparePlotData = data.plot || null;
    if (projectComparePlotData && Array.isArray(projectComparePlotData.selected_samples) && projectComparePlotData.selected_samples.length) {
      projectCompareSelectedSamples = projectComparePlotData.selected_samples.map((item) => String(item || "")).filter(Boolean);
      renderProjectCompareSelectionCount();
    }
    if (projectComparePlotData && projectComparePlotData.target_current !== undefined && projectComparePlotData.target_current !== null) {
      projectCompareTargetCurrent = String(projectComparePlotData.target_current);
      syncProjectCompareControls();
    }
    setProjectStatus("");
  } catch (err) {
    projectComparePlotData = null;
    setProjectStatus(`${t("project_compare_plot_failed")}: ${err.message}`);
  } finally {
    projectComparePlotLoading = false;
    renderProjectComparePlot();
  }
}

async function loadLatestProjectComparePlot(silent = true) {
  if (!selectedProjectId) return;
  try {
    const params = new URLSearchParams();
    params.set("chart_type", projectCompareChartType);
    params.set("metric", projectCompareMetric);
    if (projectCompareNeedsTargetCurrent() && projectCompareTargetCurrent) {
      params.set("target_current", projectCompareTargetCurrent);
    }
    const resp = await fetch(`/api/v1/projects/${encodeURIComponent(selectedProjectId)}/lsv-compare-plot/latest?${params.toString()}`);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.status !== "success") {
      projectComparePlotData = null;
      renderProjectComparePlot();
      return;
    }
    projectComparePlotData = data.plot || null;
    if (projectComparePlotData && Array.isArray(projectComparePlotData.selected_samples) && projectComparePlotData.selected_samples.length) {
      projectCompareSelectedSamples = projectComparePlotData.selected_samples.map((item) => String(item || "")).filter(Boolean);
    }
    if (projectComparePlotData && projectComparePlotData.target_current !== undefined && projectComparePlotData.target_current !== null) {
      projectCompareTargetCurrent = String(projectComparePlotData.target_current);
      syncProjectCompareControls();
    }
    renderProjectCompareSelectionCount();
    renderProjectComparePlot();
  } catch (err) {
    projectComparePlotData = null;
    renderProjectComparePlot();
    if (!silent) {
      setProjectStatus(`${t("project_compare_plot_failed")}: ${err.message}`);
    }
  }
}

async function loadProjectCompareTargetCurrents(projectId) {
  const targetProjectId = String(projectId || "").trim();
  if (!targetProjectId) {
    projectCompareTargetCurrents = {
      target_currents: [],
      potential_target_currents: [],
      overpotential_target_currents: [],
    };
    syncProjectCompareControls();
    return;
  }
  try {
    const resp = await fetch(
      `/api/v1/projects/${encodeURIComponent(targetProjectId)}/lsv-target-currents?include_archived=${projectIncludeArchived ? "1" : "0"}`
    );
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || "failed to load target currents");
    }
    projectCompareTargetCurrents = {
      target_currents: Array.isArray(data.target_currents) ? data.target_currents : [],
      potential_target_currents: Array.isArray(data.potential_target_currents) ? data.potential_target_currents : [],
      overpotential_target_currents: Array.isArray(data.overpotential_target_currents) ? data.overpotential_target_currents : [],
    };
  } catch (_err) {
    projectCompareTargetCurrents = {
      target_currents: [],
      potential_target_currents: [],
      overpotential_target_currents: [],
    };
  }
  syncProjectCompareControls();
}

function collectProjectOutputFiles(history) {
  const groups = [];
  const seenGroup = new Map();
  (Array.isArray(history) ? history : []).forEach((record) => {
    const groupKey = String(record.run_id || historyRecordKey(record));
    let group = seenGroup.get(groupKey);
    if (!group) {
      group = {
        key: groupKey,
        title: record.timestamp || groupKey,
        sub: `${record.type || "-"} | ${record.sample_name || record.file_name || "-"}`,
        type: String(record.type || "").toUpperCase(),
        files: [],
      };
      seenGroup.set(groupKey, group);
      groups.push(group);
    }
    if (Array.isArray(record.output_files)) {
      record.output_files.forEach((item) => {
        const text = String(item || "").trim();
        if (text && !group.files.includes(text)) group.files.push(text);
      });
    }
    if (record.summary_path) {
      const text = String(record.summary_path || "").trim();
      if (text && !group.files.includes(text)) group.files.push(text);
    }
  });
  return groups.filter((group) => group.files.length > 0);
}

async function copyTextToClipboard(text) {
  const value = String(text || "").trim();
  if (!value) return false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (_err) {}
  try {
    const el = document.createElement("textarea");
    el.value = value;
    el.setAttribute("readonly", "readonly");
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    el.remove();
    return true;
  } catch (_err) {
    return false;
  }
}

async function requestOpenPath(pathValue, revealOnly = false) {
  const target = String(pathValue || "").trim();
  if (!target) return;
  try {
    const resp = await fetch("/api/v1/system/open-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: target, reveal_only: revealOnly }),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_open_dir_failed"));
    }
    setFileActionStatus(t("project_open_dir_done"));
  } catch (err) {
    setFileActionStatus(`${t("project_open_dir_failed")}: ${err.message}`);
  }
}

function bindProjectFileActions(root) {
  if (!root) return;
  root.querySelectorAll("[data-copy-path]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const ok = await copyTextToClipboard(btn.getAttribute("data-copy-path") || "");
      setFileActionStatus(ok ? t("project_copy_done") : t("project_copy_failed"));
    });
  });
  root.querySelectorAll("[data-open-path]").forEach((btn) => {
    btn.addEventListener("click", () => {
      requestOpenPath(btn.getAttribute("data-open-path") || "", false);
    });
  });
  root.querySelectorAll("[data-open-dir]").forEach((btn) => {
    btn.addEventListener("click", () => {
      requestOpenPath(btn.getAttribute("data-open-dir") || "", true);
    });
  });
}

function renderProjectOutputFiles(history) {
  const wrap = byId("project-output-files");
  if (!wrap) return;
  const groups = collectProjectOutputFiles(history).filter((group) => {
    if (!projectOutputTypeFilter) return true;
    return String(group.type || "").toUpperCase() === projectOutputTypeFilter;
  });
  if (!groups.length) {
    wrap.innerHTML = `<div class="placeholder">${t("project_no_output_files")}</div>`;
    return;
  }
  wrap.innerHTML = groups
    .map((group, index) => {
      const title = group.key.startsWith("proj_") || group.key.includes("|")
        ? `${t("project_output_group_prefix")} ${index + 1}`
        : `${t("project_output_group_prefix")} ${index + 1}`;
      return `
        <div class="output-group">
          <div class="output-group-head">
            <div class="name">${escapeHtml(title)}</div>
            <div class="meta">${escapeHtml(String(group.title || "-"))} | ${escapeHtml(String(group.sub || "-"))}</div>
          </div>
          <div class="output-group-files">
            ${group.files
              .map((filePath) => {
                const pathText = String(filePath || "");
                const parts = pathText.split(/[/\\]/);
                const name = parts.length ? parts[parts.length - 1] : pathText;
                return `
                  <div class="output-file-item">
                    <div class="name">${escapeHtml(name || pathText)}</div>
                    <div class="path">${escapeHtml(pathText)}</div>
                    <div class="file-actions">
                      <button class="btn mini" type="button" data-copy-path="${escapeHtml(pathText)}">${escapeHtml(t("btn_copy_path"))}</button>
                      <button class="btn mini" type="button" data-open-path="${escapeHtml(pathText)}">${escapeHtml(t("btn_open_file"))}</button>
                      <button class="btn mini" type="button" data-open-dir="${escapeHtml(pathText)}">${escapeHtml(t("btn_open_dir"))}</button>
                    </div>
                  </div>
                `;
              })
              .join("")}
          </div>
        </div>
      `;
    })
    .join("");
  bindProjectFileActions(wrap);
}

function renderSelectedProjectDetail() {
  const titleEl = byId("project-detail-title");
  const metaEl = byId("project-detail-meta");
  const useBtn = byId("project-use-btn");
  const delBtn = byId("project-delete-btn");
  const exportBtn = byId("project-export-report-btn");
  const project = projectItems.find((it) => it.id === selectedProjectId);

  if (!project) {
    if (titleEl) titleEl.textContent = t("project_none");
    if (metaEl) metaEl.textContent = t("project_pick_hint");
    if (useBtn) useBtn.disabled = true;
    if (delBtn) delBtn.disabled = true;
    if (exportBtn) exportBtn.disabled = true;
    selectedProjectHistoryKey = "";
    projectCompareSelectedSamples = [];
    projectComparePlotData = null;
    projectComparePlotLoading = false;
    projectCompareTargetCurrents = {
      target_currents: [],
      potential_target_currents: [],
      overpotential_target_currents: [],
    };
    setProjectEditForm(null);
    renderProjectStats({});
    renderProjectHistory([]);
    renderProjectLSVSummary(null);
    renderProjectCompareSummary(null);
    renderProjectCompareTable(null);
    renderProjectCompareSelectionCount();
    renderProjectComparePlot();
    renderProjectOutputFiles([]);
    return;
  }

  if (useBtn) useBtn.disabled = false;
  if (delBtn) delBtn.disabled = false;
  if (exportBtn) exportBtn.disabled = false;
  setProjectEditForm(project);
  if (titleEl) titleEl.textContent = String(project.name || t("project_none"));
  if (metaEl) {
    const parts = [
      `${t("project_label_created")}: ${project.created_at || "-"}`,
      `${t("project_label_updated")}: ${project.updated_at || "-"}`,
      `${t("project_label_files")}: ${project.file_count ?? 0}`,
    ];
    const desc = String(project.description || "").trim();
    if (desc) parts.push(`${t("project_label_desc")}: ${desc}`);
    metaEl.textContent = parts.join(" | ");
  }

  const state = projectDetailState && typeof projectDetailState === "object" ? projectDetailState : {};
  syncProjectCompareSelection(state.lsv || null);
  renderProjectStats(state.stats || {});
  renderProjectHistory(state.history || []);
  renderProjectLSVSummary(state.lsv || null);
  renderProjectCompareSummary(state.lsv || null);
  renderProjectCompareTable(state.lsv || null);
  renderProjectComparePlot();
  renderProjectOutputFiles(state.history || []);
}

function renderProjectList(items) {
  const listEl = byId("project-list");
  if (!listEl) return;
  if (!Array.isArray(items) || !items.length) {
    listEl.innerHTML = `<div class="placeholder">${t("project_empty")}</div>`;
    return;
  }
  listEl.innerHTML = items
    .map((it) => {
      const active = it.id === selectedProjectId ? "active" : "";
      const rawColor = typeof it.color === "string" ? it.color.trim() : "";
      const color = /^#[0-9a-fA-F]{3,8}$/.test(rawColor) ? rawColor : "#155e45";
      const tags = Array.isArray(it.tags) ? it.tags.filter((x) => String(x || "").trim()).slice(0, 3) : [];
      const tagsHtml = tags.length
        ? `<div class="project-tags">${tags.map((tag) => `<span>${escapeHtml(String(tag))}</span>`).join("")}</div>`
        : "";
      return `
        <div class="project-item ${active}" data-project-id="${String(it.id || "")}">
          <div class="name"><span class="project-dot" style="background:${escapeHtml(color)}"></span>${escapeHtml(
            String(it.name || "-")
          )}</div>
          <div class="meta">${escapeHtml(t("project_label_updated"))}: ${escapeHtml(
            String(it.updated_at || "-")
          )} | ${escapeHtml(t("project_label_files"))}: ${escapeHtml(String(it.file_count ?? 0))}</div>
          ${tagsHtml}
        </div>
      `;
    })
    .join("");
  listEl.querySelectorAll(".project-item").forEach((el) => {
    el.addEventListener("click", () => {
      selectProject(el.getAttribute("data-project-id") || "");
    });
  });
}

async function loadSelectedProjectDetail() {
  if (!selectedProjectId) return;
  const projectId = selectedProjectId;
  projectComparePlotData = null;
  projectComparePlotLoading = false;
  setProjectStatus(t("project_status_detail_loading"));
  try {
    const [statsResp, historyResp, lsvResp] = await Promise.all([
      fetch(`/api/v1/stats?project=${encodeURIComponent(projectId)}&include_archived=${projectIncludeArchived ? "1" : "0"}`),
      fetch(`/api/v1/history?project=${encodeURIComponent(projectId)}&limit=30&include_archived=${projectIncludeArchived ? "1" : "0"}`),
      fetch(`/api/v1/projects/${encodeURIComponent(projectId)}/lsv-summary?page=1&page_size=15&sort=eta`),
    ]);
    const [statsData, historyData, lsvData] = await Promise.all([
      statsResp.json().catch(() => ({})),
      historyResp.json().catch(() => ({})),
      lsvResp.json().catch(() => ({})),
    ]);
    if (projectId !== selectedProjectId) return;
    projectDetailState = {
      stats: statsResp.ok && statsData.status === "success" ? statsData.data || {} : {},
      history: historyResp.ok && historyData.status === "success" ? historyData.records || [] : [],
      lsv: lsvResp.ok && lsvData.status === "success" ? lsvData.lsv_summary || {} : null,
    };
    await loadProjectCompareTargetCurrents(projectId);
    renderSelectedProjectDetail();
    await loadLatestProjectComparePlot(true);
    setProjectStatus("");
  } catch (err) {
    if (projectId !== selectedProjectId) return;
    projectCompareTargetCurrents = {
      target_currents: [],
      potential_target_currents: [],
      overpotential_target_currents: [],
    };
    projectDetailState = { stats: {}, history: [], lsv: null };
    renderSelectedProjectDetail();
    setProjectStatus(`${t("project_status_detail_failed")}: ${err.message}`);
  }
}

async function selectProject(projectId) {
  const targetId = String(projectId || "").trim();
  selectedProjectId = targetId;
  projectDetailState = null;
  selectedProjectHistoryKey = "";
  projectCompareSelectedSamples = [];
  projectComparePlotData = null;
  projectComparePlotLoading = false;
  projectCompareTargetCurrents = {
    target_currents: [],
    potential_target_currents: [],
    overpotential_target_currents: [],
  };
  renderProjectList(projectItems);
  renderSelectedProjectDetail();
  if (!targetId) return;
  await loadSelectedProjectDetail();
}

async function loadProjects(preferredProjectId = "") {
  setProjectStatus(t("project_status_loading"));
  try {
    const resp = await fetch("/api/v1/projects?status=active");
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_status_load_failed"));
    }
    projectItems = Array.isArray(data.projects) ? data.projects : [];
    syncProcessProjectOptions();
    renderProjectList(projectItems);
    if (!projectItems.length) {
      selectedProjectId = "";
      projectDetailState = null;
      renderSelectedProjectDetail();
      setProjectStatus("");
      return;
    }
    const preferred = String(preferredProjectId || selectedProjectId || "").trim();
    const picked =
      preferred && projectItems.some((it) => it.id === preferred) ? preferred : String(projectItems[0].id || "");
    await selectProject(picked);
  } catch (err) {
    projectItems = [];
    selectedProjectId = "";
    projectDetailState = null;
    syncProcessProjectOptions();
    renderProjectList([]);
    renderSelectedProjectDetail();
    setProjectStatus(`${t("project_status_load_failed")}: ${err.message}`);
  }
}

async function createProject() {
  const name = textValue("project-create-name");
  if (!name) {
    setProjectStatus(t("project_name_required"));
    return;
  }
  setProjectStatus(t("project_status_create_running"));
  try {
    const resp = await fetch("/api/v1/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description: "Created from ElectroChem v6 UI" }),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_status_create_failed"));
    }
    byId("project-create-name").value = "";
    const projectId = String(data.project_id || (data.project && data.project.id) || "");
    await loadProjects(projectId);
    setProjectStatus(t("project_status_create_success"));
  } catch (err) {
    setProjectStatus(`${t("project_status_create_failed")}: ${err.message}`);
  }
}

async function deleteCurrentProject() {
  if (!selectedProjectId) return;
  if (!window.confirm(t("project_confirm_delete"))) return;
  setProjectStatus(t("project_status_delete_running"));
  try {
    const resp = await fetch(`/api/v1/projects/${encodeURIComponent(selectedProjectId)}/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_status_delete_failed"));
    }
    selectedProjectId = "";
    projectDetailState = null;
    await loadProjects("");
    setProjectStatus(t("project_status_delete_success"));
  } catch (err) {
    setProjectStatus(`${t("project_status_delete_failed")}: ${err.message}`);
  }
}

function applyCurrentProjectToForms() {
  const project = projectItems.find((it) => it.id === selectedProjectId);
  if (!project || !project.name) return;
  const name = String(project.name);
  if (byId("proc-project")) byId("proc-project").value = name;
  if (byId("project-name")) byId("project-name").value = name;
  setProjectStatus(t("project_status_applied"));
}

async function saveCurrentProject() {
  if (!selectedProjectId) return;
  const name = textValue("project-edit-name");
  const description = textValue("project-edit-desc");
  const color = textValue("project-edit-color");
  const tags = textValue("project-edit-tags")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (!name) {
    setProjectStatus(t("project_name_required"));
    return;
  }
  if (color && !/^#[0-9a-fA-F]{3,8}$/.test(color)) {
    setProjectStatus(t("project_color_invalid"));
    return;
  }
  setProjectStatus(t("project_status_save_running"));
  try {
    const resp = await fetch(`/api/v1/projects/${encodeURIComponent(selectedProjectId)}/update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description, tags, color: color || undefined }),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_status_save_failed"));
    }
    await loadProjects(selectedProjectId);
    const active = projectItems.find((it) => it.id === selectedProjectId);
    if (active && active.name) {
      if (byId("proc-project")) byId("proc-project").value = active.name;
      if (byId("project-name")) byId("project-name").value = active.name;
    }
    setProjectStatus(t("project_status_save_success"));
  } catch (err) {
    setProjectStatus(`${t("project_status_save_failed")}: ${err.message}`);
  }
}

function openSelectedProjectHistoryResult() {
  const record = getSelectedProjectHistoryRecord();
  if (!record) {
    setProjectStatus(t("project_open_result_empty"));
    return;
  }
  renderProcessResult(buildResultFromHistoryRecord(record));
  setProcStatus(t("status_history_loaded"));
  switchTab("pro");
  setProjectStatus(t("project_open_result_done"));
}

async function archiveSelectedProjectHistory() {
  const record = getSelectedProjectHistoryRecord();
  if (!record) {
    setProjectStatus(t("project_open_result_empty"));
    return;
  }
  if (!window.confirm(t("project_history_confirm_archive"))) return;
  setProjectStatus(t("project_history_archive_running"));
  try {
    const resp = await fetch("/api/v1/history/archive", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ history_key: historyRecordKey(record) }),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_history_archive_failed"));
    }
    selectedProjectHistoryKey = "";
    await loadSelectedProjectDetail();
    await loadStatsAndHistory();
    setProjectStatus(t("project_history_archive_success"));
  } catch (err) {
    setProjectStatus(`${t("project_history_archive_failed")}: ${err.message}`);
  }
}

async function deleteSelectedProjectHistory() {
  const record = getSelectedProjectHistoryRecord();
  if (!record) {
    setProjectStatus(t("project_open_result_empty"));
    return;
  }
  if (!window.confirm(t("project_history_confirm_delete"))) return;
  setProjectStatus(t("project_history_delete_running"));
  try {
    const resp = await fetch("/api/v1/history/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ history_key: historyRecordKey(record) }),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_history_delete_failed"));
    }
    selectedProjectHistoryKey = "";
    await loadSelectedProjectDetail();
    await loadStatsAndHistory();
    setProjectStatus(t("project_history_delete_success"));
  } catch (err) {
    setProjectStatus(`${t("project_history_delete_failed")}: ${err.message}`);
  }
}

async function exportCurrentProjectReport() {
  if (!selectedProjectId) return;
  setProjectStatus(t("project_status_detail_loading"));
  try {
    const resp = await fetch(
      `/api/v1/projects/${encodeURIComponent(selectedProjectId)}/report?include_archived=${projectIncludeArchived ? "1" : "0"}`
    );
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("project_export_report_failed"));
    }
    setProjectStatus(`${t("project_export_report_success")}: ${data.path || data.file_name || ""}`);
  } catch (err) {
    setProjectStatus(`${t("project_export_report_failed")}: ${err.message}`);
  }
}

async function loadStatsAndHistory() {
  try {
    const [statsResp, historyResp] = await Promise.all([
      fetch("/api/v1/stats"),
      fetch("/api/v1/history?limit=50"),
    ]);
    const statsData = await statsResp.json();
    const historyData = await historyResp.json();

    if (statsResp.ok && statsData.status === "success") {
      renderStats(statsData.data || {});
    }
    if (historyResp.ok && historyData.status === "success") {
      renderHistory(historyData.records || []);
    }
  } catch (_err) {
    // silent refresh errors
  }
}

function getSelectedProcessTypes() {
  return Array.from(document.querySelectorAll(".proc-type-check:checked")).map((el) =>
    String(el.value || "").toUpperCase()
  );
}

function toggleDataTypePanels() {
  const selected = new Set(getSelectedProcessTypes());
  document.querySelectorAll(".dtype-panel").forEach((panel) => {
    panel.classList.toggle("hidden", !selected.has(panel.dataset.dtype));
  });
  syncFeatureBlocks();
}

function syncFeatureBlocks() {
  document.querySelectorAll(".feature-body[data-feature-toggle]").forEach((body) => {
    const toggleId = body.getAttribute("data-feature-toggle");
    const toggle = byId(toggleId);
    const enabled = Boolean(toggle && toggle.checked);
    body.classList.toggle("hidden", !enabled);
    const featureBlock = body.closest(".feature-block");
    if (featureBlock) {
      featureBlock.classList.toggle("inactive", !enabled);
    }
    body.querySelectorAll("input, select, textarea").forEach((el) => {
      el.disabled = !enabled;
    });
  });
}

async function pickFolder() {
  const initial = textValue("proc-folder") || undefined;
  setProcStatus(t("proc_pick_opening"));
  try {
    const resp = await fetch("/api/v1/system/select-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_dir: initial }),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("proc_pick_failed"));
    }
    byId("proc-folder").value = data.folder_path || "";
    setProcStatus(t("proc_pick_success"));
  } catch (err) {
    setProcStatus(`${t("proc_pick_failed")}: ${err.message}`);
  }
}

function collectProcessPayload() {
  const folder = textValue("proc-folder");
  if (!folder) {
    throw new Error(t("proc_folder_required"));
  }

  const dataTypes = getSelectedProcessTypes();
  if (!dataTypes.length) {
    throw new Error(t("proc_type_required"));
  }
  const validationErrors = collectProcessValidationErrors(dataTypes);
  if (validationErrors.length) {
    throw new Error(`${t("proc_param_invalid")}: ${validationErrors[0]}`);
  }

  const payload = {
    folder_path: folder,
    data_type: dataTypes[0],
    data_types: dataTypes,
  };

  const projectName = textValue("proc-project");
  if (projectName) payload.project_name = projectName;

  const params = {
    auto_detect_start: boolValue("pro-auto-detect"),
    plot_grid: boolValue("pro-plot-grid"),
    use_abs_current: boolValue("pro-use-abs-current"),
  };
  const potentialMode = getPotentialMode();
  params.potential_mode = potentialMode;
  addIfSet(params, "font_family", textValue("plot-font-family"));
  addIfSet(params, "font_size", numberValue("plot-font-size"));
  addIfSet(params, "area", numberValue("pro-area"));
  if (potentialMode === "formula_rhe") {
    addIfSet(params, "rhe_ph", numberValue("pro-rhe-ph"));
    addIfSet(params, "reference_electrode_preset", textValue("pro-ref-preset"));
    addIfSet(params, "reference_electrode_potential", getReferenceElectrodePotential());
  } else {
    addIfSet(params, "potential_offset", numberValue("pro-offset"));
  }

  if (dataTypes.includes("LSV")) {
    const target = textValue("pro-lsv-target");
    const tafel = textValue("pro-lsv-tafel");

    addIfSet(payload, "target_current", target);
    addIfSet(payload, "tafel_range", tafel);

    addIfSet(params, "lsv_target_current", target);
    addIfSet(params, "tafel_range", tafel);
    addIfSet(params, "lsv_match", textValue("pro-lsv-match") || "prefix");
    addIfSet(params, "lsv_prefix", textValue("pro-lsv-prefix") || "LSV");
    addIfSet(params, "lsv_title", textValue("pro-lsv-title"));
    addIfSet(params, "lsv_xlabel", textValue("pro-lsv-xlabel"));
    addIfSet(params, "lsv_ylabel", textValue("pro-lsv-ylabel"));
    addIfSet(params, "lsv_line_width", numberValue("pro-lsv-line-width"));
    params.tafel_enabled = boolValue("pro-lsv-tafel-enabled");
    params.lsv_mark_targets = boolValue("pro-lsv-mark-targets");
    params.lsv_export_data = boolValue("pro-lsv-export-data");
    params.lsv_combine_all = boolValue("pro-lsv-combine-all");
    params.export_tafel_plot = boolValue("pro-lsv-export-tafel");
    params.lsv_quality_check = boolValue("pro-lsv-quality-check");
    if (params.lsv_quality_check) {
      addIfSet(params, "lsv_quality_min_points_issue", numberValue("pro-lsv-quality-min-points-issue"));
      addIfSet(params, "lsv_quality_min_points_warning", numberValue("pro-lsv-quality-min-points-warning"));
      addIfSet(params, "lsv_quality_outlier_warning_pct", numberValue("pro-lsv-quality-outlier-warning-pct"));
      addIfSet(params, "lsv_quality_min_potential_span", numberValue("pro-lsv-quality-min-potential-span"));
      addIfSet(params, "lsv_quality_noise_warning", numberValue("pro-lsv-quality-noise-warning"));
      addIfSet(params, "lsv_quality_noise_critical", numberValue("pro-lsv-quality-noise-critical"));
      addIfSet(params, "lsv_quality_jump_warning", numberValue("pro-lsv-quality-jump-warning"));
      addIfSet(params, "lsv_quality_jump_critical", numberValue("pro-lsv-quality-jump-critical"));
      addIfSet(params, "lsv_quality_local_variation_factor", numberValue("pro-lsv-quality-local-factor"));
    }

    const overpotentialEnabled = boolValue("pro-lsv-overpotential-enabled");
    params.overpotential_enabled = overpotentialEnabled;
    if (overpotentialEnabled) {
      addIfSet(params, "eq_potential", numberValue("pro-lsv-eq-potential"));
    }

    const irEnabled = boolValue("pro-lsv-ir-enabled");
    params.ir_compensation_enabled = irEnabled;
    if (irEnabled) {
      addIfSet(params, "ir_method", textValue("pro-lsv-ir-method") || "auto");
      addIfSet(params, "ir_manual_ohm", numberValue("pro-lsv-ir-manual"));
      addIfSet(params, "ir_linear_points", numberValue("pro-lsv-ir-points"));
    }

    const onsetEnabled = boolValue("pro-lsv-onset-enabled");
    params.onset_enabled = onsetEnabled;
    if (onsetEnabled) {
      addIfSet(params, "onset_current", textValue("pro-lsv-onset-current"));
    }

    const halfwaveEnabled = boolValue("pro-lsv-halfwave-enabled");
    params.halfwave_enabled = halfwaveEnabled;
    if (halfwaveEnabled) {
      addIfSet(params, "halfwave_current", textValue("pro-lsv-halfwave-current"));
    }
  }

  if (dataTypes.includes("CV")) {
    addIfSet(params, "cv_match", textValue("pro-cv-match") || "prefix");
    addIfSet(params, "cv_prefix", textValue("pro-cv-prefix") || "CV");
    addIfSet(params, "cv_title", textValue("pro-cv-title"));
    addIfSet(params, "cv_xlabel", textValue("pro-cv-xlabel"));
    addIfSet(params, "cv_ylabel", textValue("pro-cv-ylabel"));
    addIfSet(params, "cv_line_width", numberValue("pro-cv-line-width"));
    params.cv_quality_check = boolValue("pro-cv-quality-check");
    const cvPeaksEnabled = boolValue("pro-cv-peaks-enabled");
    params.cv_peaks_enabled = cvPeaksEnabled;
    if (cvPeaksEnabled) {
      addIfSet(params, "cv_peaks_smooth", numberValue("pro-cv-peaks-smooth"));
      addIfSet(params, "cv_peaks_min_height", numberValue("pro-cv-peaks-height"));
      addIfSet(params, "cv_peaks_min_dist", numberValue("pro-cv-peaks-dist"));
      addIfSet(params, "cv_peaks_max", numberValue("pro-cv-peaks-max"));
    }
    if (params.cv_quality_check) {
      addIfSet(params, "cv_quality_min_points_warning", numberValue("pro-cv-quality-min-points-warning"));
      addIfSet(params, "cv_quality_cycle_tolerance", numberValue("pro-cv-quality-cycle-tolerance"));
    }
  }

  if (dataTypes.includes("EIS")) {
    addIfSet(params, "eis_match", textValue("pro-eis-match") || "prefix");
    addIfSet(params, "eis_prefix", textValue("pro-eis-prefix") || "EIS");
    addIfSet(params, "eis_title", textValue("pro-eis-title"));
    addIfSet(params, "eis_xlabel", textValue("pro-eis-xlabel"));
    addIfSet(params, "eis_ylabel", textValue("pro-eis-ylabel"));
    addIfSet(params, "eis_line_width", numberValue("pro-eis-line-width"));
    params.plot_nyquist = boolValue("pro-eis-plot-nyquist");
    params.plot_bode = boolValue("pro-eis-plot-bode");
  }

  if (dataTypes.includes("ECSA")) {
    addIfSet(params, "ecsa_match", textValue("pro-ecsa-match") || "prefix");
    addIfSet(params, "ecsa_prefix", textValue("pro-ecsa-prefix") || "ECSA");
    addIfSet(params, "ecsa_title", textValue("pro-ecsa-title"));
    addIfSet(params, "ecsa_xlabel", textValue("pro-ecsa-xlabel"));
    addIfSet(params, "ecsa_ylabel", textValue("pro-ecsa-ylabel"));
    addIfSet(params, "ecsa_line_width", numberValue("pro-ecsa-line-width"));
    addIfSet(params, "ecsa_ev", numberValue("pro-ecsa-ev"));
    addIfSet(params, "ecsa_last_n", numberValue("pro-ecsa-last-n"));
    params.ecsa_avg_last_n = boolValue("pro-ecsa-avg-last-n");
    addIfSet(params, "ecsa_cs_value", numberValue("pro-ecsa-cs-value"));
    addIfSet(params, "ecsa_cs_unit", textValue("pro-ecsa-cs-unit") || "uF/cm2");
    params.ecsa_use_abs_delta = boolValue("pro-ecsa-use-abs");
  }

  payload.params = params;
  return payload;
}

async function runProcess() {
  let payload;
  try {
    payload = collectProcessPayload();
  } catch (err) {
    setProcStatus(err.message);
    renderProcessError(err.message);
    return;
  }

  setProcStatus(t("proc_running"));
  try {
    const resp = await fetch("/api/v1/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok || data.status !== "success") {
      throw new Error(data.message || t("proc_failed"));
    }
    const result = data.result || {};
    const files = ((result.processing || {}).output_files || []).slice(0, 5);
    const summary = result.summary || "Done";
    setProcStatus(`${t("proc_success")}: ${summary}${files.length ? ` | output: ${files.join(", ")}` : ""}`);
    renderProcessResult(result);
    await loadStatsAndHistory();
    await loadProjects(selectedProjectId);
  } catch (err) {
    setProcStatus(`${t("proc_failed")}: ${err.message}`);
    renderProcessError(err.message);
  }
}

function bindEvents() {
  byId("tab-btn-pro").addEventListener("click", () => switchTab("pro"));
  byId("tab-btn-ai").addEventListener("click", () => switchTab("ai"));
  byId("tab-btn-project").addEventListener("click", () => switchTab("project"));
  byId("help-docs-btn").addEventListener("click", openHelpPanel);
  byId("help-panel-close").addEventListener("click", closeHelpPanel);
  byId("help-panel-mask").addEventListener("click", closeHelpPanel);
  byId("help-doc-toc-items").addEventListener("click", (e) => {
    const btn = e.target.closest(".help-toc-link");
    if (!btn) return;
    jumpToHelpHeading(btn.dataset.target || "");
  });
  byId("help-doc-scroll").addEventListener("scroll", refreshHelpTocActive);
  byId("sys-status-btn").addEventListener("click", openSystemPanel);
  byId("sys-panel-close").addEventListener("click", closeSystemPanel);
  byId("sys-panel-mask").addEventListener("click", closeSystemPanel);
  byId("sys-panel-refresh").addEventListener("click", fetchHealth);
  byId("ai-settings-open").addEventListener("click", openAISettingsPanel);
  byId("ai-settings-close").addEventListener("click", closeAISettingsPanel);
  byId("ai-settings-mask").addEventListener("click", closeAISettingsPanel);

  byId("lang-select").addEventListener("change", (e) => {
    currentLang = e.target.value || "zh";
    localStorage.setItem("electrochem_v6_lang", currentLang);
    applyI18n();
    fetchHealth();
    if (currentConversationId) {
      openConversation(currentConversationId, true);
    } else {
      renderMessages([]);
      byId("conv-title").textContent = t("conv_none");
      byId("conv-meta").textContent = t("conv_auto_create");
    }
    loadConversations();
    loadStatsAndHistory();
    loadProjects(selectedProjectId);
    renderTemplateOptions();
    updateLLMKeyHint(textValue("llm-provider"));
    if (!hasProcessResult) {
      renderResultPlaceholder();
    }
  });
  byId("conv-refresh").addEventListener("click", loadConversations);
  byId("conv-search-btn").addEventListener("click", applyConversationFilter);
  byId("conv-search-clear").addEventListener("click", clearConversationFilter);
  byId("conv-search").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      applyConversationFilter();
    }
  });
  byId("history-refresh").addEventListener("click", loadStatsAndHistory);
  byId("project-refresh").addEventListener("click", () => loadProjects(selectedProjectId));
  byId("project-include-archived").addEventListener("change", (e) => {
    projectIncludeArchived = Boolean(e.target.checked);
    loadSelectedProjectDetail();
  });
  byId("project-output-type-filter").addEventListener("change", (e) => {
    projectOutputTypeFilter = String(e.target.value || "").toUpperCase();
    renderSelectedProjectDetail();
  });
  byId("project-compare-sort").addEventListener("change", (e) => {
    projectCompareSort = String(e.target.value || "eta");
    renderSelectedProjectDetail();
  });
  byId("project-compare-only-eta").addEventListener("change", (e) => {
    projectCompareOnlyEta = Boolean(e.target.checked);
    renderSelectedProjectDetail();
  });
  byId("project-compare-only-tafel").addEventListener("change", (e) => {
    projectCompareOnlyTafel = Boolean(e.target.checked);
    renderSelectedProjectDetail();
  });
  byId("project-compare-chart-type").addEventListener("change", (e) => {
    projectCompareChartType = String(e.target.value || "overlay");
    projectComparePlotData = null;
    syncProjectCompareControls();
    renderProjectComparePlot();
    loadLatestProjectComparePlot(true);
  });
  byId("project-compare-metric").addEventListener("change", (e) => {
    projectCompareMetric = String(e.target.value || "potential_at_target");
    projectComparePlotData = null;
    syncProjectCompareControls();
    renderProjectComparePlot();
    loadLatestProjectComparePlot(true);
  });
  byId("project-compare-target-current").addEventListener("change", (e) => {
    projectCompareTargetCurrent = String(e.target.value || "10").trim() || "10";
    projectComparePlotData = null;
    renderProjectComparePlot();
    loadLatestProjectComparePlot(true);
  });
  byId("project-compare-select-all-btn").addEventListener("click", () => {
    const summary = projectDetailState && projectDetailState.lsv ? projectDetailState.lsv : null;
    const samples = getFilteredProjectCompareSamples(summary).map((it) => String(it.sample_name || "").trim()).filter(Boolean);
    projectCompareSelectedSamples = samples;
    projectComparePlotData = null;
    renderProjectCompareTable(summary);
    renderProjectComparePlot();
  });
  byId("project-compare-clear-btn").addEventListener("click", () => {
    projectCompareSelectedSamples = [];
    projectComparePlotData = null;
    renderProjectCompareSelectionCount();
    renderProjectCompareTable(projectDetailState && projectDetailState.lsv ? projectDetailState.lsv : null);
    renderProjectComparePlot();
  });
  byId("project-compare-generate-btn").addEventListener("click", generateProjectComparePlot);
  byId("project-create-btn").addEventListener("click", createProject);
  byId("project-export-report-btn").addEventListener("click", exportCurrentProjectReport);
  byId("project-use-btn").addEventListener("click", applyCurrentProjectToForms);
  byId("project-save-btn").addEventListener("click", saveCurrentProject);
  byId("project-delete-btn").addEventListener("click", deleteCurrentProject);
  byId("project-open-result-btn").addEventListener("click", openSelectedProjectHistoryResult);
  byId("project-archive-history-btn").addEventListener("click", archiveSelectedProjectHistory);
  byId("project-delete-history-btn").addEventListener("click", deleteSelectedProjectHistory);
  byId("project-create-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      createProject();
    }
  });
  byId("project-edit-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      saveCurrentProject();
    }
  });
  byId("llm-reload").addEventListener("click", loadLLMConfig);
  byId("llm-save").addEventListener("click", saveLLMConfig);
  byId("prompt-apply-template").addEventListener("click", applyPromptTemplate);
  byId("prompt-save").addEventListener("click", savePromptSettings);
  byId("llm-provider").addEventListener("change", () => {
    applyLLMProviderPreset(textValue("llm-provider"));
  });

  byId("conv-new").addEventListener("click", () => {
    currentConversationId = null;
    byId("conv-title").textContent = t("conv_new");
    byId("conv-meta").textContent = t("conv_new_hint");
    renderMessages([]);
    setSendStatus(t("conv_new"));
  });

  byId("send-btn").addEventListener("click", sendMessage);
  byId("proc-run").addEventListener("click", runProcess);
  byId("proc-folder-pick").addEventListener("click", pickFolder);
  byId("tmpl-load").addEventListener("click", loadSelectedTemplate);
  byId("tmpl-save").addEventListener("click", () => {
    saveTemplate(false);
  });
  byId("tmpl-delete").addEventListener("click", deleteSelectedTemplate);

  document.querySelectorAll(".proc-type-check").forEach((el) => {
    el.addEventListener("change", () => {
      toggleDataTypePanels();
    });
  });

  document.querySelectorAll(".feature-body[data-feature-toggle]").forEach((body) => {
    const toggleId = body.getAttribute("data-feature-toggle");
    const toggle = byId(toggleId);
    if (toggle) {
      toggle.addEventListener("change", syncFeatureBlocks);
    }
  });

  const potentialModeEl = byId("pro-potential-mode");
  if (potentialModeEl) {
    potentialModeEl.addEventListener("change", syncPotentialConversionUI);
  }
  const refPresetEl = byId("pro-ref-preset");
  if (refPresetEl) {
    refPresetEl.addEventListener("change", syncPotentialConversionUI);
  }
  ["pro-offset", "pro-rhe-ph", "pro-ref-custom"].forEach((id) => {
    const el = byId(id);
    if (el) el.addEventListener("input", renderPotentialOffsetPreview);
  });
  [
    ["lsv", "LSV"],
    ["cv", "CV"],
    ["eis", "EIS"],
    ["ecsa", "ECSA"],
  ].forEach(([baseId, defaultToken]) => {
    const el = byId(`pro-${baseId}-match`);
    if (el) {
      el.addEventListener("change", () => {
        syncMatchFieldMeta(baseId, defaultToken);
      });
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    closeHelpPanel();
    closeSystemPanel();
    closeAISettingsPanel();
  });
}

function init() {
  currentLang = localStorage.getItem("electrochem_v6_lang") || "zh";
  applyI18n();
  bindEvents();
  switchTab("pro");
  toggleDataTypePanels();
  syncFeatureBlocks();
  syncAllMatchFieldMeta();
  syncPotentialConversionUI();
  renderResultPlaceholder();
  byId("conv-title").textContent = t("conv_none");
  byId("conv-meta").textContent = t("conv_auto_create");
  fetchHealth();
  loadConversations();
  loadStatsAndHistory();
  loadProjects();
  loadPromptSettings();
  loadLLMConfig();
  loadTemplates();
}

init();



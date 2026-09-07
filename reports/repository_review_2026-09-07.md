**ElectroChem V6 仓库审查记录 · 2026-09-07**

后续修复状态：下述 11 项缺陷已处理，逐项行为及最终验证见[修复记录](../reports/repository_fixes_2026-09-07.md)。本文保留修复前的复现证据，代码行号可能随修复移动。

本次评估以磁盘上的当前工作区为准，包含已有未提交改动；当前 HEAD 为 `0102981`，应用版本为 `6.0.20`。没有修改业务代码。审查覆盖计算、解析、后台任务、历史与项目归档、存储清理、UI 会话状态、LLM 配置和发布流程。

项目已有清晰的计算模块注册机制、统一结果模型、SQLite 存储、后台任务以及数值参考测试。主要改进方向是防止静默误算、保证任务文件生命周期一致，以及解决异步界面的状态错配。

验证使用本机系统 Python 3.12；项目 `.venv` 没有安装开发检查工具，因此没有用该环境运行测试。以下检查均通过：

| 检查 | 结果 |
| --- | --- |
| `python -m pytest tests/ -q --tb=short -p no:cacheprovider` | 870 项测试全部通过 |
| `python -m ruff check src/ tests/ --no-cache` | 全部通过 |
| `python -m pyright src/` | 0 errors / 0 warnings |
| `python run_v6.py check` | `ok=true`，五类处理模块可运行 |
| `python run_v6.py smoke --port 18131` | `ok=true`，8 项 API/UI 入口检查通过 |

下列缺陷通过补充的临时最小复现发现，当前测试没有覆盖这些触发条件。涉及数据的复现均使用临时目录和隔离运行环境，UI/模型切换复现使用原函数及 mock；没有发送外部模型请求。没有重新构建或安装 Windows 发行包，也没有核验真实厂商仪器导出的全部格式；不将现有测试通过等同于这些验证已经完成。

P1 表示应优先修复的数据删除或严重结果错误；P2 表示应安排修复的条件性结果错误和功能问题。

1. **[P1] FE 产品表忽略列头单位，结果可能放大 1000 倍，质量报告仍判通过。**

   位置：[processing_coupled_io.py:50](../src/electrochem_v6/core/processing_coupled_io.py#L50)、[processing_coupled_io.py:221](../src/electrochem_v6/core/processing_coupled_io.py#L221)。列名归一化无条件删除括号中的内容，随后把原始数值直接写入 `product_moles`。

   完整管道复现输入为 `sample,product,Product Moles (mmol),n,Charge (C)`，数据为 `A,H2,0.000001,2,1`。输出 `product_moles=1e-6 mol`、FE=`19.297066424%`；按列头单位换算应为 `1e-9 mol`、FE=`0.019297066424%`。实际写出了 `coupled_results.csv`，质量报告仍是 `is_valid=True, warnings=[], quality_level="good", recommendation="accept"`。

   建议保留并解析列头单位，进入计算前统一换算为内部单位。不支持的单位应明确拒绝；单位冲突不能通过删除单位来“兼容”。回归测试同时校验输入数值、标准化单位、最终 FE 和质量状态。

2. **[P1] “清理孤立文件”会删除尚在排队或运行的上传目录。**

   位置：[storage_service.py:83](../src/electrochem_v6/core/storage_service.py#L83)、[routes_post.py:320](../src/electrochem_v6/server/routes_post.py#L320)。清理只从历史记录读取 `artifact_root` 引用；上传准备阶段已创建目录，但直到处理成功才绑定历史来源。

   隔离复现阻塞单 worker，经真实 `_prepare_uploaded_zip_job` 保存 ZIP 并提交任务。清理前：`job.status=queued`、ZIP 存在、`referenced_runs=0, orphaned_runs=1`。调用 `cleanup_orphaned_runs()` 后返回成功并删除该任务目录；任务仍为 `queued`，ZIP 已不存在。任务后续会遇到解压或文件访问失败。正在执行但尚未绑定历史的任务也处于同一引用空窗期。

   建议创建上传目录时即登记运行及文件引用，准备中、排队中和运行中的任务都应阻止清理。引用检查与删除需要共享生命周期锁或租约机制，避免检查之后任务又开始使用文件。添加真实排队上传与清理并发的回归测试。

3. **[P2] ECSA 在评价电位恰好等于采样点时，最后 N 圈平均会取错圈。**

   位置：[processing_ecsa_calc.py:37](../src/electrochem_v6/core/processing_ecsa_calc.py#L37)、[processing_ecsa_calc.py:97](../src/electrochem_v6/core/processing_ecsa_calc.py#L97)。`<=0` 的穿越判断会把同一个精确交点两侧线段都计入。

   合成两圈数据，`Ev=0` 恰在采样点，第一圈电流为 ±1 mA、第二圈为 ±2 mA，面积 1 cm²，设置 `last_n=2, avg_last_n=True`。实际检测 `up=4, down=4`，返回 ΔJ=`4 mA/cm²`；按两圈平均应为 `3 mA/cm²`。错误会继续传递到 Cdl/ECSA。

   建议按扫描分支去重交点，或采用半开区间判定；选择最后 N 圈应建立在实际循环配对之上。测试需包含评价电位恰好命中采样点、未命中采样点和首尾部分循环。

4. **[P2] ECSA 所有扫速相同时，仍输出不可辨识的拟合与 R²=1。**

   位置：[processing_ecsa_calc.py:121](../src/electrochem_v6/core/processing_ecsa_calc.py#L121)、[processing_ecsa.py:134](../src/electrochem_v6/core/processing_ecsa.py#L134)。拟合仅检查点数不少于两条，没有检查有效扫速是否不同；响应方差为零时直接把 R²设为 1。

   两个重复实验文件 `ECSA10_a.txt`、`ECSA10_b.txt`，扫速均为 0.01 V/s、ΔJ 均为 1 mA/cm²。真实 `process_ecsa_for_subfolder()` 返回 `N_points=2, R2=1.0, Cdl_mFcm2≈25, ECSA_cm2≈625` 并生成 PNG。NumPy 的病态拟合警告没有阻止成功输出。

   建议拟合前校验不同有效扫速数和设计矩阵秩，明确处理零方差及病态拟合；无法识别斜率时返回失败状态。对重复扫速可以保留重复实验统计，但不能把重复点当成扫速覆盖。

5. **[P2] 普通本地处理成功后，项目 ZIP 导出可能只包含清单。**

   位置：[project_archive.py:155](../src/electrochem_v6/core/project_archive.py#L155)、[processing_cv_history.py:22](../src/electrochem_v6/core/processing_cv_history.py#L22)。归档依赖历史记录的 `folder_path` 判断文件是否属于可信数据目录；普通 CV 历史只保存 `file_path`，没有保存该目录字段。其他若干类型的历史构建器也没有填充它。

   在应用数据目录之外的独立目录处理正常 CV 文件，采用默认输出位置。真实 `process_folder()` 成功，写入 1 条历史和 7 个存在的结果文件；历史 `folder_path=null`。再调用项目归档函数，得到 `file_count=0, skipped_count=8`，ZIP 仅含 `archive_manifest.json`。因此“下载成功”不足以证明结果已备份。

   建议在运行/历史持久化时保存经校验的输入根目录、输出根目录和文件清单，并兼容已有缺失元数据；保留归档的目录边界检查。端到端测试应先真实处理，再导出并核对文件内容，不能只构造已补齐目录字段的测试历史。

6. **[P2] 快速切换 AI 会话可能显示 A 的内容，却把后续消息发到 B。**

   位置：[app.js:1896](../src/electrochem_v6/ui/static/app.js#L1896)。`openConversation()` 先更新当前 ID，等待响应后直接渲染，没有校验响应是否仍属于当前选择。

   用实际函数模拟依次打开 A、B，响应按 B、A 顺序返回，结果为 `sendTarget=B, visibleTitle=A, visibleMessages=A history`。用户看到的上下文与消息实际归属不一致。

   建议为每次会话切换分配请求序号，响应渲染前核对；将当前选择、详情加载和后台任务归属分开保存。补充乱序响应及请求期间新建会话的测试。

7. **[P2] 搜索会话会清空仍然打开的会话 ID，下一条消息另建会话。**

   位置：[app.js:1884](../src/electrochem_v6/ui/static/app.js#L1884)。列表接口仅返回筛选结果的前 30 条，代码却把当前会话不在结果中视为不存在，清空 ID 而保留聊天内容。

   当前显示 A，搜索仅匹配 B，复现结果为 `sendTarget=null, visibleTitle=A`。继续发送会创建新会话，原有上下文不再关联。

   建议列表搜索与当前会话独立；只有删除成功或详情接口确认不存在时，才清空当前选择。

8. **[P2] 预检期间重复点击处理按钮会提交多个作业。**

   位置：[process_runtime.js:104](../src/electrochem_v6/ui/static/process_runtime.js#L104)。函数只检查活动 job ID，而该 ID 在预检和提交完成后才设置。预检等待期间没有提交锁。

   连续调用实际 `runProcess()` 两次，再释放预检 Promise，`submitProcessJob` 实际调用 2 次。后台每次创建新 UUID，因此会接受两个任务。两个轮询共用一个活动 ID，先完成者还可能清空另一作业的取消入口。

   建议在进入提交流程时立即设置 `submitting`，覆盖预检至取得 job ID 的全部阶段；后续状态更新只作用于对应作业。必要时为提交请求加入幂等标识。

9. **[P2] 已有 AI 会话忽略新选择的供应商和模型。**

   位置：[service.py:375](../src/electrochem_v6/agent/service.py#L375)。命中会话缓存后，代码直接复用旧 controller 的 provider、model 和客户端，覆盖此次请求设置。

   使用 mock 客户端，同一会话第一次指定 `openai/old-model`，第二次指定 `deepseek/new-model`，实际仍返回旧组合，客户端创建次数为 1。前端每次发送确实携带设置面板中的 provider/model，因此实际行为与界面选择不一致。

   建议比较供应商、模型和配置版本；配置变化时更新客户端并保留会话历史。若产品决定会话固定模型，应让设置生效范围在界面上明确可见。

10. **[P2] CV 从电位窗口中间起扫时，分圈图遗漏最后一段。**

    位置：[processing_cv_calc.py:185](../src/electrochem_v6/core/processing_cv_calc.py#L185)，调用位置：[processing_cv.py:150](../src/electrochem_v6/core/processing_cv.py#L150)。算法固定按两个相邻扫段拼一圈。

    完整单圈 `0→1→-1→0`，具体输入 `[0,.5,1,.5,0,-.5,-1,-.5,0]`，只返回 `start_index=0, end_index=6`，即 `0→1→-1`，遗漏最后 `-1→0`。影响分圈图及分圈峰分析；总曲线指标使用完整原始数据，不受此处截断影响。

    建议结合起始电位和扫描方向判断闭合循环，保留并标记不完整段，补充窗口中点起扫用例。

11. **[P2] 宣称支持旧版 `.xls`，但运行和打包依赖缺少读取引擎。**

    位置：[processing_coupled_io.py:234](../src/electrochem_v6/core/processing_coupled_io.py#L234)、[requirements.txt](../requirements.txt)、[requirements-pack.txt](../packaging/requirements-pack.txt)。代码对 `.xls` 调用默认 `pandas.read_excel`，依赖列表包含 openpyxl，但未包含 xlrd。

    本机 xlrd 不存在。使用 pandas 能识别为 `xls` 的文件头验证读取器选择，在读取内容前即报 `ImportError: Missing optional dependency 'xlrd'`。此项验证的是引擎依赖缺失，没有用该文件头冒充完整 Excel 工作簿做功能测试。

    建议若保留 `.xls` 支持，则在安装和打包依赖中统一加入读取引擎，并使用真实小型 `.xls` 夹具验证发行包；否则在支持范围和导入校验中明确排除该格式。

除以上已复现的问题，还建议安排以下工程改进。这些是基于当前代码结构的建议，不表示已观察到对应线上故障：

- **把科学数据的单位和有效性作为模块契约。** 扩展现有输入配置与结果模型，明确原始单位、标准化数值、转换规则和拒绝原因。重点补充量纲变化、相同扫速、精确交点、首尾部分循环等参考用例。质量报告应能表达无法得出可靠结论，避免把计算返回值存在等同于有效。
- **让运行文件的引用覆盖完整生命周期。** 在现有 job、history、manifest 之间统一输入根目录、输出根目录、artifact 所有权和运行状态。上传、执行、取消、归档和清理应使用同一套事实来源。
- **把 UI 异步竞争纳入测试。** 当前浏览器用例集中在正常流程；增加双击、乱序返回、搜索当前会话、请求期间切换会话、已缓存会话换模型等用例，比只增加字符串存在性检查更能覆盖实际问题。
- **逐步降低大文件的职责密度。** `app.js` 约 3665 行，`database.py` 约 2313 行，`process_service.py` 约 1405 行。优先按会话状态、处理任务、项目/历史持久化等职责继续拆分，沿用现有模块边界和接口，避免一次性重写。
- **将发布成功条件前移到推送版本标签之前。** [ci.yml:118](../.github/workflows/ci.yml#L118) 先提交并推送版本与标签，随后才构建、签名。静态可见：后续构建或签名失败时，远端仍留下已推进的版本。建议先完成构建、签名和产物验证，再发布标签与资产；增加发布互斥和失败重试设计。本次未执行发布流程。
- **统一依赖与支持版本的验证方式。** 常规安装、打包和 `requirements-frozen.txt` 使用不同依赖入口，CI 仅测 Python 3.12，而包声明支持 Python ≥3.10。建议从统一约束生成不同用途依赖，并对声明的最低版本做兼容检查；发布时保存所用依赖清单。

建议修复顺序：先处理 FE 单位与活跃任务清理；再处理 ECSA 边界、项目导出及 UI 状态问题；随后补齐格式支持、发布可靠性和模块拆分。每项修复都应加入能复现原触发条件的回归用例，并校验最终导出结果或可见 UI 行为。

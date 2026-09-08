# 7.0.1 干净系统验收与发布者签名进度

日期：2026-09-08。用户已授权推进正式发布前的独立 Windows 验收和发布者签名。当前状态为：**验收工具与签名流程已准备，真实干净系统验收和公信发布者签名尚未完成**。此记录不改变已有候选包的未签名状态。

用户随后确认本轮**先准备验收工具**，独立 Windows VM 的实际安装、升级和卸载暂不执行。签名身份仍待确定。

## 本轮已处理

- 读取当前用户及本机个人证书库，两处均无代码签名证书；未访问私钥或导出证书。签名环境配置也为空。GitHub CLI 查询仓库签名配置返回 401，因此不能断言远端是否已有凭据。
- 从微软官方 NuGet `Microsoft.Windows.SDK.BuildTools 10.0.26100.9169` 准备了工作区内的 x64 SignTool 及所需 DLL。三个文件均为有效微软签名，实际 `signtool verify /pa` 验证微软 WebView2 安装程序通过；不需要修改整机 SDK 安装。
- 本地签名支持 `-SignToolPath` 或 `ELECTROCHEM_SIGNTOOL_PATH`，并验证所选工具的微软签名。正式构建为 GUI、MCP、安装器和编译时的内嵌卸载器接入同一发布者签名流程，保留卸载器签名回执；任一步失败会停止。
- 正式构建在缺少证书时确实拒绝继续，原客户端 SHA-256 未变，没有创建输出安装包。没有创建测试根证书或改变 Windows 信任设置。
- 安装、签名和发布相关定向回归 **127/127 通过**，包括真实 Inno 卸载器回调、签名回调失败阻止生成、特殊字符路径和原有发布保护。Ruff 与差异检查通过。这些是代码/编译验证，不能代替真实公信签名。
- 准备 Windows PowerShell 5.1 独立 VM 验收脚本：默认只读预检；执行前核对目标 VM 身份、系统、无开发工具/现有数据和实际包哈希。执行分安装卸载、同版本修复、真实旧版升级，结果单独记录，不会把修复当成升级。
- 找到真实旧版候选 `ElectroChem-Setup-6.0.20.exe`，版本资源为 6.0.20，SHA-256 为 `e24175f5d2762c8d2e831178a5dbc4a90863598c0e9e43c494d4607b56fd94ff`。新旧包均未签名，若先做候选验收，报告明确保持 `formalReleaseEligible=false`。
- 已写[签名路线说明](windows_signing.md)和[未提交的 SignPath 英文申请草稿](signpath_application_draft.md)。草稿未假填身份、邮箱、地区、权限或二次验证状态，没有发送申请或对外消息。

本地原始证据位于 `.test_runtime/windows-release-acceptance/`：`host-readiness-unrestricted.json`、`host-with-sdk.json`、`sdk/download.json`、`sdk/verification.json`、`signing-guard.json`、`regression.xml`。这些报告仅用于本次准备，不是 Windows VM 验收报告。

## 验收中发现并修复的端口问题

旧 Windows 服务使用 `SO_REUSEADDR`，不同数据目录的两个客户端可能同时声称监听同一地址，导致原生 API 请求进入另一实例。已改为在绑定前设置 `SO_EXCLUSIVEADDRUSE`，由桌面已有逻辑在端口占用时尝试其他端口；明确携带错误 `X-Electrochem-Session` 的写请求现在返回 403，而不是回退到无令牌原生请求路径。5 项真实套接字/API 测试及 59 项既有服务端、桌面与 MCP 回归通过。该改动依据[微软 Winsock 独占地址说明](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse)。

首轮开发机隔离测试在发现该问题前，误向已安装客户端创建一个空项目：`proj_20260908232907_d04fe398`，名称 `Windows VM acceptance 36c34970-fce0-4d19-9c7c-39b5193acf42`。处理预检被拒绝，未提交数据处理任务。确认该精确项目仍为零样品、零结果后，仅通过应用的可恢复操作移入回收站；其余项目元数据前后完全一致，没有删除实验文件。证据为 `owned-empty-project-cleanup.json`。首轮失去窗口的自建测试进程经路径、启动时间及空数据库核对后单独终止，不能记作正常退出通过；已安装客户端继续运行，见 `owned-probe-cleanup.json`。

验收脚本现会在启动后及每次 API 请求前核对实际监听 PID，只允许本次进程独占的端口，并携带正确 Origin 与会话令牌；安装后核对 GUI/MCP 的版本和发布者签名，升级前后核对真实历史记录标识、结果元数据、输出引用和记录数，不以空项目或样品列表存在代替结果保留。**39 项 Windows PowerShell 5.1 验收脚本测试通过**。

修复后重新完整构建到 `dist_7_0_1_release_candidate` 和 `dist_installer_7_0_1_release_candidate`。225 个源码/配置快照前后相同，冻结 GUI/MCP 模块与源码逐一核对通过，静态文件匹配，环境自检 5 项通过。新 GUI SHA-256 为 `1bb23e2e19f294b4421cf743fe13b8c4caad81e3182f425c8a48e815e17bd7d3`。

新包的真实桌面隔离验证通过：在已有 8010 监听者存在时自动使用独占端口 8011，240 点合成 CV 完成，PNG/CSV 与历史结果核对通过，窗口正常关闭后进程退出且会话文件移除。证据为 `.test_runtime/windows-acceptance-script-integration-20260908-e/integration-report.json`。该报告的 `installationAttempted` 和 `formalReleaseEligible` 均为 `false`；它仍不代表干净系统安装、升级或卸载通过。

早期 `dist_7_0_1_windows_verified` / `dist_installer_7_0_1_windows_verified` 中的候选保留用于追溯，已被本轮修复取代，不再作为发布或验收输入。本轮定向测试合计 **230 项通过**（127 项安装/签名/发布、64 项服务端及桌面回归、39 项验收脚本），不包含重复执行的计数。

## 当前候选与工具包

下列文件均为 **7.0.1 未签名候选**。已核对全部便携 ZIP 条目、安装包依赖清单、PE 版本、SHA-256 及打包前后源码一致性，原始报告为 `.test_runtime/windows-release-acceptance/port-isolation/artifact-report.json`。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `dist_installer_7_0_1_release_candidate/ElectroChem-Setup-7.0.1.exe` | 90,360,102 | `d8ad08d9264f3fe36a86530b0de417227502aa544ec249ed8b6dc5b1c4e5cc09` |
| `dist_installer_7_0_1_release_candidate/ElectroChem-Setup-7.0.1-offline.exe` | 352,341,639 | `3d8f08be41dba0b9d3111eca9be49d3a722e72faf9d921377d5122ca709401c8` |
| `dist_7_0_1_release_candidate/ElectroChem-7.0.1-win64.zip` | 123,106,538 | `613d28778918deca3951ca797b5d7184d6cc6487f41582df8741c6d0b736515e` |

验收工具集中输出为 `dist_acceptance_7_0_1/ElectroChem-7.0.1-acceptance-kit.zip`，完整解压后从 `START-HERE.zh.md` 开始。包内包含上述三份候选、真实 6.0.20 升级基线、六份系统/场景模板、默认只读预检脚本、人工矩阵及签名说明。模板需要填写真实 VM UUID 和计算机名，不能在当前开发机执行安装。文件清单写入 `kit-manifest.json`，整包校验值为旁边的 `.zip.sha256`；`status=prepared_only`，实际干净系统验收和签名均为未完成。

## 仍需实际环境与身份

### 测试环境

本机 Hyper-V 服务存在，但在受限和正常用户执行环境中，`Get-VM` 都因 Windows 管理权限被拒绝；进程没有管理员令牌。Windows Sandbox 未安装，已检查的常用位置没有 Windows ISO 或可用的其他虚拟化程序。没有创建、启动、修改或删除虚拟机，也没有在开发机安装/升级/卸载 ElectroChem。

后续需要由拥有权限的用户提供可用的 Windows 10 22H2 x64 / Windows 11 x64 独立测试机或 VM，或允许在指定主机上准备新的测试 VM，并提供合法可用的系统镜像。本轮按用户选择仅交付工具。管理员权限用于管理 VM及VM内安装，不应为通过测试而删除开发机资料或修改整机防护。

微软的 Hyper-V 创建流程要求本地管理员或 Hyper-V Administrators 权限及相应系统介质。[微软 Hyper-V 文档](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/create-a-virtual-machine-in-hyper-v) 本轮访问原 Windows 10 Enterprise Evaluation 下载入口时已被重定向，不能保证旧的下载链接仍提供所需 22H2 镜像；应使用用户合法已有的镜像或当前官方渠道，不以 LTSC/Server 替代本轮目标系统。

具备环境后，按 [验收脚本说明](../packaging/acceptance/README.md)执行对应的自动生命周期场景，再补齐[独立 Windows 矩阵](windows_acceptance_7.0.1.md)中的断网、运行库缺失/过旧、普通用户、缩放、任务恢复及其他人工项目。脚本默认不强杀、不重启、不删除目录；失败保留日志与现场。

### 发布者签名

公信签名需要已获授权的代码签名证书或签名服务账户。当前没有这些凭据，本地生成一个自签证书不能代替普通用户电脑信任的发布者身份。

建议先确认个人/机构身份、真实地区，以及是否接受 SignPath Foundation 作为证书发布者。开源计划需要项目审核；如需要显示自己的实名发布者，则先由证书机构确认该申请主体的受理条件与完整费用。取得身份、硬件令牌或云服务权限后，才能完成实际签名。

当前 GitHub 签名工作流仍采用 PFX 导入方式。新硬件令牌、SignPath 或云 HSM 不能凭空套入这个入口；选定供应商后再接其官方流程，不导出受保护私钥或降低校验。签名完成会改变文件，必须重新生成 ZIP/安装器、哈希及清单，并对最后一份实际发布文件完成验收。

**本轮没有签署或发布软件、购买证书、代填身份验证、发送申请、推送 GitHub 或修改正式安装。**

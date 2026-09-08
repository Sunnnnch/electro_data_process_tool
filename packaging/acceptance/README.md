# 独立 Windows 虚拟机验收包

此脚本面向可还原的干净 Windows 10 22H2 x64 / Windows 11 x64 虚拟机，不需要安装 Python、Node、Git 或开发工具。使用系统自带的 **64 位 Windows PowerShell 5.1**。默认只预检；本机开发环境会被拒绝。当前脚本及候选包的准备、契约测试或开发机上的隔离任务验证，都不能填作干净 Windows 验收通过。

## 准备目录

把这些文件复制到 VM 的普通目录，例如 `C:\AcceptanceKit`。不要复制整个源码仓库，也不要放进待安装的应用目录。

```text
AcceptanceKit/
  Invoke-WindowsAcceptance.ps1
  manifest.json
  README.md
  artifacts/
    ElectroChem-Setup-7.0.1.exe
    ElectroChem-Setup-6.0.20.exe       # 仅真实旧版升级场景需要
```

`manifest.example.json` 已记录现有 **未签名候选包** 的 SHA-256，包括真实版本 6.0.20 的旧安装包。签名或重建会改变文件，届时必须替换对应 SHA-256；已签名包还必须填写真实发布者证书指纹。不要把同版本重建包改版本号作为旧版本。脚本会核对实际安装包和安装后 EXE 的 PE 版本。所用基线必须支持真实桌面服务与项目 API；若旧版不具备该能力，本轮会停止并保留现场，应另作人工迁移验收。

## 只读预检

先从独立 VM 的快照启动，使用专门测试账户。确认无现有 ElectroChem 安装、运行任务和 `%USERPROFILE%\.electrochem` 目录，预先安装符合要求的 WebView2/.NET。标准自动流程不会补装、修复或下载 Windows 组件。以 VM 管理员身份打开 64 位 PowerShell：

```powershell
cd C:\AcceptanceKit
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\Invoke-WindowsAcceptance.ps1 -PreflightOnly
```

输出 JSON 的 `machine.vmUuid` 和 `machine.computerName` 来自当前机器；复制到 `manifest.json`。`runId` 使用 `[guid]::NewGuid().ToString()`，每次换新值。`osFamily` 填 `Windows10` 或 `Windows11`。示例占位符不能执行。

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\Invoke-WindowsAcceptance.ps1 `
  -ManifestPath .\manifest.json -PreflightOnly -AllowUnsignedCandidate
```

示例中的执行策略只作用于该 PowerShell 子进程，不修改整机或用户策略。若下载的未签名脚本被来源标记阻止，应在独立 VM 中先核对验收包的 SHA-256，再由测试管理员按其组织规则解除这个脚本的阻止；组织策略不允许时不要绕过。

预检只读取本机和包信息，不创建数据目录、不启动客户端、不安装或卸载、不修改注册表。`blockers` 必须为空才能执行。它同时核对 VM UUID、计算机名、虚拟硬件、系统/位数、管理员权限、开发工具、源码/Codex配置、已有应用/数据/安装记录以及测试环境变量。不应删除开发机资料或绕过这些检查；使用新的独立 VM 快照。

## 明确执行

确认这是可丢弃、可还原的 VM，包的哈希与预检结果一致后，使用该 VM 的实际 UUID：

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\Invoke-WindowsAcceptance.ps1 `
  -ManifestPath .\manifest.json -Execute `
  -Confirmation 'DISPOSABLE-VM:VM的实际UUID' -AllowUnsignedCandidate
```

`-AllowUnsignedCandidate` 只允许 `NotSigned` 的已核对哈希候选包；签名损坏、HashMismatch、不可信签名或发布者不匹配仍会拒绝。未签名验收报告固定标记 `distributionStatus=unsigned_candidate`、`formalReleaseEligible=false`。已签名包可省略该开关；签名候选的卸载程序也必须具有同一发布者的有效签名。脚本不签名、不导入证书、不宣称完整发布资格。

执行顺序：

1. 安装到固定的 `C:\ElectroChem-Acceptance\<runId>\app`；安装器按自己的 AppId 写入 Windows 安装登记。核对安装后的 GUI 与 MCP 程序的版本、哈希和发布者签名；7.0.0 起要求存在 MCP，6.0.20 基线缺少 MCP 时明确记为旧版不提供。脚本本身不写、删除或改写注册表。
2. 新版本运行包内 `--environment-check --json --output`，确认 WebView2、默认用户数据目录和嵌入窗口可用。
3. 显示真实客户端窗口，只读取本次启动、路径及 PID 均核对的新实例会话；启动时与每次 API 调用前还要核对 TCP 监听端口仅属于该 PID，避免请求进入别的客户端。调用本机 API 创建项目、生成 240 行合成 CV 数据、预检并完成小任务，确认 PNG/CSV 和项目结果已保存。
4. 保存独立 marker 与输入/输出哈希。给自己的窗口发送正常 WM_CLOSE，等待实际进程退出和会话文件移除；返回“已接收关闭请求”不算退出通过。
5. 根据场景升级或同版本修复，重开后核对原项目、实际历史记录的 `record_key`、CV 类型、结果元数据、输出引用、数据条数与 marker；有样品空壳但没有历史结果不能通过。最后卸载，核对用户数据库、合成输入/输出和安装目录中的测试 `user_data` marker 均保留。

所有阶段写 `C:\ElectroChem-Acceptance\<runId>\report.json`，并保留安装/卸载日志、环境 JSON 与合成数据。失败、超时、仍有任务运行或无法退出时，立即停止后续升级/卸载，**不强杀、不重启、不清理目录**。回到 VM 内检查任务和托盘，保留失败报告；重新测试前还原快照，而不是清理真实用户目录。

## 场景与报告边界

- `scenario=install_uninstall`、`baseline=null`：新版本安装、任务、退出与卸载保留数据。
- `scenario=repair`、`baseline=null`：同版本安装覆盖与数据保留，只写 `repairStatus`，`upgradeStatus` 保持 `not_run`。
- `scenario=upgrade`、`baseline` 是实际较低版本包：先旧版安装并真实创建项目/结果，再升级目标版本。通过时记录旧包版本、SHA-256 和 `upgradeStatus=passed`。
- 请求升级但 `baseline=null`：继续新版本安装/卸载的可做部分，升级始终 `not_run`。

此自动流程使用 VM 管理员测试账户，不能代表普通用户验收；也不证明全部科学模块的数值正确性或 UI 的显示缩放。缺少/过旧 WebView2、离线包交互批准/拒绝/重启、普通用户、100/150/200%缩放、全部科学模块、异常退出恢复、运行中升级保护、卸载后重新安装等仍按 `docs/windows_acceptance_7.0.1.md` 在独立快照手工验收。断网本身不由此脚本设置或认证；不要把已有运行库的静默安装写成“缺失运行库离线安装通过”。

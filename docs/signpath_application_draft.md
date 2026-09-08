# SignPath Foundation 申请草稿

**状态：仅供开发者审阅；尚未提交、尚未获批。** 本文不是已经生效的 Code Signing Policy，不代表 SignPath 已授权项目使用其证书。所有 `[TO CONFIRM]` 项目必须由开发者确认后才能用于申请。

## English application draft

**Subject: Application inquiry — ElectroChem open-source Windows application**

Dear SignPath Foundation team,

We would like to ask whether ElectroChem is eligible for your open-source code signing program and what additional information or changes you would require. The information below describes our project and proposed signing scope. We are not yet using a SignPath Foundation certificate and have not completed SignPath onboarding.

### Project details

- Project name: ElectroChem — Intelligent Electrochemical Data Processing Software (智能电化学数据处理软件).
- Public repository: <https://github.com/Sunnnnch/electro_data_process_tool>.
- Project license: MIT, as recorded in the repository's `LICENSE`. Third-party components retain their own licenses.
- Version currently declared in the working source: 7.0.1. The exact public release and source revision to be submitted are `[TO CONFIRM: existing release URL, tag and full commit SHA]`.
- Applicant name and contact email: `[TO CONFIRM]`.
- Applicant's country/region and individual/organization status: `[TO CONFIRM]`.
- Applicant's authority to represent the repository and maintain the project: `[TO CONFIRM]`.

ElectroChem is a scientific desktop application for local electrochemical data processing. It imports exported numerical tables and supports linear sweep voltammetry, cyclic voltammetry, impedance spectroscopy, electrochemical surface-area analysis and coupled-product/Faradaic-efficiency calculations. It also provides project history, result review, parameter templates, reruns and reproducible reports. Core calculations do not require an AI account or network access.

The Windows desktop consists of a Python application, a WebView2-based interface and a loopback HTTP service. A separate local stdio MCP companion can expose selected project and processing tools to an AI client configured by the user. This companion does not expose a public Internet MCP endpoint.

### Proposed build provenance and approval process

The repository contains the Python source, web UI, PyInstaller specification, Inno Setup script and PowerShell build scripts. Windows packaging uses Python 3.12, a pinned direct dependency baseline and a recorded inventory of installed package versions. The present dependency setup is not a complete hash-locked transitive dependency graph, and we do not claim byte-for-byte reproducible builds.

The existing manual GitHub release workflow takes an explicit release tag and full expected commit SHA, verifies that source version and tag agree, and runs lint, type checks and tests before building. Source pushes alone do not publish releases. Artifact checks verify expected filenames, version metadata, signatures, hashes and exclusion of user data from the portable archive.

The current signing workflow is not integrated with SignPath. If accepted, we propose to configure an approved build-origin verification and signing-approval flow using your supported integration. We would identify the actual authors, reviewers and signing approvers, require the applicable account protections, and publish an accurate Code Signing Policy before requesting production signatures. These controls and named roles remain to be confirmed; this draft does not assert that they are already in place.

- Authors/committers: `[TO CONFIRM: names or repository teams and authority]`.
- Reviewers: `[TO CONFIRM]`.
- Signing approvers: `[TO CONFIRM]`.
- GitHub and SignPath two-factor authentication status: `[TO CONFIRM; do not infer from repository access]`.
- Proposed CI workflow, artifact configuration and release-approval method: `[TO CONFIRM WITH SIGNPATH]`.

### Proposed signing scope

Subject to your approval, we would like to cover:

- `ElectroChem.exe`, the main PyInstaller desktop executable.
- `ElectroChem-MCP.exe`, the PyInstaller stdio companion.
- The standard Inno Setup installer and, if permitted, a separately identified offline installer.
- The Inno-generated application uninstaller, so installation and uninstallation show a consistent, verified publisher.

Please advise whether this scope, including the PyInstaller-generated executables and Inno-generated uninstaller, meets your artifact requirements. We would enforce the product name and release version in the artifact metadata. We would not use the project's certificate to re-sign unrelated upstream executables or libraries.

### Third-party components and offline installer

The packaged application contains upstream Python and scientific libraries, pywebview/pythonnet components, an MCP SDK and application-local runtime files. A per-build package inventory and the relevant license notices can be supplied for review. The full third-party license and distribution review for this application is `[TO CONFIRM]`.

The standard installer does not bundle or silently download WebView2. It requires an existing suitable Runtime or directs the user to Microsoft's installation page with their agreement. The optional offline variant embeds the official Microsoft Evergreen Standalone x64 installer. The build validates Microsoft's existing signature and the Runtime identity/version before accepting that dependency; installation of a missing or outdated Runtime requires the user's approval.

Microsoft's WebView2 installer would retain its Microsoft signature and would not be re-signed using the project's certificate. We specifically request confirmation that this prerequisite and the other platform runtime components are acceptable under your component-distribution rules. If the offline variant is not eligible, please advise whether the standard installer and portable package can be reviewed separately.

### Network behavior and privacy disclosure

Project history, configuration and calculation outputs are stored locally. The ordinary desktop service listens on loopback and the MCP companion connects to that local service. The application's environment diagnostic report is generated locally; it does not upload itself.

Optional network interactions include:

- When a user configures and invokes the built-in AI assistant, prompts, conversation context and analysis/result information included in the request may be transmitted to the configured model provider or endpoint. Core numerical processing remains available without this feature.
- A user-triggered update check queries release metadata from the project's GitHub repository. The client can open the official release page; it does not silently replace the installed application.
- When users connect an external AI host through MCP, information returned to that host may be processed according to the host's own model settings and privacy policies.
- User-opened external links and Microsoft prerequisite installation may involve the user's browser or Microsoft's components. The Evergreen Runtime can use Microsoft's own maintenance/update mechanisms; an offline installer does not imply that third-party components never use the network afterward.

We will provide a reviewed public privacy notice covering these behaviors and the applicable third-party policies. Its location and completed network-behavior review are `[TO CONFIRM]`; we do not yet claim that the project satisfies every SignPath disclosure requirement.

Please let us know the evidence you need regarding the project's public release history, maintenance, reputation, build provenance and proposed artifact scope. We understand that acceptance is subject to your review and is not guaranteed.

Kind regards,

`[TO CONFIRM: applicant name and contact details]`

## 提交前需开发者确认

1. 申请人身份、所在地区、联系邮箱及代表仓库申请的权限；是否接受证书发布者为 SignPath Foundation。
2. 已公开发布的版本链接、拟签名版本和完整提交 SHA，以及项目长期保持开源的意向。
3. 作者、审阅者、签名批准人的实际名单和职责；各账号的 2FA 状态。
4. 第三方许可清单、公开隐私说明、真实网络行为核查，以及标准/离线安装包和卸载器是否都申请签名。
5. 经 SignPath 接纳后再确定实际工作流、签名批准和产物验证配置；不要把此草稿直接当成已满足条件的声明发布。

本草稿依据本地 `README.md`、`LICENSE`、`packaging/README.md`、`packaging/electrochem_v6.spec`、`.github/workflows/release.yml`、`docs/desktop_client.md`、`docs/mcp.md` 和更新检查实现整理。申请要求参见 [SignPath Foundation 条件](https://signpath.org/terms.html)及[官方申请入口](https://signpath.org/apply.html)。尚未发送邮件、提交申请或修改任何公网页面。

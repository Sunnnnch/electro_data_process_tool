# Windows 发布者签名安排

核对日期：2026-09-08。本文是接入前的操作安排；当前构建不能因此称为已签名。证书、服务受理地区和审核要求以实际申请时的官方确认结果为准。

## 当前状态

本轮只读检查未发现可用的当前用户代码签名证书，也未配置发布签名凭据。仓库已有本地 Authenticode 签名和发布验证脚本，但取得公信发布者身份仍需要开发者或签名机构完成。

本轮已补齐安装器编译期间的卸载器签名接线、明确的 SignTool 路径选择和签名回执检查。相关代码测试及微软 SDK 工具的只读验证已通过；尚未用真实发布者证书为本项目签名，安装后的卸载器公信签名仍待验收。

签名解决发布者身份和文件完整性问题，不替代干净 Windows 系统的安装、升级和卸载验收。有效签名的新文件仍可能显示 SmartScreen 信誉提示；微软说明 EV 证书也不再自动绕过该提示，不应只为“首次下载免警告”购买 EV。[微软 SmartScreen 说明](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)

## 选择路线

| 路线 | 对本项目的适用性 | 接入前需要确认 |
| --- | --- | --- |
| SignPath Foundation 开源项目计划 | 建议优先评估，免签名服务费用，适合继续公开维护的开源软件 | 项目是否获接纳、接受 Foundation 作为证书发布者、安装包组成与构建流程是否符合要求 |
| 支持个人核验的 CA 代码签名证书，配硬件令牌 | 若需要自己的实名发布者且可接受费用，适合先完成本地签名 | 中国个人是否受理、可接受身份证件和地址证明、令牌寄送、Windows 驱动和费用 |
| CA 的云 HSM 签名服务 | 适合以后在 GitHub Actions 中自动签名 | 中国个人开户、实名核验、授权方式、按次/订阅费用、官方 CI 接口 |
| Azure Artifact Signing 公开信任 | 若申请主体是中国个人，目前不作为可直接开通的路线 | 微软目前将个人开发者公开身份核验限于美国、加拿大；更换 Azure 资源区不能改变身份条件 |

SignPath 使用其 HSM 保管私钥，证书发布者为 SignPath Foundation。项目需要符合开源、已发布、可验证构建、双因素认证、签名批准与隐私说明等要求；申请不保证获批。本项目的 MIT 许可只是其中一个条件，离线包所带 Microsoft WebView2 等组件也需要按其规则确认。[项目说明](https://signpath.org/)、[申请条件](https://signpath.org/terms.html)、[申请入口](https://signpath.org/apply.html)

已准备[英文申请草稿及中文待确认项](signpath_application_draft.md)，尚未提交或获批，不能直接当成已经生效的签名政策。

Sectigo 官方提供个人身份核验流程，SSL.com 也提供个人代码签名核验说明。但这些通用页面不足以承诺某位中国申请者能够完成受理、核验和交付。购买前应让机构书面确认地区、证件、实名发布者格式与完整费用。[Sectigo 核验说明](https://www.sectigo.com/faqs/detail/OV-Code-Signing-Validation-for-Organizations-and-Individuals)、[SSL.com 核验说明](https://www.ssl.com/how-to/validation-process-for-document-signing-code-signing-and-ev-code-signing-certificates/)

Azure 的个人地区限制见[官方设置前提](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart#prerequisites)。Private Trust 不受相同地区限制，但不能替代面向普通 Windows 用户的公开信任签名。

## 现有脚本如何衔接

`packaging/sign_windows_binary.ps1` 使用证书指纹从 Windows 证书库选择身份，再调用 SignTool 和时间戳服务。硬件令牌或云 KSP 将证书及私钥操作关联到当前用户证书库后，有可能沿用此入口；需要用具体供应商驱动和一个待签副本实际验证，不能只凭证书出现在列表中就判定可用。

签名脚本和安装器构建脚本按 `-SignToolPath`、`ELECTROCHEM_SIGNTOOL_PATH`、默认 SDK 目录的顺序寻找工具，并核验其有效微软签名。指定路径应指向所在机器上已核验的 Windows SDK `signtool.exe`。

取得并配置签名身份后，可先在新的构建副本上执行以下流程。指纹不是私钥；PIN、证书密码和服务令牌由开发者在本机或服务安全界面提供，不写入仓库或聊天。

```powershell
# 仅列出证书公开信息，不导出私钥。
Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Select-Object Subject, Thumbprint, NotAfter, HasPrivateKey

$env:ELECTROCHEM_SIGN_CERT_SHA1 = '实际代码签名证书指纹'
$env:ELECTROCHEM_SIGNTOOL_PATH = '实际 Windows SDK 目录\signtool.exe'
& .\packaging\sign_windows_binary.ps1 -Path '新构建目录\ElectroChem\ElectroChem.exe' -RequireSigning
& .\packaging\sign_windows_binary.ps1 -Path '新构建目录\ElectroChem\ElectroChem-MCP.exe' -RequireSigning
```

公开可信代码签名的私钥现要求硬件保护。新签发的令牌/HSM 私钥通常不可导出，不能假定能生成包含私钥的 PFX。[DigiCert 当前密钥要求](https://docs.digicert.com/en/certcentral/order-and-manage-certificates/request-certificates/request-a-code-signing-or-ev-code-signing-certificate/request-code-signing-certificate.html)

当前 `.github/workflows/release.yml` 仍将 `WINDOWS_SIGNING_CERT_BASE64` 解码为 PFX 后导入证书库。这条流程不能直接用于新令牌、SignPath 或云 HSM。确定供应商后，应接入其正式接口，或在装有硬件令牌的受控机器上完成签名；不能通过导出受保护私钥、使用自签证书或关闭发布签名验证来绕过。

## 正式签名与验收步骤

1. 在实际选定的签名服务上验证 GUI、MCP 程序和安装器的签名、时间戳及公开可信证书链。
2. 使用已接通的 Inno 卸载器签名流程：要求签名或配置证书时启用 `SignTool` / `SignedUninstaller=yes`，编译回调调用同一签名脚本，检查有效签名、指定证书指纹和回执；缺少匹配回执会停止构建。最终还需实际安装并检查 `unins000.exe`，代码测试不能替代公信证书验收。[Inno Setup 官方说明](https://jrsoftware.org/ishelp/topic_setup_signeduninstaller.htm)
3. 完成所有嵌入文件签名后，再生成最终 ZIP、标准/离线安装器及各自 SHA-256 和依赖清单。签名会改变文件，旧哈希和旧清单不可沿用。
4. 用 `release_validation.py` 验证最终产物。目前验证要求 GUI、MCP 和安装器使用同一张发布者证书；若将来选择短期证书轮换的云方案，应据其官方身份契约重新设计此项，不能直接删掉校验。
5. 在未添加测试根证书的干净 Win10/11 上检查安装器、安装后的程序和卸载器，记录实际显示的发布者、签名有效性及 SmartScreen 行为，再完成发布验收。

## 开发者需要先确定的信息

- 以个人还是机构申请，以及真实所在国家/地区。
- 是否接受 SignPath Foundation 作为证书发布者；若用自有身份，接受在 Windows 发布者信息中显示经核验的实名。
- 是否长期保持开源，以及签名费用的大致预算。
- 希望先本地人工签名，还是必须在 GitHub Actions 中完成；是否已有签名账户或硬件令牌。

证件照片、地址证明等只在选定机构的官方核验流程中提交。尚未取得身份和签名权限时，可以继续完成测试、文档和源码准备，但二进制发布状态保持“未签名，待正式发布验收”。

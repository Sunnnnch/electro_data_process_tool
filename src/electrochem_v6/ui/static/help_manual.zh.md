# 电化学数据处理软件 V6 使用说明

## 软件用途

本软件面向电化学实验数据整理与结果复核，当前可处理 `LSV`、`CV`、`EIS`、`ECSA` 四类数据，并提供项目管理、历史追踪和 AI 辅助分析。

## 推荐工作流

1. 在“专业模式”选择数据根目录。
2. 填写项目名称，并勾选需要处理的类型，可多选。
3. 保持默认参数先跑通一轮，再调整高级参数。
4. 到“统计与历史”查看处理结果、输出文件和质量摘要。
5. 如需归档和复用结果，到“项目管理”查看项目历史、结果文件和导出报告。

## 文件夹读取逻辑

### 根目录和子目录

- 处理入口会把你选择的目录本身视为一个处理单元。
- 同时会继续扫描该目录下的一级子文件夹，每个一级子文件夹也会独立处理。
- 当前不会递归扫描二级、三级更深目录。

### 可读取的文件类型

- 当前会读取扩展名为 `.txt` 或 `.csv` 的文件。
- 已生成的结果文件会自动跳过，避免二次处理。
- 带有下列特征的文件名通常会被视为结果文件并忽略：`results.csv`、`combined`、`quality_report`、`summary`。

### 文件匹配策略

每种数据类型都可以单独设置“文件匹配策略”和“文件前缀/规则”。当前支持以下策略：

- `prefix`：文件名以前缀开头，适合命名规范的批量数据。
- `contains`：文件名中包含指定字符串，适合已有历史命名。
- `regex`：按正则表达式匹配文件名，适合复杂命名规则。

说明：

- `prefix` 与 `contains` 为大小写不敏感匹配。
- `regex` 使用 Python `re.search`，大小写不敏感。
- 正则写错时，该规则不会命中文件。

## 示例目录结构

### 单项目、根目录直接放数据

```text
HER_2026/
  LSV_sample01.csv
  LSV_sample02.csv
  EIS_sample01.csv
  EIS_sample02.csv
```

适合文件数量不多、命名规则统一的场景。

### 多样品、一级子目录分开

```text
HER_2026/
  Sample_A/
    LSV_01.csv
    EIS_01.csv
  Sample_B/
    LSV_01.csv
    EIS_01.csv
  Sample_C/
    LSV_01.csv
    EIS_01.csv
```

这是最推荐的组织方式，样品之间更容易隔离、回溯和批处理。

### ECSA 推荐命名

```text
ECSA_Project/
  Sample_A/
    ECSA_20mVs.csv
    ECSA_40mVs.csv
    ECSA_60mVs.csv
    ECSA_80mVs.csv
```

同一个目录下需要有多个扫描速率的 ECSA 文件，否则无法完成拟合。

## 常见命名规则示例

### 适合 `prefix` 的命名

- `LSV_sample01.csv`
- `CV_sample01.csv`
- `EIS_sample01.csv`
- `ECSA_20mVs.csv`

### 适合 `contains` 的命名

- `sample01_LSV_run1.csv`
- `2026-02-28_sampleA_EIS.csv`
- `NiFe_sample02_CV_cycle3.txt`

### 适合 `regex` 的命名

- 规则：`sample-\d+-lsv`
- 命中文件：`sample-01-lsv.csv`

- 规则：`^(HER|OER)_.*_EIS$`
- 命中文件：`HER_NiFe_01_EIS.csv`

## 支持的数据组织方式

### LSV / CV / EIS

- 同一个样品可以放在根目录，也可以放在某个一级子目录。
- 每个命中的文件会单独处理并生成输出。
- 如果同一个目录里有多份同类型文件，会逐个处理。

### ECSA

- ECSA 按目录聚合。
- 一个目录中需要至少两份命中的 ECSA 文件，才能完成 `ΔJ-v` 拟合。
- 文件名通常建议保留扫描速率信息，便于结果识别。

## 专业模式参数说明

### 通用参数

- `电极面积`：用于把电流换算成电流密度。
- `电位换算方式`：可选择手动偏移，或按 `RHE` 公式换算。
- `绘图与字体设置`：控制图标题、坐标轴名称、字体、字号和线宽。

### 电位换算

手动偏移模式：

- 直接输入整体电位偏移值，单位 `V`。

RHE 公式模式：

```text
E_RHE = E_measured + E_ref + 0.0591 × pH
```

需要设置：

- `pH`
- `参比电极` 预设，或自定义参比电位

### LSV 关键参数

- `目标电流`：支持多个值，逗号分隔，例如 `10,100`。
- `Tafel 区间`：线性拟合区间，格式如 `1-10`。
- `启用 iR 补偿`：可自动从 EIS 文件估算电阻，或手动输入电阻。
- `启用过电位`：打开后可填写理论平衡电位 `E_eq`，软件会计算 `η = |E - E_eq| × 1000`。
- `启用 Onset / Halfwave`：按给定电流阈值计算起始电位或半波电位。

### CV 关键参数

- `峰检测`：可设置平滑窗口、最小峰高、最小峰间距、最大峰数。
- 峰检测依赖数据质量，建议先用默认值确认是否识别稳定。

### EIS 关键参数

- 可绘制 `Nyquist` 和 `Bode`。
- 若 LSV 启用了自动 `iR` 补偿，软件会尝试优先匹配同目录下与样品名相关的 EIS 文件。

### ECSA 关键参数

- `Ev`、`最后 N 圈`、`平均最后 N 圈` 直接影响 `ΔJ` 计算。
- `Cs` 与单位用于计算 `ECSA` 和粗糙度因子。

## 输出结果说明

处理完成后，常见输出包括：

- 汇总结果表
- 单样品图像
- 质量摘要
- 项目历史记录

你可以在以下位置查看：

- “统计与历史”中的“处理结果”
- “项目管理”中的“最近历史”
- “项目管理”中的“结果文件”

结果文件支持：

- `复制路径`
- `打开文件`
- `打开目录`

## 项目管理说明

项目管理用于把处理结果按项目归档，而不是只看一次性的运行结果。

支持的操作：

- 新建项目
- 编辑项目名称、说明、标签、颜色
- 查看项目统计
- 查看最近历史
- 归档历史记录
- 删除历史记录
- 导出项目报告

### 归档是什么意思

归档不是删除。

- `归档`：保留记录，但默认不再参与常规列表和统计。
- `删除`：从历史里移除。

## AI 对话模式说明

AI 模式适合做以下工作：

- 结果解读
- 异常排查
- 报告草稿生成
- 与 ZIP 数据包联动分析

建议流程：

1. 先在 `AI设置` 里配置 `Provider`、`Model`、`API Key`。
2. 选择是否附加提示词模板。
3. 发送消息时，按需补充项目名、数据类型或 ZIP 文件。

## HTTP 接口说明

### 健康检查

```http
GET /health
```

### 专业模式处理

```http
POST /api/v1/process
Content-Type: application/json
```

#### `curl` 示例

```bash
curl -X POST http://127.0.0.1:8010/api/v1/process \
  -H "Content-Type: application/json" \
  -d '{
    "folder_path": "D:/data/demo",
    "project_name": "HER_2026",
    "data_types": ["LSV", "EIS"],
    "target_current": "10,100",
    "tafel_range": "1-10",
    "lsv_match": "prefix",
    "eis_match": "contains"
  }'
```

#### Python 示例

```python
import requests

payload = {
    "folder_path": "D:/data/demo",
    "project_name": "HER_2026",
    "data_types": ["LSV", "EIS"],
    "target_current": "10,100",
    "tafel_range": "1-10",
}
resp = requests.post("http://127.0.0.1:8010/api/v1/process", json=payload, timeout=120)
print(resp.json())
```

### AI 对话

```http
POST /api/v1/agent/messages
Content-Type: application/json
```

#### `curl` 示例

```bash
curl -X POST http://127.0.0.1:8010/api/v1/agent/messages \
  -H "Content-Type: application/json" \
  -d '{
    "message": "请总结本次 HER 结果",
    "project_name": "HER_2026",
    "data_type": "LSV"
  }'
```

#### Python 示例

```python
import requests

payload = {
    "message": "请总结本次 HER 结果",
    "project_name": "HER_2026",
    "data_type": "LSV",
}
resp = requests.post("http://127.0.0.1:8010/api/v1/agent/messages", json=payload, timeout=120)
print(resp.json())
```

### 查询项目和历史

```http
GET /api/v1/projects
GET /api/v1/history?project=<project_id>&limit=50
GET /api/v1/stats?project=<project_id>
```

### 文件与系统辅助接口

```http
POST /api/v1/system/select-folder
POST /api/v1/system/open-path
```

`open-path` 可配合 `reveal_only` 使用：

```json
{
  "path": "D:/data/demo/output/LSV_results.csv",
  "reveal_only": true
}
```

## 常见问题

### 为什么选了目录却没有结果

优先检查：

1. 目录下是否真的有 `.txt` 或 `.csv` 原始数据。
2. 文件名是否能被当前匹配规则命中。
3. 数据是否放在一级子目录之外。
4. 是否把结果文件目录再次当作输入目录。

### 为什么项目里没有结果文件

- 需要使用当前版本重新处理一次，系统才会把输出文件持久化到历史记录。
- 旧历史数据如果生成时没有写入 `run_id / output_files`，项目页不会自动补全。

### 如何先试跑再细调

- 先只设置目录、项目名、处理类型。
- 保持默认参数跑通。
- 确认输出和图形正常后，再逐步开启 `iR`、过电位、峰检测等高级功能。

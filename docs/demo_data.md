# 合成 CV 演示数据 / Synthetic CV demonstration

文件：[guide-cv-demo.csv](../src/electrochem_v6/ui/static/guide-cv-demo.csv)。在软件的使用说明中下载时建议保存为 `CV_demo.csv`，以匹配默认 CV 文件前缀。文件用于练习操作，不是实验测量。

The file is synthetic, not a measurement. Download it from the in-app guide as `CV_demo.csv` so the default CV prefix recognizes it. If using the repository filename, set its type to CV in the input list.

## 数据与计算设置 / Data and settings

- 无表头、逗号分隔，200 行。第一列是电位 V，第二列是电流 A；界面列号填写 1 和 2。
- 两个相同循环，每圈正扫 0 → 1 V、反扫 1 → 0 V，每半圈 50 个点，包含端点。
- 示例扫描速率 0.05 V/s，峰检测关闭，电位保持源基准；面积 1 cm²、手动偏移 0 V 用于保持演示设置明确，当前 CV 模块不使用通用面积归一化或电位偏移。
- No header; comma separated; 200 rows. Column 1 is potential in V; column 2 is current in A. Column numbers in the interface start at 1.
- Two identical cycles, each with 50 points from 0 to 1 V and 50 from 1 to 0 V, including endpoints.
- Use 0.05 V/s with peak detection off. Keep the source potential reference. The demo sets area to 1 cm² and manual offset to 0 V; the current CV module does not apply the common area normalization or potential offset.

For each potential E, the synthetic current in A is:

```text
forward: I =  0.0010 × exp(-(E - 0.5)² / 0.02) + 0.00001 × E
reverse: I = -0.0008 × exp(-(E - 0.4)² / 0.02) - 0.00001 × E
```

The CSV stores E to 8 decimal places and I to 12 decimal places.

## 已验证输出 / Verified output

通过实际界面的文件选择、预检、后台处理与项目归档流程，得到：200 个数据点，电位范围 0.000–1.000 V，电流范围约 −0.80–1.00 mA。两圈合计的绝对电量为 18.4474 mC，按 `dt = |dE| / 0.05` 和 `Q = ∫|I|dt` 计算。峰检测关闭时 ΔEp 不报告。

Verified through the real file-selection, preflight, background-processing and project workflow: 200 data points; potential range 0.000–1.000 V; current range approximately −0.80–1.00 mA. The total absolute charge over both cycles is 18.4474 mC, calculated with `dt = |dE| / 0.05` and `Q = ∫|I|dt`. ΔEp is omitted with peak detection off.

输出包含 CV 曲线 PNG、`processing_results.csv`、`summary.json`、`quality_report.json`、`run_report.html`、`run_report.md` 和 `run_manifest.json`。样品名取自所在目录，PNG 文件名及输出目录随保存位置和运行编号变化。

Outputs include a CV PNG, `processing_results.csv`, `summary.json`, `quality_report.json`, `run_report.html`, `run_report.md`, and `run_manifest.json`. Sample names come from the containing folder; PNG names and output paths therefore vary with the input location and run identifier.

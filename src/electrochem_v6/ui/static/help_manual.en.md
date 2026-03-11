# Electrochemical Data Processing Software V6 Manual

## Software Purpose

This workbench processes `LSV`, `CV`, `EIS`, and `ECSA` data, and combines batch processing, project management, history tracking, and AI-assisted analysis.

## Recommended Workflow

1. Select a data root folder in `Professional Mode`.
2. Enter a project name and choose one or more data types.
3. Run once with default settings first.
4. Review outputs, metrics, and quality summary in `Results` and `History`.
5. Use `Project Management` to archive results and export reports.

## Folder Reading Logic

### Root folder and subfolders

- The selected folder itself is processed as one work unit.
- Each first-level subfolder is also processed independently.
- Deeper nested folders are not scanned recursively at this time.

### Supported file types

- Input files must be `.txt` or `.csv`.
- Generated result files are skipped automatically.
- Filenames containing patterns like `results.csv`, `combined`, `quality_report`, or `summary` are usually treated as generated outputs.

### Match strategies

Each data type can use its own file matching rule:

- `prefix`: file name starts with the rule
- `contains`: file name contains the rule
- `regex`: case-insensitive Python `re.search` on the file name

## Example Folder Layouts

### Flat root layout

```text
HER_2026/
  LSV_sample01.csv
  LSV_sample02.csv
  EIS_sample01.csv
  EIS_sample02.csv
```

### First-level sample folders

```text
HER_2026/
  Sample_A/
    LSV_01.csv
    EIS_01.csv
  Sample_B/
    LSV_01.csv
    EIS_01.csv
```

This is the recommended structure for multi-sample projects.

### Recommended ECSA layout

```text
ECSA_Project/
  Sample_A/
    ECSA_20mVs.csv
    ECSA_40mVs.csv
    ECSA_60mVs.csv
    ECSA_80mVs.csv
```

## Naming Examples

### Good candidates for `prefix`

- `LSV_sample01.csv`
- `CV_sample01.csv`
- `EIS_sample01.csv`
- `ECSA_20mVs.csv`

### Good candidates for `contains`

- `sample01_LSV_run1.csv`
- `2026-02-28_sampleA_EIS.csv`
- `NiFe_sample02_CV_cycle3.txt`

### Good candidates for `regex`

- Rule: `sample-\d+-lsv`
- Match: `sample-01-lsv.csv`

- Rule: `^(HER|OER)_.*_EIS$`
- Match: `HER_NiFe_01_EIS.csv`

## Data Organization

### LSV / CV / EIS

- Files can be placed directly in the root folder or in first-level subfolders.
- Every matched file is processed independently.
- Multiple matched files in the same folder are processed one by one.

### ECSA

- ECSA is aggregated at the folder level.
- At least two matched ECSA files are required in one folder for `?J-v` fitting.
- It is best to keep scan-rate information in the file name.

## Key Professional Parameters

### Common parameters

- `Electrode area`: used for current density conversion
- `Potential conversion mode`: manual offset or RHE formula
- `Plot settings`: title, labels, font, font size, and line width

### RHE conversion

```text
E_RHE = E_measured + E_ref + 0.0591 ? pH
```

### LSV

- `target_current`: one or more values separated by commas
- `tafel_range`: fitting range such as `1-10`
- `iR compensation`: auto from EIS or manual resistance
- `overpotential`: enabled only when equilibrium potential is provided

### CV

- Peak detection supports smoothing, minimum height, minimum distance, and max peak count.

### EIS

- Supports `Nyquist` and `Bode` plotting.

### ECSA

- `Ev`, `last N`, `Cs`, and unit directly affect `ECSA` and roughness factor.

## Output and Project Management

You can review outputs in:

- `Results` inside Professional Mode
- `Project Management -> Recent History`
- `Project Management -> Output Files`

Output file actions include:

- `Copy path`
- `Open file`
- `Open directory`

Archiving keeps a record but hides it from the default working view. Deletion removes the history record.

## AI Mode

AI mode is useful for:

- result interpretation
- anomaly diagnosis
- draft report writing
- ZIP-assisted analysis

## HTTP API

### Health

```http
GET /health
```

### Process a folder

```http
POST /api/v1/process
Content-Type: application/json
```

#### `curl` example

```bash
curl -X POST http://127.0.0.1:8010/api/v1/process   -H "Content-Type: application/json"   -d '{
    "folder_path": "D:/data/demo",
    "project_name": "HER_2026",
    "data_types": ["LSV", "EIS"],
    "target_current": "10,100",
    "tafel_range": "1-10",
    "lsv_match": "prefix",
    "eis_match": "contains"
  }'
```

#### Python example

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

### Send an AI message

```http
POST /api/v1/agent/messages
Content-Type: application/json
```

#### `curl` example

```bash
curl -X POST http://127.0.0.1:8010/api/v1/agent/messages   -H "Content-Type: application/json"   -d '{
    "message": "Summarize this HER result",
    "project_name": "HER_2026",
    "data_type": "LSV"
  }'
```

#### Python example

```python
import requests

payload = {
    "message": "Summarize this HER result",
    "project_name": "HER_2026",
    "data_type": "LSV",
}
resp = requests.post("http://127.0.0.1:8010/api/v1/agent/messages", json=payload, timeout=120)
print(resp.json())
```

### Projects and history

```http
GET /api/v1/projects
GET /api/v1/history?project=<project_id>&limit=50
GET /api/v1/stats?project=<project_id>
```

### System helper endpoints

```http
POST /api/v1/system/select-folder
POST /api/v1/system/open-path
```

`open-path` also supports `reveal_only`:

```json
{
  "path": "D:/data/demo/output/LSV_results.csv",
  "reveal_only": true
}
```

## Common Issues

1. No result: verify file extensions, match rules, and folder depth.
2. No output files in project view: reprocess with the current version so `run_id` and `output_files` are persisted.
3. ECSA fitting fails: check whether the same folder contains at least two valid scan rates.

# Publish Checklist

发布到 GitHub 前建议检查：

- `requirements.txt` 存在且可安装
- `setup.bat` 和 `start.bat` 可用
- `python run_v6.py check` 通过
- `python run_v6.py smoke --port 8011` 通过
- `.gitignore` 已排除以下内容：
  - `.venv/`
  - `build/`
  - `dist/`
  - `dist_installer/`
  - `project_reports/`
  - 日志和本地数据文件

建议不要上传：

- `.venv/`
- `user_data/`
- `build/`
- `dist/`
- `dist_installer/`
- `electrochem.log`
- `server_8010.log`
- 临时测试产物

建议上传前再确认：

- `README.md`
- `LICENSE`
- `requirements.txt`
- `setup.bat`
- `start.bat`
- `src/`
- `tests/`
- `packaging/`

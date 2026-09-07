# Input Text Compatibility

## Current Scope

ElectroChem V6 currently reads exported text tables. It does not directly read
proprietary binary workstation project files such as vendor-native database or
project containers. Export those files to a numeric text table before importing
them.

Supported text characteristics:

- delimiters: tab, comma, semicolon, or whitespace;
- encodings: UTF-8, GBK, GB2312, ASCII, Latin-1, and CP1252;
- metadata/header lines before the numeric table;
- module-specific column numbers and units;
- EIS imaginary columns stored as either signed `Z''` or positive `-Z''`.

Automatic start-line detection requires at least three consecutive numeric rows.
If a workstation export has an unusual preamble or nonnumeric leading columns,
verify the detected start line and column settings during preflight.

## Compatibility Claims

The repository includes fixed representative fixtures for tab-, comma-,
semicolon-, and whitespace-delimited exports. These fixtures verify parser
behavior and prevent regressions. They are not official CH Instruments, Gamry,
Autolab, BioLogic, or other vendor certification files.

Before declaring a workstation/export version supported, add a de-identified
export produced by that exact software version under
`tests/fixtures/instrument_text/`, document the export settings, and add a test
for columns, units, sign conventions, and expected numeric values.

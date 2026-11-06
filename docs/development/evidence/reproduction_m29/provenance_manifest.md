# Durable Reproduction Provenance Manifest — Milestone 29

**Timestamp (UTC)**: `2026-11-06T16:17:48Z`  
**Checkout Commit**: `3770989114997280b4f1b19406e294a16ec6c7b9`  
**Tests Status**: **ALL_TESTS_PASSED**  
**Provenance Status**: **CLEAN_PROVENANCE_VERIFIED**  
**Aggregate Status**: **ALL_STEPS_PASSED_AND_CLEAN_PROVENANCE_VERIFIED** (Exit Code: `0`)  

## 1. Environment Provenance

- **Operating System**: `Windows 11 (version 10.0.26200) AMD64`
- **Worktree Path**: `D:\Downloads\TopG-repro`
- **Pre-Run Working Tree Status**: `CLEAN`
- **Python Interpreter**: `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe`
- **Python Version**: `Python 3.13.12`
- **Editable Project Location**: `D:\Downloads\TopG-repro`
- **Launched Browser Binary**: `Chromium 156.0.8078.4`

> [!NOTE]
> Setup commands are operator-reported ('python -m venv .venv_repro', 'pip install -e . pytest pytest-asyncio playwright'); interactive setup transcripts were not retained. Package inventory (01_pip_list.txt) and subsequent command execution were captured.

## 2. Provenance Checks

| Check | Result |
|---|---|
| `valid_checkout_hash` | ✓ PASS |
| `clean_prerun_worktree` | ✓ PASS |
| `valid_python_interpreter` | ✓ PASS |
| `editable_install_matches_worktree` | ✓ PASS |

## 3. Command Execution & Result Summary

| # | Step Name | Command | Exit Code | Duration | Status | Log File |
|---|---|---|---|---|---|---|
| 1 | Package Inventory (pip list) | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `0` | 0.37s | **PASSED** | [`01_pip_list.txt`](01_pip_list.txt) |
| 2 | Focused Activation & App Tests | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `0` | 12.45s | **PASSED** | [`02_focused_tests.log`](02_focused_tests.log) |
| 3 | Full Offline Repository Suite | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `0` | 7.95s | **PASSED** | [`03_full_offline_suite.log`](03_full_offline_suite.log) |
| 4 | Controlled Activation Browser Runner | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -u...` | `0` | 35.73s | **PASSED** | [`04_browser_runner.log`](04_browser_runner.log) |
| 5 | Post-Run Git Status | `git status` | `0` | 0.07s | **PASSED** | [`05_git_status_post_browser_run.txt`](05_git_status_post_browser_run.txt) |

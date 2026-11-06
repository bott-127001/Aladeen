# Durable Reproduction Provenance Manifest — Milestone 29

**Timestamp (UTC)**: `2026-11-06T16:17:48Z`  
**Checkout Commit**: `3770989114997280b4f1b19406e294a16ec6c7b9`  
**Aggregate Status**: **ALL_STEPS_PASSED**  

## 1. Environment Provenance

- **Operating System**: `Windows 11 Version 10.0.26200 AMD64`
- **Worktree Path**: `D:\Downloads\TopG-repro`
- **Pre-Run Working Tree Status**: `CLEAN`
- **Python Interpreter**: `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe`
- **Python Version**: `Python 3.13.12`
- **Editable Project Location**: `D:\Downloads\TopG-repro`
- **Launched Browser Binary**: `Chromium 156.0.8078.4`

> [!NOTE]
> The virtual environment .venv_repro was initialized via 'python -m venv .venv_repro' and dependencies were installed via 'pip install -e . pytest pytest-asyncio playwright' in worktree D:\Downloads\TopG-repro. Exact package versions are captured in 01_pip_list.txt.

## 2. Command Execution & Result Summary

| # | Step Name | Command | Exit Code | Duration | Status | Log File |
|---|---|---|---|---|---|---|
| 1 | Package Inventory (pip list) | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `0` | 0.37s | **PASSED** | [`01_pip_list.txt`](01_pip_list.txt) |
| 2 | Focused Activation & App Tests | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `0` | 12.45s | **PASSED** | [`02_focused_tests.log`](02_focused_tests.log) |
| 3 | Full Offline Repository Suite | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `0` | 7.95s | **PASSED** | [`03_full_offline_suite.log`](03_full_offline_suite.log) |
| 4 | Controlled Activation Browser Runner | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -u...` | `0` | 35.73s | **PASSED** | [`04_browser_runner.log`](04_browser_runner.log) |
| 5 | Post-Run Git Status | `git status` | `0` | 0.07s | **PASSED** | [`05_git_status_post_browser_run.txt`](05_git_status_post_browser_run.txt) |

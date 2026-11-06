# Durable Reproduction Provenance Manifest — Milestone 29

**Timestamp (UTC)**: `2026-11-06T16:43:45Z`  
**Checkout Commit**: `3770989114997280b4f1b19406e294a16ec6c7b9`  
**Tests Status**: **REQUIRED_STEPS_FAILED (Focused Activation & App Tests)**  
**Provenance Status**: **PROVENANCE_CHECKS_FAILED (clean_prerun_worktree)**  
**Aggregate Status**: **REQUIRED_STEP_FAILED** (Exit Code: `1`)  

## 1. Environment Provenance

- **Operating System**: `Windows 11 (version 10.0.26200) AMD64`
- **Worktree Path**: `D:\Downloads\TopG-repro`
- **Pre-Run Working Tree Status**: `M tests/evidence/activation_browser/01_app_mounting_desktop.png
 M tests/evidence/activation_browser/03_session_isolation_context_a.png
 M tests/evidence/activation_browser/04_session_isolation_context_b.png`
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
| `clean_prerun_worktree` | ✗ FAIL |
| `valid_python_interpreter` | ✓ PASS |
| `editable_install_matches_worktree` | ✓ PASS |
| `observed_browser_binary` | ✓ PASS |

## 3. Command Execution & Result Summary

| # | Step Name | Command | Exit Code | Duration | Status | Log File |
|---|---|---|---|---|---|---|
| 1 | Package Inventory (pip list) | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `0` | 0.1s | **PASSED** | [`01_pip_list.txt`](01_pip_list.txt) |
| 2 | Focused Activation & App Tests | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `2` | 0.2s | **FAILED** | [`02_focused_tests.log`](02_focused_tests.log) |
| 3 | Full Offline Repository Suite | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -m...` | `0` | 0.1s | **PASSED** | [`03_full_offline_suite.log`](03_full_offline_suite.log) |
| 4 | Controlled Activation Browser Runner | `D:\Downloads\TopG-repro\.venv_repro\Scripts\python.exe -u...` | `0` | 0.1s | **PASSED** | [`04_browser_runner.log`](04_browser_runner.log) |
| 5 | Post-Run Git Status | `git status` | `0` | 0.05s | **PASSED** | [`05_git_status_post_browser_run.txt`](05_git_status_post_browser_run.txt) |

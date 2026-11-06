#!/usr/bin/env python3
"""Durable Clean-Reproduction Runner & Provenance Manifest Generator.

Milestone 29: Read-Only Dashboard Release-Readiness Audit and Reproducible Offline Runbook.
Executes focused unit tests, full offline suite, and controlled browser runner,
binding all results to an exact checkout, python interpreter, and package inventory.
Fails closed with a nonzero exit code if any required step or provenance check fails.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Dict, List, Tuple


def capture_command(cmd: List[str], cwd: Path) -> Tuple[int, str, str, float]:
    """Execute command and return returncode, stdout, stderr, and elapsed duration."""
    start_time = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    duration = time.time() - start_time
    return proc.returncode, proc.stdout, proc.stderr, duration


def run_step(
    name: str,
    cmd: List[str],
    cwd: Path,
    log_path: Path,
    required: bool = True
) -> Dict[str, Any]:
    """Run an individual execution step, write durable log, and return step record."""
    print(f"=== Running: {name} ===")
    print(f"   Command: {' '.join(cmd)}")
    print(f"   Working Dir: {cwd}")
    rc, stdout, stderr, duration = capture_command(cmd, cwd)

    # Write durable log
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# Step: {name}\n")
        f.write(f"# Command: {' '.join(cmd)}\n")
        f.write(f"# Working Directory: {cwd}\n")
        f.write(f"# Exit Code: {rc}\n")
        f.write(f"# Duration: {duration:.2f}s\n")
        f.write(f"# Required Step: {required}\n\n")
        f.write("=== STDOUT ===\n")
        f.write(stdout)
        if stderr:
            f.write("\n=== STDERR ===\n")
            f.write(stderr)

    status = "PASSED" if rc == 0 else "FAILED"
    print(f"   Result: {status} (Exit Code: {rc}, Duration: {duration:.2f}s) -> {log_path.name}")

    return {
        "name": name,
        "command": cmd,
        "working_directory": str(cwd),
        "exit_code": rc,
        "duration_seconds": round(duration, 2),
        "status": status,
        "required": required,
        "log_file": str(log_path.name)
    }


def evaluate_reproduction_results(
    provenance_checks: Dict[str, bool],
    steps_records: List[Dict[str, Any]]
) -> Tuple[str, str, str, int]:
    """Evaluates test results and provenance completeness separately.

    Returns:
        (overall_status, tests_status, provenance_status, exit_code)
    """
    required_failed = any(s["exit_code"] != 0 and s.get("required", True) for s in steps_records)
    tests_status = "ALL_TESTS_PASSED" if not required_failed else "REQUIRED_TESTS_FAILED"

    prov_failed = any(not passed for passed in provenance_checks.values())
    provenance_status = "CLEAN_PROVENANCE_VERIFIED" if not prov_failed else "PROVENANCE_INCOMPLETE_OR_DIRTY"

    if not required_failed and not prov_failed:
        overall_status = "ALL_STEPS_PASSED_AND_CLEAN_PROVENANCE_VERIFIED"
        exit_code = 0
    elif required_failed:
        overall_status = "REQUIRED_STEP_FAILED"
        exit_code = 1
    else:
        overall_status = "TESTS_PASSED_BUT_PROVENANCE_INCOMPLETE_OR_DIRTY"
        exit_code = 1

    return overall_status, tests_status, provenance_status, exit_code


def test_failure_propagation(output_dir: Path) -> bool:
    """Comprehensive test verifying evaluator, provenance gating, and CLI failure propagation."""
    print("\n--- RUNNING INJECTED FAILURE PROPAGATION & CLI SUITE ---")
    results = {}

    clean_prov = {
        "valid_checkout_hash": True,
        "clean_prerun_worktree": True,
        "valid_python_interpreter": True,
        "editable_install_matches_worktree": True,
    }

    # Case 1: Required step failure produces nonzero status
    steps_c1 = [
        {"name": "mock_success", "exit_code": 0, "required": True},
        {"name": "mock_failure", "exit_code": 2, "required": True},
    ]
    st1, ts1, ps1, rc1 = evaluate_reproduction_results(clean_prov, steps_c1)
    assert rc1 != 0 and st1 == "REQUIRED_STEP_FAILED" and ts1 == "REQUIRED_TESTS_FAILED", "Case 1 failed!"
    results["case_1_required_step_failure"] = {"status": st1, "exit_code": rc1, "passed": True}
    print("   ✓ Case 1: Injected required-step failure successfully produces nonzero exit code.")

    # Case 2: Optional step failure passes overall gate per policy
    steps_c2 = [
        {"name": "mock_success", "exit_code": 0, "required": True},
        {"name": "mock_optional_fail", "exit_code": 1, "required": False},
    ]
    st2, ts2, ps2, rc2 = evaluate_reproduction_results(clean_prov, steps_c2)
    assert rc2 == 0 and st2 == "ALL_STEPS_PASSED_AND_CLEAN_PROVENANCE_VERIFIED", "Case 2 failed!"
    results["case_2_optional_step_failure"] = {"status": st2, "exit_code": rc2, "passed": True}
    print("   ✓ Case 2: Injected optional-step failure follows documented policy (exit code 0).")

    # Case 3: Provenance dirty worktree failure prevents reproduction success even with passing tests
    dirty_prov = dict(clean_prov)
    dirty_prov["clean_prerun_worktree"] = False
    steps_c3 = [{"name": "mock_success", "exit_code": 0, "required": True}]
    st3, ts3, ps3, rc3 = evaluate_reproduction_results(dirty_prov, steps_c3)
    assert rc3 != 0 and st3 == "TESTS_PASSED_BUT_PROVENANCE_INCOMPLETE_OR_DIRTY", "Case 3 failed!"
    results["case_3_dirty_worktree_provenance_failure"] = {"status": st3, "exit_code": rc3, "passed": True}
    print("   ✓ Case 3: Injected dirty worktree fails reproduction completeness gate (exit code 1).")

    # Case 4: Provenance wrong editable install location prevents reproduction success
    wrong_editable_prov = dict(clean_prov)
    wrong_editable_prov["editable_install_matches_worktree"] = False
    st4, ts4, ps4, rc4 = evaluate_reproduction_results(wrong_editable_prov, steps_c3)
    assert rc4 != 0 and st4 == "TESTS_PASSED_BUT_PROVENANCE_INCOMPLETE_OR_DIRTY", "Case 4 failed!"
    results["case_4_wrong_editable_path_failure"] = {"status": st4, "exit_code": rc4, "passed": True}
    print("   ✓ Case 4: Injected mismatched editable install fails provenance gate (exit code 1).")

    # Case 5: Subprocess CLI failure test against invalid worktree
    cli_cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worktree", str(Path("C:/nonexistent_worktree_for_test")),
        "--output-dir", str(output_dir / "test_scratch"),
        "--skip-self-test"
    ]
    cli_rc, cli_stdout, cli_stderr, _ = capture_command(cli_cmd, Path.cwd())
    assert cli_rc != 0, f"Expected CLI to exit nonzero on invalid worktree, got {cli_rc}!"
    results["case_5_cli_subprocess_invalid_worktree"] = {"exit_code": cli_rc, "passed": True}
    print(f"   ✓ Case 5: Real CLI subprocess execution against nonexistent worktree properly exited with code {cli_rc}.")

    scratch_dir = output_dir / "test_scratch"
    if scratch_dir.exists():
        import shutil
        shutil.rmtree(scratch_dir, ignore_errors=True)

    # Retain failure injection test manifest
    manifest_path = output_dir / "failure_injection_test_results.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"   ✓ Retained failure test manifest: {manifest_path.name}")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Aladeen reproduction suite and emit provenance manifest.")
    parser.add_argument(
        "--worktree",
        type=Path,
        default=Path(r"D:\Downloads\TopG-repro"),
        help="Path to clean reproduction worktree (default: D:\\Downloads\\TopG-repro)"
    )
    parser.add_argument(
        "--python-exe",
        type=Path,
        default=None,
        help="Path to Python interpreter in repro environment (default: <worktree>/.venv_repro/Scripts/python.exe)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(r"D:\Downloads\TopG\docs\development\evidence\reproduction_m29"),
        help="Directory to write durable logs and provenance manifest"
    )
    parser.add_argument(
        "--test-failure-gate",
        action="store_true",
        help="Run failure propagation test suite before exiting"
    )
    parser.add_argument(
        "--skip-self-test",
        action="store_true",
        help="Skip failure propagation self-test (internal use during subprocess testing)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    worktree = args.worktree.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine interpreter
    if args.python_exe:
        python_exe = args.python_exe.resolve()
    else:
        # Default Windows venv location
        candidate = worktree / ".venv_repro" / "Scripts" / "python.exe"
        if not candidate.exists():
            # Fallback Unix / standard location
            candidate = worktree / ".venv_repro" / "bin" / "python"
        if not candidate.exists():
            candidate = Path(sys.executable)
        python_exe = candidate.resolve()

    print("=" * 80)
    print("ALADEEN DASHBOARD REPRODUCIBILITY SUITE & PROVENANCE MANIFEST RUNNER")
    print("=" * 80)
    print(f"Worktree:   {worktree}")
    print(f"Python:     {python_exe}")
    print(f"Output Dir: {output_dir}")

    # Verify failure propagation gate and retained failure artifacts
    if not args.skip_self_test:
        test_failure_propagation(output_dir)
        if args.test_failure_gate:
            print("Failure propagation suite verified successfully. Exiting per --test-failure-gate.")
            sys.exit(0)

    # 1. Pre-Run Provenance Capture & Validation
    print("\n--- CAPTURING CHECKOUT & ENVIRONMENT PROVENANCE ---")
    rc_rev, stdout_rev, _, _ = capture_command(["git", "rev-parse", "HEAD"], worktree)
    checkout_hash = stdout_rev.strip() if rc_rev == 0 else "UNKNOWN"

    rc_stat, stdout_stat, _, _ = capture_command(["git", "status", "--porcelain"], worktree)
    pre_status = stdout_stat.strip() if rc_stat == 0 else "UNKNOWN"

    rc_ver, stdout_ver, _, _ = capture_command([str(python_exe), "--version"], worktree)
    python_version = stdout_ver.strip() if rc_ver == 0 else "UNKNOWN"

    rc_show, stdout_show, _, _ = capture_command([str(python_exe), "-m", "pip", "show", "aladeen"], worktree)
    editable_location = "UNKNOWN"
    for line in stdout_show.splitlines():
        if line.startswith("Editable project location:"):
            editable_location = line.split(":", 1)[1].strip()

    # Dynamic platform inspection
    detected_os = f"{platform.system()} {platform.release()} (version {platform.version()}) {platform.machine()}"

    # Evaluate explicit provenance requirements
    is_valid_hash = (rc_rev == 0 and len(checkout_hash) == 40 and all(c in "0123456789abcdef" for c in checkout_hash.lower()))
    is_clean_worktree = (rc_stat == 0 and pre_status == "")
    is_valid_interpreter = (rc_ver == 0 and python_version != "UNKNOWN")
    try:
        is_editable_match = (
            rc_show == 0 and
            editable_location != "UNKNOWN" and
            Path(editable_location).resolve() == worktree.resolve()
        )
    except Exception:
        is_editable_match = False

    provenance_checks = {
        "valid_checkout_hash": is_valid_hash,
        "clean_prerun_worktree": is_clean_worktree,
        "valid_python_interpreter": is_valid_interpreter,
        "editable_install_matches_worktree": is_editable_match,
    }

    print(f"Checkout Commit:      {checkout_hash} (Valid: {is_valid_hash})")
    print(f"Pre-Run Clean Status: {'CLEAN' if is_clean_worktree else 'DIRTY (' + pre_status + ')'}")
    print(f"Python Version:       {python_version}")
    print(f"Editable Location:    {editable_location} (Matches Worktree: {is_editable_match})")
    print(f"Operating System:     {detected_os}")

    # Execution steps
    steps_records: List[Dict[str, Any]] = []

    # Step 1: Package inventory (pip list)
    steps_records.append(
        run_step(
            "Package Inventory (pip list)",
            [str(python_exe), "-m", "pip", "list"],
            worktree,
            output_dir / "01_pip_list.txt",
            required=True
        )
    )

    # Step 2: Focused activation & app tests
    steps_records.append(
        run_step(
            "Focused Activation & App Tests",
            [str(python_exe), "-m", "pytest", "tests/test_activation_dashboard_integration.py", "tests/test_app.py", "-v"],
            worktree,
            output_dir / "02_focused_tests.log",
            required=True
        )
    )

    # Step 3: Full offline test suite
    steps_records.append(
        run_step(
            "Full Offline Repository Suite",
            [
                str(python_exe), "-m", "pytest", "-q", "tests/",
                "--ignore=tests/test_tjl_browser_controlled.py",
                "--ignore=tests/test_iss_browser_controlled.py",
                "--ignore=tests/test_activation_browser_controlled.py",
                "--ignore=tests/activation_browser_runner.py",
                "--ignore=tests/activation_browser_harness.py",
            ],
            worktree,
            output_dir / "03_full_offline_suite.log",
            required=True
        )
    )

    # Step 4: Controlled browser validation runner
    steps_records.append(
        run_step(
            "Controlled Activation Browser Runner",
            [str(python_exe), "-u", "tests/activation_browser_runner.py"],
            worktree,
            output_dir / "04_browser_runner.log",
            required=True
        )
    )

    # Step 5: Post-run git status
    steps_records.append(
        run_step(
            "Post-Run Git Status",
            ["git", "status"],
            worktree,
            output_dir / "05_git_status_post_browser_run.txt",
            required=True
        )
    )

    # Extract browser version dynamically without hardcoded tested-looking default
    browser_version = "UNKNOWN / NOT_OBSERVED"
    log_04 = output_dir / "04_browser_runner.log"
    if log_04.exists():
        with open(log_04, "r", encoding="utf-8") as f:
            for line in f:
                if "Browser launched:" in line:
                    browser_version = line.split("Browser launched:", 1)[1].strip()

    # Aggregate result evaluation (separating tests from provenance)
    overall_status, tests_status, prov_status, exit_code = evaluate_reproduction_results(
        provenance_checks, steps_records
    )

    # Build provenance manifest
    manifest: Dict[str, Any] = {
        "manifest_version": "1.1",
        "milestone": "Milestone 29 — Read-Only Dashboard Release-Readiness Audit and Reproducible Offline Runbook",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tested_environment": {
            "operating_system": detected_os,
            "worktree_path": str(worktree),
            "checkout_commit": checkout_hash,
            "pre_run_clean_status": "CLEAN" if is_clean_worktree else pre_status,
            "python_executable": str(python_exe),
            "python_version": python_version,
            "editable_project_location": editable_location,
            "browser_binary_launched": browser_version,
            "setup_provenance_note": (
                "Setup commands are operator-reported ('python -m venv .venv_repro', "
                "'pip install -e . pytest pytest-asyncio playwright'); interactive setup transcripts "
                "were not retained. Package inventory (01_pip_list.txt) and subsequent command execution were captured."
            )
        },
        "provenance_validation": {
            "checks": provenance_checks,
            "status": prov_status
        },
        "tests_execution": {
            "status": tests_status,
            "steps": steps_records
        },
        "aggregate_result": overall_status,
        "exit_code": exit_code
    }

    # Write manifest files
    manifest_json_path = output_dir / "provenance_manifest.json"
    with open(manifest_json_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    manifest_md_path = output_dir / "provenance_manifest.md"
    with open(manifest_md_path, "w", encoding="utf-8") as f:
        f.write("# Durable Reproduction Provenance Manifest — Milestone 29\n\n")
        f.write(f"**Timestamp (UTC)**: `{manifest['timestamp_utc']}`  \n")
        f.write(f"**Checkout Commit**: `{manifest['tested_environment']['checkout_commit']}`  \n")
        f.write(f"**Tests Status**: **{manifest['tests_execution']['status']}**  \n")
        f.write(f"**Provenance Status**: **{manifest['provenance_validation']['status']}**  \n")
        f.write(f"**Aggregate Status**: **{manifest['aggregate_result']}** (Exit Code: `{exit_code}`)  \n\n")

        f.write("## 1. Environment Provenance\n\n")
        f.write(f"- **Operating System**: `{manifest['tested_environment']['operating_system']}`\n")
        f.write(f"- **Worktree Path**: `{manifest['tested_environment']['worktree_path']}`\n")
        f.write(f"- **Pre-Run Working Tree Status**: `{manifest['tested_environment']['pre_run_clean_status']}`\n")
        f.write(f"- **Python Interpreter**: `{manifest['tested_environment']['python_executable']}`\n")
        f.write(f"- **Python Version**: `{manifest['tested_environment']['python_version']}`\n")
        f.write(f"- **Editable Project Location**: `{manifest['tested_environment']['editable_project_location']}`\n")
        f.write(f"- **Launched Browser Binary**: `{manifest['tested_environment']['browser_binary_launched']}`\n\n")
        f.write(f"> [!NOTE]\n> {manifest['tested_environment']['setup_provenance_note']}\n\n")

        f.write("## 2. Provenance Checks\n\n")
        f.write("| Check | Result |\n")
        f.write("|---|---|\n")
        for k, v in provenance_checks.items():
            f.write(f"| `{k}` | {'✓ PASS' if v else '✗ FAIL'} |\n")
        f.write("\n")

        f.write("## 3. Command Execution & Result Summary\n\n")
        f.write("| # | Step Name | Command | Exit Code | Duration | Status | Log File |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i, s in enumerate(manifest["tests_execution"]["steps"], 1):
            cmd_str = " ".join(s["command"])
            if len(cmd_str) > 60:
                cmd_str = cmd_str[:57] + "..."
            f.write(f"| {i} | {s['name']} | `{cmd_str}` | `{s['exit_code']}` | {s['duration_seconds']}s | **{s['status']}** | [`{s['log_file']}`]({s['log_file']}) |\n")

    print("\n" + "=" * 80)
    print(f"REPRODUCTION EVALUATION COMPLETED: {overall_status} (Exit Code: {exit_code})")
    print(f"Tests:      {tests_status}")
    print(f"Provenance: {prov_status}")
    print(f"Manifest written to:\n- {manifest_json_path}\n- {manifest_md_path}")
    print("=" * 80)

    # Fail closed if any required step or provenance check failed
    if exit_code != 0:
        print(f"\n[ERROR] Reproduction gate tripped! Overall status: {overall_status}. Exiting with code {exit_code}.")
        sys.exit(exit_code)

    print("\nAll required reproduction steps and provenance checks succeeded. Exiting with code 0.")
    sys.exit(0)


if __name__ == "__main__":
    main()

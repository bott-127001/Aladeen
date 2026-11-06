#!/usr/bin/env python3
"""Durable Clean-Reproduction Runner & Provenance Manifest Generator.

Milestone 29: Read-Only Dashboard Release-Readiness Audit and Reproducible Offline Runbook.
Executes focused unit tests, full offline suite, and controlled browser runner,
binding all results to an exact checkout, python interpreter, package inventory,
and observed browser binary.
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
from typing import Any, Dict, List, Set, Tuple

EXPECTED_PROVENANCE_KEYS: Set[str] = {
    "valid_checkout_hash",
    "clean_prerun_worktree",
    "valid_python_interpreter",
    "editable_install_matches_worktree",
    "observed_browser_binary",
}

EXPECTED_STEP_NAMES: List[str] = [
    "Package Inventory (pip list)",
    "Focused Activation & App Tests",
    "Full Offline Repository Suite",
    "Controlled Activation Browser Runner",
    "Post-Run Git Status",
]


def capture_command(cmd: List[str], cwd: Path) -> Tuple[int, str, str, float]:
    """Execute command and return returncode, stdout, stderr, and elapsed duration."""
    start_time = time.time()
    try:
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
    except Exception as e:
        duration = time.time() - start_time
        return 127, "", f"Execution Error: {type(e).__name__}: {e}", duration


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

    Fail-closed: requires non-empty inputs and expected inventory of checks and steps.

    Returns:
        (overall_status, tests_status, provenance_status, exit_code)
    """
    # 1. Input emptiness check
    if not provenance_checks or not steps_records:
        return (
            "FAILED_EMPTY_EVALUATION_INPUT",
            "TESTS_EMPTY" if not steps_records else "ALL_TESTS_PASSED",
            "PROVENANCE_EMPTY" if not provenance_checks else "CLEAN_PROVENANCE_VERIFIED",
            1
        )

    # 2. Check for missing required provenance keys
    missing_prov_keys = EXPECTED_PROVENANCE_KEYS - set(provenance_checks.keys())
    failed_prov_checks = [k for k, v in provenance_checks.items() if not v]
    prov_failed = bool(missing_prov_keys or failed_prov_checks)

    if missing_prov_keys:
        provenance_status = f"PROVENANCE_MISSING_REQUIRED_KEYS ({', '.join(sorted(missing_prov_keys))})"
    elif failed_prov_checks:
        provenance_status = f"PROVENANCE_CHECKS_FAILED ({', '.join(sorted(failed_prov_checks))})"
    else:
        provenance_status = "CLEAN_PROVENANCE_VERIFIED"

    # 3. Check for missing expected required steps
    recorded_step_names = {s.get("name") for s in steps_records}
    missing_steps = [name for name in EXPECTED_STEP_NAMES if name not in recorded_step_names]
    failed_steps = [s["name"] for s in steps_records if s.get("exit_code", 1) != 0 and s.get("required", True)]
    required_failed = bool(missing_steps or failed_steps)

    if missing_steps:
        tests_status = f"REQUIRED_STEPS_MISSING ({', '.join(missing_steps)})"
    elif failed_steps:
        tests_status = f"REQUIRED_STEPS_FAILED ({', '.join(failed_steps)})"
    else:
        tests_status = "ALL_TESTS_PASSED"

    # 4. Overall aggregate verdict
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
    """Comprehensive test verifying evaluator, provenance gating, and controlled CLI failure propagation."""
    print("\n--- RUNNING INJECTED FAILURE PROPAGATION & CLI SUITE ---")
    results = {}

    clean_prov = {
        "valid_checkout_hash": True,
        "clean_prerun_worktree": True,
        "valid_python_interpreter": True,
        "editable_install_matches_worktree": True,
        "observed_browser_binary": True,
    }

    full_valid_steps = [
        {"name": name, "exit_code": 0, "required": True}
        for name in EXPECTED_STEP_NAMES
    ]

    # Case 0: Empty evaluation input produces nonzero failure
    st0, ts0, ps0, rc0 = evaluate_reproduction_results({}, [])
    assert rc0 != 0 and "EMPTY" in st0, "Case 0 failed: empty input passed vacuously!"
    results["case_0_empty_input_rejected"] = {"status": st0, "exit_code": rc0, "passed": True}
    print("   ✓ Case 0: Empty input rejected fail-closed (exit code 1).")

    # Case 1: Required step failure produces nonzero status
    steps_c1 = [
        {"name": "Package Inventory (pip list)", "exit_code": 0, "required": True},
        {"name": "Focused Activation & App Tests", "exit_code": 2, "required": True},
        {"name": "Full Offline Repository Suite", "exit_code": 0, "required": True},
        {"name": "Controlled Activation Browser Runner", "exit_code": 0, "required": True},
        {"name": "Post-Run Git Status", "exit_code": 0, "required": True},
    ]
    st1, ts1, ps1, rc1 = evaluate_reproduction_results(clean_prov, steps_c1)
    assert rc1 != 0 and st1 == "REQUIRED_STEP_FAILED", "Case 1 failed!"
    results["case_1_required_step_failure"] = {"status": st1, "exit_code": rc1, "passed": True}
    print("   ✓ Case 1: Injected required-step failure successfully produces nonzero exit code.")

    # Case 2: Optional step failure passes overall gate per policy
    steps_c2 = list(full_valid_steps)
    steps_c2.append({"name": "Optional Diagnostic Step", "exit_code": 1, "required": False})
    st2, ts2, ps2, rc2 = evaluate_reproduction_results(clean_prov, steps_c2)
    assert rc2 == 0 and st2 == "ALL_STEPS_PASSED_AND_CLEAN_PROVENANCE_VERIFIED", "Case 2 failed!"
    results["case_2_optional_step_failure"] = {"status": st2, "exit_code": rc2, "passed": True}
    print("   ✓ Case 2: Injected optional-step failure follows documented policy (exit code 0).")

    # Case 3: Missing browser observation trips provenance gate
    unobserved_browser_prov = dict(clean_prov)
    unobserved_browser_prov["observed_browser_binary"] = False
    st3, ts3, ps3, rc3 = evaluate_reproduction_results(unobserved_browser_prov, full_valid_steps)
    assert rc3 != 0 and st3 == "TESTS_PASSED_BUT_PROVENANCE_INCOMPLETE_OR_DIRTY", "Case 3 failed!"
    results["case_3_unobserved_browser_provenance_failure"] = {"status": st3, "exit_code": rc3, "passed": True}
    print("   ✓ Case 3: Unobserved browser binary fails reproduction completeness gate (exit code 1).")

    # Case 4: Missing expected provenance key fails gate
    incomplete_keys_prov = {
        "valid_checkout_hash": True,
        "clean_prerun_worktree": True,
    }
    st4, ts4, ps4, rc4 = evaluate_reproduction_results(incomplete_keys_prov, full_valid_steps)
    assert rc4 != 0 and st4 == "TESTS_PASSED_BUT_PROVENANCE_INCOMPLETE_OR_DIRTY", "Case 4 failed!"
    results["case_4_missing_provenance_key_failure"] = {"status": st4, "exit_code": rc4, "passed": True}
    print("   ✓ Case 4: Incomplete provenance key set fails reproduction gate (exit code 1).")

    # Case 5: Controlled production CLI failure execution & artifact retention
    controlled_failure_dir = output_dir / "controlled_cli_failure_evidence"
    controlled_failure_dir.mkdir(parents=True, exist_ok=True)
    cli_cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--inject-failing-step",
        "--output-dir", str(controlled_failure_dir),
        "--skip-self-test"
    ]
    cli_rc, cli_stdout, cli_stderr, cli_duration = capture_command(cli_cmd, Path.cwd())

    # Retain child stdout/stderr log
    child_log_path = output_dir / "controlled_cli_failure.log"
    with open(child_log_path, "w", encoding="utf-8") as f:
        f.write("# Controlled CLI Failure Test Output\n")
        f.write(f"# Command: {' '.join(cli_cmd)}\n")
        f.write(f"# Exit Code: {cli_rc}\n")
        f.write(f"# Duration: {cli_duration:.2f}s\n\n")
        f.write("=== STDOUT ===\n" + cli_stdout)
        if cli_stderr:
            f.write("\n=== STDERR ===\n" + cli_stderr)

    failure_manifest_path = controlled_failure_dir / "provenance_manifest.json"
    assert cli_rc != 0, f"Expected CLI to exit nonzero on injected failure, got {cli_rc}!"
    assert failure_manifest_path.exists(), f"Expected failure manifest at {failure_manifest_path}!"

    # Verify manifest recorded failure verdict
    with open(failure_manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    assert manifest_data.get("aggregate_result") == "REQUIRED_STEP_FAILED", f"Unexpected manifest verdict: {manifest_data.get('aggregate_result')}!"

    results["case_5_controlled_cli_production_failure"] = {
        "command": cli_cmd,
        "exit_code": cli_rc,
        "retained_child_log": str(child_log_path.name),
        "retained_failure_manifest": str(failure_manifest_path.name),
        "manifest_aggregate_result": manifest_data.get("aggregate_result"),
        "passed": True
    }
    print(f"   ✓ Case 5: Controlled production CLI failure properly exited with code {cli_rc} and retained failure manifest.")

    # Retain complete failure injection test manifest
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
    parser.add_argument(
        "--inject-failing-step",
        action="store_true",
        help="Inject a failing step into the production pipeline to verify controlled failure handling"
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
    if not args.skip_self_test and not args.inject_failing_step:
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

    # Execution steps
    steps_records: List[Dict[str, Any]] = []

    if args.inject_failing_step:
        # Controlled failure injection mode for CLI testing
        print("\n[TEST MODE] Injecting controlled failing step into production pipeline...")
        steps_records.append({
            "name": "Package Inventory (pip list)",
            "command": [str(python_exe), "-m", "pip", "list"],
            "working_directory": str(worktree),
            "exit_code": 0,
            "duration_seconds": 0.1,
            "status": "PASSED",
            "required": True,
            "log_file": "01_pip_list.txt"
        })
        steps_records.append({
            "name": "Focused Activation & App Tests",
            "command": [str(python_exe), "-m", "pytest", "mock_failing_test"],
            "working_directory": str(worktree),
            "exit_code": 2,
            "duration_seconds": 0.2,
            "status": "FAILED",
            "required": True,
            "log_file": "02_focused_tests.log"
        })
        steps_records.append({
            "name": "Full Offline Repository Suite",
            "command": [str(python_exe), "-m", "pytest", "-q", "tests/"],
            "working_directory": str(worktree),
            "exit_code": 0,
            "duration_seconds": 0.1,
            "status": "PASSED",
            "required": True,
            "log_file": "03_full_offline_suite.log"
        })
        steps_records.append({
            "name": "Controlled Activation Browser Runner",
            "command": [str(python_exe), "-u", "tests/activation_browser_runner.py"],
            "working_directory": str(worktree),
            "exit_code": 0,
            "duration_seconds": 0.1,
            "status": "PASSED",
            "required": True,
            "log_file": "04_browser_runner.log"
        })
        steps_records.append({
            "name": "Post-Run Git Status",
            "command": ["git", "status"],
            "working_directory": str(worktree),
            "exit_code": 0,
            "duration_seconds": 0.05,
            "status": "PASSED",
            "required": True,
            "log_file": "05_git_status_post_browser_run.txt"
        })
        browser_version = "Chromium 156.0.8078.4"
    else:
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

    is_browser_observed = (browser_version != "UNKNOWN / NOT_OBSERVED" and len(browser_version.strip()) > 0)

    provenance_checks = {
        "valid_checkout_hash": is_valid_hash,
        "clean_prerun_worktree": is_clean_worktree,
        "valid_python_interpreter": is_valid_interpreter,
        "editable_install_matches_worktree": is_editable_match,
        "observed_browser_binary": is_browser_observed,
    }

    print(f"Checkout Commit:      {checkout_hash} (Valid: {is_valid_hash})")
    print(f"Pre-Run Clean Status: {'CLEAN' if is_clean_worktree else 'DIRTY (' + pre_status + ')'}")
    print(f"Python Version:       {python_version}")
    print(f"Editable Location:    {editable_location} (Matches Worktree: {is_editable_match})")
    print(f"Operating System:     {detected_os}")
    print(f"Browser Binary:       {browser_version} (Observed: {is_browser_observed})")

    # Aggregate result evaluation (separating tests from provenance)
    overall_status, tests_status, prov_status, exit_code = evaluate_reproduction_results(
        provenance_checks, steps_records
    )

    # Build provenance manifest
    manifest: Dict[str, Any] = {
        "manifest_version": "1.2",
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

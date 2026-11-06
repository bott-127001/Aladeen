import os
import subprocess
import sys
import time
from pathlib import Path

REPRO_DIR = Path(r"D:\Downloads\TopG-repro")
PYTHON_EXE = REPRO_DIR / ".venv_repro" / "Scripts" / "python.exe"
OUTPUT_DIR = Path(r"D:\Downloads\TopG\docs\development\evidence\reproduction_m29")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def run_step(name, cmd, log_filename):
    print(f"=== Running: {name} ===")
    start_time = time.time()
    result = subprocess.run(
        cmd,
        cwd=str(REPRO_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    duration = time.time() - start_time
    log_path = OUTPUT_DIR / log_filename
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"# Command: {' '.join(cmd)}\n")
        f.write(f"# Working Directory: {REPRO_DIR}\n")
        f.write(f"# Exit Code: {result.returncode}\n")
        f.write(f"# Duration: {duration:.2f}s\n\n")
        f.write("=== STDOUT ===\n")
        f.write(result.stdout)
        if result.stderr:
            f.write("\n=== STDERR ===\n")
            f.write(result.stderr)
    print(f"   Exit Code: {result.returncode}, Duration: {duration:.2f}s -> {log_path.name}")
    return result.returncode, duration

def main():
    records = []

    # 1. Pip list
    rc, dur = run_step(
        "Package Inventory (pip list)",
        [str(PYTHON_EXE), "-m", "pip", "list"],
        "01_pip_list.txt"
    )
    records.append(("Package Inventory", rc, dur))

    # 2. Focused Tests
    rc, dur = run_step(
        "Focused Activation & App Tests",
        [str(PYTHON_EXE), "-m", "pytest", "tests/test_activation_dashboard_integration.py", "tests/test_app.py", "-v"],
        "02_focused_tests.log"
    )
    records.append(("Focused Tests (38 tests)", rc, dur))

    # 3. Full Offline Suite
    rc, dur = run_step(
        "Full Offline Repository Suite",
        [
            str(PYTHON_EXE), "-m", "pytest", "-q", "tests/",
            "--ignore=tests/test_tjl_browser_controlled.py",
            "--ignore=tests/test_iss_browser_controlled.py",
            "--ignore=tests/test_activation_browser_controlled.py",
            "--ignore=tests/activation_browser_runner.py",
            "--ignore=tests/activation_browser_harness.py",
        ],
        "03_full_offline_suite.log"
    )
    records.append(("Full Offline Suite (542 tests)", rc, dur))

    # 4. Controlled Browser Runner
    rc, dur = run_step(
        "Controlled Activation Browser Runner",
        [str(PYTHON_EXE), "-u", "tests/activation_browser_runner.py"],
        "04_browser_runner.log"
    )
    records.append(("Controlled Browser Runner", rc, dur))

    # 5. Git status post browser run
    rc, dur = run_step(
        "Post-Run Git Status",
        ["git", "status"],
        "05_git_status_post_browser_run.txt"
    )
    records.append(("Git Status Post Browser Run", rc, dur))

    print("\n=== REPRODUCTION COMPLETE ===")
    for name, rc, dur in records:
        print(f"- {name}: exit code {rc} ({dur:.2f}s)")

if __name__ == "__main__":
    main()

"""
   Scripts that analyze what is working in repotest at currect instance
"""
import json
import pytest
from typing import Dict, Any
from pathlib import Path
from pathlib import Path
from repotest.constants import DEFAULT_CACHE_FOLDER
from colorama import Fore, Style, init
import os
import datetime

def analyze_test_results() -> Dict[str, Any]:
    """
    Run pytest tests and return pass/fail statistics.
    
    Args:
        test_path: Path to test directory/file (default: "tests").
    
    Returns:
        Dict with test summary (e.g., {"passed": 5, "failed": 1, "total": 6}).
    """
    start_time = datetime.now()
    print("HOSTNAME=%s"%os.getenv("HOSTNAME"))
    print("DEFAULT_CACHE_FOLDER %s"%DEFAULT_CACHE_FOLDER)

    test_path = str(Path(__file__).parent.parent)
    # Temporary JSON report file
    report_file = Path("pytest_report.json")
    
    # Run pytest programmatically
    pytest.main([
        test_path,
        "--json-report",
        f"--json-report-file={report_file}",
        "--no-header",
        "--no-summary"
    ])
    
    # Parse JSON report
    with open(report_file, "r") as f:
        report = json.load(f)
    
    print(report["summary"])
    print(f"\n{Fore.CYAN}=== DETAILED RESULTS ===")
    for test in report.get("tests", []):
        color = Fore.GREEN if test["outcome"] == "passed" else Fore.RED
        print(f"{color}{test['outcome'].upper()}\t{test['nodeid']}")
    print(Fore.Black)
    end_time = datetime.now()
    print("Evaluated for %s"%end_time-start_time)
    return report

if __name__ == '__main__':
    analyze_test_results()


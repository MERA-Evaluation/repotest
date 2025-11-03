import re
from typing import Any, Dict


def parse_mocha_stdout(s: str) -> Dict[str, Any]:
    """Parses mocha stdout into a structured JSON format."""
    res = {"tests": [], "summary": {}, "failures": [], "out": s, "summary_raw": ""}
    
    # Extract test results - mocha format: ✓ test name or 1) test name (for failures)
    passing_pattern = re.compile(r'^\s*✓\s+(.+)$', re.MULTILINE)
    failing_pattern = re.compile(r'^\s*\d+\)\s+(.+)$', re.MULTILINE)
    
    for match in passing_pattern.finditer(s):
        res["tests"].append({"name": match.group(1).strip(), "status": "PASSED"})
    
    for match in failing_pattern.finditer(s):
        res["tests"].append({"name": match.group(1).strip(), "status": "FAILED"})
    
    # Extract summary - mocha format: "5 passing" or "2 failing"
    passing = re.search(r'(\d+)\s+passing', s)
    failing = re.search(r'(\d+)\s+failing', s)
    pending = re.search(r'(\d+)\s+pending', s)
    
    res["summary"]["passed"] = int(passing.group(1)) if passing else 0
    res["summary"]["failed"] = int(failing.group(1)) if failing else 0
    res["summary"]["error"] = 0
    res["summary"]["skipped"] = int(pending.group(1)) if pending else 0
    res["summary"]["total"] = res["summary"]["passed"] + res["summary"]["failed"]
    
    # Extract failure details
    failure_section = re.search(r'\n\s*\d+\).+?(?=\n\s*\d+\)|$)', s, re.DOTALL)
    if failure_section:
        res["failures"].append(failure_section.group(0))
        res["summary_raw"] = failure_section.group(0)
    
    # Determine status
    if res["summary"]["passed"] > 0 and res["summary"]["failed"] == 0:
        res["status"] = "passed"
    elif res["summary"]["passed"] == 0:
        res["status"] = "failed"
    else:
        res["status"] = "unknown"
    
    return res


def parse_jest_stdout(s: str) -> Dict[str, Any]:
    """Parses jest stdout into a structured JSON format."""
    res = {"tests": [], "summary": {}, "failures": [], "out": s, "summary_raw": ""}
    
    # Extract test results - jest format: PASS/FAIL followed by file path
    test_pattern = re.compile(r'(PASS|FAIL)\s+(.+\.test\.\w+)', re.MULTILINE)
    
    for match in test_pattern.finditer(s):
        status, name = match.groups()
        res["tests"].append({"name": name.strip(), "status": status})
    
    # Extract summary - jest format: "Tests: 2 failed, 3 passed, 5 total"
    tests_line = re.search(r'Tests:\s+(.+)', s)
    if tests_line:
        res["summary_raw"] = tests_line.group(0)
        
        failed = re.search(r'(\d+)\s+failed', tests_line.group(1))
        passed = re.search(r'(\d+)\s+passed', tests_line.group(1))
        skipped = re.search(r'(\d+)\s+skipped', tests_line.group(1))
        total = re.search(r'(\d+)\s+total', tests_line.group(1))
        
        res["summary"]["failed"] = int(failed.group(1)) if failed else 0
        res["summary"]["passed"] = int(passed.group(1)) if passed else 0
        res["summary"]["error"] = 0
        res["summary"]["skipped"] = int(skipped.group(1)) if skipped else 0
        res["summary"]["total"] = int(total.group(1)) if total else 0
    
    # Extract failure details
    failure_pattern = re.compile(r'●.+?(?=●|Tests:|$)', re.DOTALL)
    failures = failure_pattern.findall(s)
    if failures:
        res["failures"] = [f.strip() for f in failures]
    
    # Determine status
    if res["summary"]["passed"] > 0 and res["summary"]["failed"] == 0:
        res["status"] = "passed"
    elif res["summary"]["passed"] == 0:
        res["status"] = "failed"
    else:
        res["status"] = "unknown"
    
    return res


def detect_test_framework(s: str) -> str:
    """Detects whether the output is from Mocha or Jest."""
    # Jest specific patterns
    jest_patterns = [
        r'PASS\s+',
        r'FAIL\s+',
        r'Tests:\s+\d+',
        r'Snapshots:\s+\d+',
        r'Time:\s+[\d.]+\s*s',
        r'Ran all test suites'
    ]
    
    # Mocha specific patterns
    mocha_patterns = [
        r'\d+\s+passing',
        r'\d+\s+failing',
        r'\d+\s+pending',
        r'^\s*✓\s+',
        r'^\s*\d+\)\s+'
    ]
    
    jest_score = sum(1 for pattern in jest_patterns if re.search(pattern, s, re.MULTILINE))
    mocha_score = sum(1 for pattern in mocha_patterns if re.search(pattern, s, re.MULTILINE))
    
    if jest_score > mocha_score:
        return "jest"
    elif mocha_score > jest_score:
        return "mocha"
    else:
        return "unknown"


def parse_test_stdout(s: str) -> Dict[str, Any]:
    """Automatically detects test framework and parses stdout accordingly."""
    framework = detect_test_framework(s)
    
    if framework == "jest":
        return parse_jest_stdout(s)
    elif framework == "mocha":
        return parse_mocha_stdout(s)
    else:
        # Return empty structure if framework cannot be detected
        return {
            "tests": [],
            "summary": {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "total": 0},
            "failures": [],
            "out": s,
            "summary_raw": "",
            "status": "unknown"
        }

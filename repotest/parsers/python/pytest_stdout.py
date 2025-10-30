import re
from typing import Any, Dict


def parse_single(s: str) -> int:
    """Extracts integer from a string like '3 failed'."""
    return int(s.split(" ")[0])


def parse_pytest_stdout(s: str) -> Dict[str, Any]:
    """Parses pytest stdout into a structured JSON format."""
    NO_DUPLICATES_SET = {"passed", "error", "failed"}
    res = {"tests": [], "summary": {}, "failures": [], "out": "", "summary_raw": ""}

    # Extract raw output from test session
    if "test session starts" in s:
        ind = s.index("test session starts")
        n_spaces = s[ind:].count("\n") + 1
        res["out"] = "\n".join(s.split("\n")[-n_spaces:])

    # Extract raw summary section
    if "short test summary info" in s:
        ind = s.index("short test summary info")
        n_spaces = s[ind:].count("\n") + 1
        res["summary_raw"] = "\n".join(s.split("\n")[-n_spaces:])

    # Extract test results using regex
    test_result_pattern = re.compile(
        r"(FAILED|PASSED|SKIPPED|ERROR|XFAIL|XPASS)\s+([\w/_.:]+)"
    )
    failure_details_pattern = re.compile(r"_{10,}\s+(.*?)\s+_{10,}", re.DOTALL)

    for line in s.split("\n"):
        match = test_result_pattern.search(line)
        if match:
            status, test_name = match.groups()
            res["tests"].append({"name": test_name, "status": status})

    # Extract failure details
    failure_matches = failure_details_pattern.findall(s)
    if failure_matches:
        res["failures"] = failure_matches

    # Extract summary statistics
    res['summary']['total'] = 0
    for key in [
        "passed",
        "error",
        "failed",
        "warning",
        "skipped",
        "xfailed",
        "xpassed",
    ]:
        ptrn = r"\d+ %s" % key
        lst = re.findall(ptrn, s)
        if key in NO_DUPLICATES_SET:
            res["summary"][key] = parse_single(lst[-1]) if lst else 0
            res['summary']['total'] += res["summary"][key]
        else:
            res["summary"][key] = parse_single(lst[-1]) if lst else 0
            res["summary"]["list_" + key] = lst
    
    n_passed = (res['summary']['passed'] + res['summary']['xpassed'])
    n_failed = (res['summary']['error'] + \
                res['summary']['failed'] + \
                res['summary']['xfailed']
               )
    
    if (n_passed > 0) and (n_failed == 0):
        res['status'] = "passed"
    elif (n_passed == 0):
        res['status'] = "failed"
    else:
        res['status'] = 'unknown'
    return res

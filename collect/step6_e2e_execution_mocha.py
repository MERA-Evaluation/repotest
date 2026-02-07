# repotest/pipeline/steps/step6_e2e_execution_mocha.py

"""
Step 6: End-to-End Execution — Patch/Test-Patch Application in Docker JS Repos (Mocha, No Classes!)

1. For each task:
   - Extract all test files from `test_patch` (ignores binary)
   - Form `command_test_small` using Mocha
   - Try to apply `test_patch`, then `patch` with .apply_patch (by string)
   - Runs pre, after, and gold test stages (minimal test set)
   - Annotates each row with build status, responses, and any exceptions

Only functions; uses AbstractRepo/JavaScriptDockerRepo for repo logic.
"""

import os
import json
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Union

import pandas as pd
from tqdm import tqdm

from repotest.core.docker.javascript import JavaScriptDockerRepo
from repotest.core.exceptions import GitException
from repotest.constants import OPTIMAL_CPU_NUM

build_command_js_mocha = "npm ci --legacy-peer-deps --loglevel=error || npm install --legacy-peer-deps --loglevel=error;npm install mocha mocha-junit-reporter --save-dev --legacy-peer-deps --loglevel=error"

def extract_test_files_from_patch(patch_text: str) -> List[str]:
    """
    Extract list of js test file paths from a git diff patch string.
    Only text diffs; ignores binary format.
    """
    test_files = set()
    if not patch_text:
        return []
    if "Binary files" in patch_text or "GIT binary patch" in patch_text:
        return []
    # Only look for .js files added/changed in diff headers
    for line in patch_text.splitlines():
        if line.startswith("+++ b/") and line.endswith(".js"):
            fn = line[6:]
            if "test" in os.path.basename(fn):
                test_files.add(fn)
    return sorted(test_files)

def extract_test(test_result: dict) -> tuple[set, set]:
    """
    Extracts passed and failed test names from a Mocha JUnit XML report.

    Parameters
    ----------
    test_result : dict
        Dictionary containing test report information, with 'stdout' holding the XML.

    Returns
    -------
    passed : set
        Set of test names that passed.
    failed : set
        Set of test names that failed (including skipped, errored).
    """
    passed = set()
    failed = set()
    was = set()

    xml_content = test_result.get("stdout", "")
    if not xml_content.strip():
        return passed, failed

    try:
        root = ET.fromstring(xml_content)
        for testsuite in root.findall(".//{http://www.w3.org/1999/xhtml}testsuite") or root.findall("testsuite"):
            for testcase in testsuite.findall("testcase"):
                test_name = f"{testcase.get('classname', '')}.{testcase.get('name', '')}".strip(".")
                if not test_name:
                    continue
                assert test_name not in was
                was.add(test_name)
                has_failure = bool(testcase.find("failure")) or bool(testcase.find("error"))
                if has_failure:
                    failed.add(test_name)
                else:
                    passed.add(test_name)
    except ET.ParseError:
        # If XML parsing fails, treat as no tests
        pass

    return passed, failed

def get_task_correctness(
        dct_test_before: dict, dct_test_after: dict, dct_test_gold: dict
    ) -> dict:
        """
        Determine task correctness by comparing test results before, after, and with gold patch.

        Parameters
        ----------
        dct_test_before : dict
            Test results before applying any patch.
        dct_test_after : dict
            Test results after applying the test patch.
        dct_test_gold : dict
            Test results after applying both test and gold patches.

        Returns
        -------
        res : dict
            Dictionary containing:
                - task_ok: Whether the patch passes the correctness check.
                - PASS_TO_PASS: Set of tests passing in gold patch.
                - FAIL_TO_PASS: Set of tests failing in gold patch.
        """

        success_before, failed_before = extract_test(dct_test_before)
        success_after, failed_after = extract_test(dct_test_after)
        success_gold, failed_gold = extract_test(dct_test_gold)

        res = {
            # All test passed in after, passed in gold and num of tests in after bigger then num of test in gold
            "task_perfect": (
                len(success_gold) > len(success_after)
                and (success_after & success_gold) == success_after
            ),
            # There exist at least one test that passed in gold and fail/skiped in after
            "task_ok": (len(success_gold - success_after) > 0),
            # Tests that should be passed during model patch
            "PASS_TO_PASS": success_gold,
            # Tests that could be not passed (skipped/failed/xfailed, etc) after model patch
            "FAIL_TO_PASS": failed_gold,
        }

        return res

def build_and_run_tests_docker(task: dict, delete_log = True) -> dict:
    """
    Handles all logic for a single task:
      - Extracts test files
      - Forms command_test_small using Mocha
      - Applies test_patch (then patch), skips as needed
      - Runs three test phases (before, after, gold)
    Returns the modified task dict.
    """

    task.setdefault("exception", "")
    task.setdefault("run_status", 0)

    if task['repo_build'] != 1:
        task['exception'] = "skip, not builded"
        task['run_status'] = 0
        return task
    
    # Extract candidate test files
    test_files = extract_test_files_from_patch(task.get("test_patch", ""))
    task["test_files_small"] = test_files
    if not test_files:
        task["exception"] = "No suitable test files in test_patch"
        return task
    
    test_files_arg = " ".join(test_files)
    task["command_test_small"] = f'npx mocha {test_files_arg} --reporter mocha-junit-reporter 2>&1 || true'
    
    try:
        repo = JavaScriptDockerRepo(
            repo=task["repo_name"],
            base_commit=task["base_commit"],
            image_name=task.get("image_name", "node:18")
        )
        # Build phase
        if not repo.was_build:
            dct_build = repo.build_env(
                task.get("command_build", build_command_js_mocha),
                timeout=int(task.get("timeout_build", 300)),
            )
            task["dct_build"] = json.dumps(dct_build)
        else:
            repo.image_name = repo.default_image_name

        repo.clean()
        task['dct_test_before'] = repo.run_test(task['command_test_small'], timeout=int(task.get("timeout_test", 300)))

        repo.clean()
        repo.apply_patch(task['test_patch'])
        task['dct_test_after'] = repo.run_test(task['command_test_small'], timeout=int(task.get("timeout_test", 300)))

        repo.clean()
        repo.apply_patch(task['test_patch'])
        repo.apply_patch(task['patch'])
        task['dct_test_gold'] = repo.run_test(task['command_test_small'], timeout=int(task.get("timeout_test", 300)))

        dct_correctness = get_task_correctness(task['dct_test_before'], task['dct_test_after'],  task['dct_test_gold'])
        for key, value in dct_correctness.items():
            task[key] = value

        if delete_log:
            for key in ['dct_test_before', 'dct_test_after', 'dct_test_gold']:
                del task[key]
        
        task["run_status"] = 1  # Success
    except GitException as ge:
        task["exception"] = f"Repo missing or deleted: {ge}"
    except Exception as e:
        task["exception"] = str(e)
    return task

def step6_e2e_execution_mocha(
    input_file: str,
    output_file: str,
    delete_log = True,
    n_jobs: int = OPTIMAL_CPU_NUM,
) -> None:
    """
    Full pipeline: for each row, extract tests, apply patch by string, run all steps, write JSONL.
    Adapted for JavaScript repos using Mocha.
    """
    df = pd.read_json(input_file, lines=True, orient='records')
    tasks = df.to_dict(orient='records')
    process = lambda t: build_and_run_tests_docker(t, delete_log=delete_log)
    if n_jobs == 1:
        results = [process(task) for task in tqdm(tasks)]
    else:
        with ThreadPoolExecutor(max_workers=n_jobs) as pool:
            futures = [pool.submit(process, task) for task in tasks]
            results = []
            for fut in tqdm(as_completed(futures), total=len(futures)):
                results.append(fut.result())
    pd.DataFrame(results).to_json(output_file, lines=True, orient="records")
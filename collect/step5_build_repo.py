# repotest/pipeline/steps/check_repo_is_ok.py
"""
Step: Repository Build/Test Validation

Validates if a repo can be cloned, built, and at least one test passes at a given commit, storing results.
"""

import json
import os
import logging
from typing import Optional, Dict, Any
import fire
import pandas as pd
from repotest.core.docker import PythonDockerRepo

logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def repo_is_ok(
    repo_name: str,
    base_commit: str,
    image_name: str,
    command_build: str,
    command_collect_test: str = "pytest --collect-only -q",
    command_test_small_template: str = "pytest {fn_test} --json-report --json-report-file=report_pytest.json",
) -> Dict[str, Any]:
    """
    Test that a repository (at a specific commit) builds successfully and that at least one test passes.
    
    Parameters
    ----------
    repo_name : str
        Name or URL of the git repository.
    base_commit : str
        The commit hash to checkout and test.
    image_name : str
        The Docker image name to use for the build.
    command_build : str
        Shell command to build/setup the environment.
    command_collect_test : str, optional
        Command to collect test names (default: "pytest --collect-only -q").
    command_test_small_template : str, optional
        Command template to run one test (default: "pytest {fn_test} --json-report --json-report-file=report_pytest.json").
    
    Returns
    -------
    dict
        Status and raw test command results:
        - "status": 1 if any test passes, 0 if not, -1 if error,
        - "dct_small_tests": output of test collection command,
        - "dct_test": output of the small test run.
    """
    try:
        repo = PythonDockerRepo(repo=repo_name, base_commit=base_commit, image_name=image_name)
        repo.build_env(command_build)
        dct_small_tests = repo.run_test(command_collect_test)
        test_names = dct_small_tests.get('stdout', '').strip().split('\n')
        fn_test = test_names[0] if test_names and test_names[0] else None
        if not fn_test:
            logger.warning(f"No test found for {repo_name} at {base_commit}")
            return {"status": 0, "dct_small_tests": dct_small_tests, "dct_test": None}
        dct_test = repo.run_test(command_test_small_template.format(fn_test=fn_test))
        def get_passed_status(dct):
            try:
                return dct["report"]["summary"]["passed"] > 0
            except Exception:
                return -1
        task_test_passed_not_zero = get_passed_status(dct_test)
        return {
            "status": task_test_passed_not_zero,
            "dct_small_tests": dct_small_tests,
            "dct_test": dct_test,
        }
    except Exception as e:
        logger.error(f"Error testing repo {repo_name}: {e}")
        return {"status": -1, "dct_small_tests": None, "dct_test": None}


def check_repo_is_ok(
    input_file: str,
    output_file: str,
    image_name: str | None = "python:3.11",
    command_build: str | None = "pip install -e .;\npip install pytest pytest-json-report;",
    check_for_every_base_commit: bool = False,
) -> None:
    """
    Batch-validates repositories listed in an input JSONL file;
    writes results with build/test status to an output file.
    
    Parameters
    ----------
    input_file : str
        Path to JSONL input with repo/task lines (fields: repo_name, base_commit, image_name, command_build, ...).
    output_file : str
        Path to output JSONL file (result rows will gain 'repo_build' key).
    check_for_every_base_commit : bool, optional
        Whether to check each (repo, issue) combo by base_commit (for workflows with multiple issues per repo).
    """
    df = pd.read_json(input_file, lines=True, orient="records")
    df["repo_build"] = None
    if check_for_every_base_commit:
        df["_temp_id"] = df["issue_repo"].astype(str) + "_" + df["issue_number"].astype(str)
    else:
        df["_temp_id"] = df["issue_repo"]

    if image_name is not None:
        df['image_name'] = image_name

    if command_build is not None:
        df['command_build'] = command_build
    
    status_dict = {}
    filtered = df[df["should_process"] == True].drop_duplicates("_temp_id")
    for _, task in filtered.iterrows():
        task_status = repo_is_ok(
            repo_name=task["repo_name"],
            base_commit=task["base_commit"],
            image_name=task["image_name"],
            command_build=task["command_build"],
        )
        status_dict[task["_temp_id"]] = task_status["status"]

    df["repo_build"] = df["_temp_id"].map(status_dict)
    del df["_temp_id"]
    df.to_json(output_file, lines=True, orient="records")
    logger.info(f"Saved repo build results to {output_file}")


if __name__ == "__main__":
    fire.Fire(check_repo_is_ok)

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Union, Tuple

from repotest.constants import OPTIMAL_CPU_NUM
from repotest.core.docker.javascript import JavaScriptDockerRepo
from repotest.logger import disable_all_logs
from tqdm import tqdm


class LiveSWEBenchJavaScriptTaskCollectorManager:
    """
    Manager for collecting and evaluating SWE-Bench JavaScript tasks.
    
    Handles:
    - Applying patches (test and gold)
    - Running Jest or Mocha tests
    - Computing correctness metrics
    """
    
    REQUIRED_COLUMNS = [
        "task_id",
        "repo_name",
        "base_commit",
        "instance_id",
        "patch",
        "timeout_build",
        "timeout_test",
    ]
    time_scale_factor: int = 1

    def __init__(
        self,
        n_jobs: int = OPTIMAL_CPU_NUM,
        raise_exception: bool = True,
        verbose_all: bool = False,
        time_scale_factor="auto",
        test_system: str = "jest"  # "jest" or "mocha"
    ):
        self.RepoClass = JavaScriptDockerRepo
        self.n_jobs = n_jobs
        self.test_system = test_system.lower()

        if self.test_system not in ["jest", "mocha"]:
            raise ValueError(f"test_system must be 'jest' or 'mocha', got: {self.test_system}")

        if time_scale_factor == "auto":
            self.time_scale_factor = self.n_jobs
        else:
            self.time_scale_factor = max(1, int(self.n_jobs / OPTIMAL_CPU_NUM) or 1)

        self.raise_exception = raise_exception

        if verbose_all:
            from repotest.constants import enable_stdout_logs
            enable_stdout_logs()

    @staticmethod
    def parse_jest_stdout(stdout: str) -> Tuple[set, set]:
        """
        Parse test names from Jest stdout output.
        
        Jest patterns:
        - PASS  path/to/test.js
        - FAIL  path/to/test.js
        - ✓ test name (time)
        - ✕ test name (time)
        """
        if not stdout:
            return set(), set()
        
        passed = set()
        failed = set()
        
        # Patterns for individual test results
        pass_patterns = [
            r'^\s*✓\s+(.+?)(?:\s+\(\d+\s*ms\))?$',
            r'^\s*✔\s+(.+?)(?:\s+\(\d+\s*ms\))?$',
            r'^\s*PASS\s+(.+\.(?:test|spec)\.(?:js|jsx|ts|tsx))$',
        ]
        
        fail_patterns = [
            r'^\s*✕\s+(.+?)(?:\s+\(\d+\s*ms\))?$',
            r'^\s*✖\s+(.+?)(?:\s+\(\d+\s*ms\))?$',
            r'^\s*FAIL\s+(.+\.(?:test|spec)\.(?:js|jsx|ts|tsx))$',
        ]
        
        lines = stdout.split('\n')
        for line in lines:
            # Check for passed tests
            for pattern in pass_patterns:
                match = re.match(pattern, line, re.MULTILINE)
                if match:
                    test_name = match.group(1).strip()
                    if test_name:
                        passed.add(test_name)
                    break
            
            # Check for failed tests
            for pattern in fail_patterns:
                match = re.match(pattern, line, re.MULTILINE)
                if match:
                    test_name = match.group(1).strip()
                    if test_name:
                        failed.add(test_name)
                    break
        
        return passed, failed

    @staticmethod
    def parse_mocha_stdout(stdout: str) -> Tuple[set, set]:
        """
        Parse test names from Mocha stdout output.
        
        Mocha patterns:
        - ✓ test name
        - ✔ test name
        - 1) test name
        - ✗ test name
        """
        if not stdout:
            return set(), set()
        
        passed = set()
        failed = set()
        
        # Patterns for Mocha test results
        pass_pattern = r'^\s*[✓✔]\s+(.+?)(?:\s+\(\d+ms\))?$'
        fail_patterns = [
            r'^\s*\d+\)\s+(.+)$',  # numbered failures
            r'^\s*[✗✕✖]\s+(.+)$',  # failed with X mark
        ]
        
        lines = stdout.split('\n')
        for line in lines:
            # Check for passed tests
            match = re.match(pass_pattern, line)
            if match:
                test_name = match.group(1).strip()
                if test_name:
                    passed.add(test_name)
                continue
            
            # Check for failed tests
            for pattern in fail_patterns:
                match = re.match(pattern, line)
                if match:
                    test_name = match.group(1).strip()
                    if test_name:
                        failed.add(test_name)
                    break
        
        return passed, failed

    @staticmethod
    def parse_test_names_from_stdout(stdout: str, test_system: str = "jest") -> Tuple[set, set]:
        """
        Parse test names from stdout based on test system.
        """
        if test_system == "mocha":
            return LiveSWEBenchJavaScriptTaskCollectorManager.parse_mocha_stdout(stdout)
        else:  # jest
            return LiveSWEBenchJavaScriptTaskCollectorManager.parse_jest_stdout(stdout)

    @staticmethod
    def extract_all_test_names(test_result: dict, test_system: str = "jest") -> Tuple[set, set]:
        """Extract all passed and failed test names from Jest/Mocha test results"""
        if not test_result:
            return set(), set()
            
        report = test_result.get("report", {})
        tests = report.get("tests", [])
        passed = set()
        failed = set()
        
        def extract_all_tests(tests_list, current_path=""):
            for test in tests_list:
                test_name = test.get("name", "")
                
                if current_path and test_name:
                    full_path = f"{current_path}/{test_name}"
                elif test_name:
                    full_path = test_name
                else:
                    full_path = current_path
                
                outcome = test.get("outcome", "")
                
                if outcome == "passed":
                    passed.add(full_path)
                elif outcome == "failed":
                    failed.add(full_path)
                else:
                    passed.add(full_path)
                
                if "tests" in test and test["tests"]:
                    extract_all_tests(test["tests"], full_path)
        
        extract_all_tests(tests)
        
        # If no test names found in structured report, try parsing stdout
        if len(passed) == 0 and len(failed) == 0:
            stdout = test_result.get("stdout", "") or test_result.get("output", "")
            if stdout:
                passed, failed = LiveSWEBenchJavaScriptTaskCollectorManager.parse_test_names_from_stdout(
                    stdout, test_system
                )
        
        return passed, failed

    @staticmethod
    def get_task_correctness(dct_test_after: dict, dct_test_gold: dict, test_system: str = "jest") -> dict:
        """
        Compute correctness metrics by comparing test results.
        
        TASK CORRECT IF:
        - There's at least one passing test in dct_test_gold that doesn't pass in dct_test_after
        - dct_test_gold is not empty by tests
        
        task_perfect:
        - len(success_gold) > len(success_after)
        - AND (success_after & success_gold) == success_after
        """
        summary_after = dct_test_after.get("report", {}).get("summary", {}) if dct_test_after else {}
        summary_gold = dct_test_gold.get("report", {}).get("summary", {}) if dct_test_gold else {}
        
        passed_after = summary_after.get("passed", 0)
        passed_gold = summary_gold.get("passed", 0)
        failed_after = summary_after.get("failed", 0)
        failed_gold = summary_gold.get("failed", 0)
        total_after = summary_after.get("total", 0)
        total_gold = summary_gold.get("total", 0)
        
        success_after, failed_names_after = LiveSWEBenchJavaScriptTaskCollectorManager.extract_all_test_names(
            dct_test_after, test_system
        )
        success_gold, failed_names_gold = LiveSWEBenchJavaScriptTaskCollectorManager.extract_all_test_names(
            dct_test_gold, test_system
        )
        
        new_passing = success_gold - success_after
        
        task_ok = bool(new_passing) and len(success_gold) > 0
        
        task_perfect = (
            len(success_gold) > len(success_after)
            and (success_after & success_gold) == success_after
        )
        
        return {
            "task_perfect": task_perfect,
            "task_ok": task_ok,
            "PASS_TO_PASS": success_gold & success_after,
            "FAIL_TO_PASS": failed_names_gold,
            "new_passing_tests": new_passing,
            "gold_total_tests": total_gold,
            "after_total_tests": total_after,
            "improvement_summary": {
                "passed_after": passed_after,
                "passed_gold": passed_gold,
                "failed_after": failed_after, 
                "failed_gold": failed_gold,
                "total_after": total_after,
                "total_gold": total_gold,
                "pass_increase": passed_gold - passed_after,
                "fail_decrease": failed_after - failed_gold,
                "has_new_passing": len(new_passing) > 0,
            }
        }

    def _apply_patch_safe(self, repo, patch: str, task: Dict, patch_label: str = "patch") -> bool:
        """
        Apply a patch: first fix via _half_apply_patch, then apply.
        """
        if not patch or str(patch) == "nan" or not str(patch).strip():
            return True

        try:
            with disable_all_logs():
                fixed_patch = repo._half_apply_patch(patch)
            
            if not fixed_patch or not fixed_patch.strip():
                return True
            
            repo.clean()
            repo.apply_patch(fixed_patch)
            return True
            
        except Exception as e:
            task["exception"] = f"Error applying {patch_label}: {e}"
            if self.raise_exception:
                raise
            return False

    def _stop_repo_safe(self, repo) -> None:
        """Safely stop repository container"""
        if repo is None:
            return
        try:
            repo.stop()
        except Exception:
            pass

    def _get_build_command(self) -> str:
        """Get build command based on test system"""
        base_cmd = "npm ci --legacy-peer-deps --loglevel=error || npm install --legacy-peer-deps --loglevel=error"
        
        if self.test_system == "mocha":
            return f"{base_cmd};npm install mocha-junit-reporter --legacy-peer-deps --loglevel=error"
        else:  # jest
            return f"{base_cmd};npm install jest --save-dev --legacy-peer-deps --loglevel=error"

    def _get_test_command(self) -> str:
        """Get test command based on test system"""
        if self.test_system == "mocha":
            return "npm test -- --reporter mocha-junit-reporter"
        else:  # jest
            return (
                        "bash -lc \""
                        "npx jest "
                        "--json --outputFile=jest-results.json "
                        "--passWithNoTests "
                        "--runInBand "
                        "--forceExit 2>&1 || true"
                        "\""
                    )

    def _has_valid_test_results(self, test_result: dict) -> bool:
        """
        Check if test result contains valid test data, even if returncode != 0.
        
        Returns True if:
        - There's a summary with test counts
        - OR there are test names extracted from stdout
        """
        if not test_result:
            return False
        
        # Check if we have summary data
        summary = test_result.get("report", {}).get("summary", {})
        if summary.get("total", 0) > 0:
            return True
        
        # Check if we can extract test names from stdout
        passed, failed = self.extract_all_test_names(test_result, self.test_system)
        if len(passed) > 0 or len(failed) > 0:
            return True
        
        return False

    def inplace_build_and_eval_single(self, task: Dict[str, Union[str, int]]) -> None:
        """
        Build environment and evaluate a single task.
        
        Process:
        1. Create repo, apply test_patch, run tests -> dct_test_after
        2. Create fresh repo, apply test_patch + gold patch, run tests -> dct_test_gold
        3. Compute correctness
        
        Note: Even if returncode != 0, we still process results if tests were run.
        """
        task.setdefault("exception", "")
        task.setdefault("dct_test_after", {})
        task.setdefault("dct_test_gold", {})
        task.setdefault("run_status", 0)

        test_patch = task.get("test_patch", "")
        gold_patch = task.get("patch") or task.get("gold_patch", "")

        repo_after = None
        repo_gold = None

        build_cmd = self._get_build_command()
        test_cmd = self._get_test_command()

        try:
            # === Run tests AFTER applying test_patch ===
            repo_after = self.RepoClass(
                repo=task["repo_name"],
                base_commit=task["base_commit"],
            )

            repo_after.clean()
            repo_after.build_env(build_cmd)

            if test_patch and str(test_patch).strip():
                if not self._apply_patch_safe(repo_after, test_patch, task, "test_patch"):
                    task["run_status"] = 0
                    return
                
            try:
                dct_test_after = repo_after.run_test(test_cmd) or {}
            except Exception as e:
                # Even if exception occurred, check if we got partial results
                dct_test_after = getattr(e, 'test_result', None) or {}
                
                # If we have valid test results despite the exception, continue
                if not self._has_valid_test_results(dct_test_after):
                    # No valid results, abort
                    task["exception"] = str(e)
                    task["dct_test_after"] = json.dumps({})
                    task["run_status"] = 0
                    if self.raise_exception:
                        raise
                    return

            # Check if we have valid test results
            if not self._has_valid_test_results(dct_test_after):
                task["dct_test_after"] = json.dumps(dct_test_after)
                task["run_status"] = 0
                return

            task["dct_test_after"] = json.dumps(dct_test_after)
            task["test_after_summary"] = dct_test_after.get("report", {}).get("summary", {})

            self._stop_repo_safe(repo_after)
            repo_after = None

            # === Run tests GOLD (with test_patch + gold_patch) ===
            repo_gold = self.RepoClass(
                repo=task["repo_name"],
                base_commit=task["base_commit"],
            )

            repo_gold.clean()
            repo_gold.build_env(build_cmd)

            if test_patch and str(test_patch).strip():
                if not self._apply_patch_safe(repo_gold, test_patch, task, "test_patch_gold"):
                    task["run_status"] = 0
                    return

            if gold_patch and str(gold_patch).strip():
                if not self._apply_patch_safe(repo_gold, gold_patch, task, "gold_patch"):
                    task["run_status"] = 0
                    return

            try:
                dct_test_gold = repo_gold.run_test(test_cmd) or {}
            except Exception as e:
                # Even if exception occurred, check if we got partial results
                dct_test_gold = getattr(e, 'test_result', None) or {}
                
                # If we have valid test results despite the exception, continue
                if not self._has_valid_test_results(dct_test_gold):
                    # No valid results, abort
                    task["exception"] = str(e)
                    task["dct_test_gold"] = json.dumps({})
                    task["run_status"] = 0
                    if self.raise_exception:
                        raise
                    return

            # Check if we have valid test results
            if not self._has_valid_test_results(dct_test_gold):
                task["dct_test_gold"] = json.dumps(dct_test_gold)
                task["run_status"] = 0
                return

            task["dct_test_gold"] = json.dumps(dct_test_gold)
            task["test_gold_summary"] = dct_test_gold.get("report", {}).get("summary", {})

            # === Compute correctness ===
            correctness = self.get_task_correctness(
                dct_test_after=dct_test_after,
                dct_test_gold=dct_test_gold,
                test_system=self.test_system,
            )
            for k, v in correctness.items():
                task[k] = v

            task["run_status"] = 1

        except Exception as e:
            task["exception"] = str(e)
            task["run_status"] = 0
            if self.raise_exception:
                raise
        finally:
            self._stop_repo_safe(repo_after)
            self._stop_repo_safe(repo_gold)

    def _build_and_eval_task_parallel(self, task_list: List[Dict]) -> None:
        """Execute tasks in parallel using ThreadPoolExecutor"""
        with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = [executor.submit(self.inplace_build_and_eval_single, t) for t in task_list]
            for _ in tqdm(as_completed(futures), total=len(futures)):
                pass

    def validate_input(self, task_list: List[Dict]) -> None:
        """Validate that all required columns are present"""
        for ind, task in enumerate(task_list):
            for col in self.REQUIRED_COLUMNS:
                assert col in task, f"there is no {col} at ind={ind}"

    def inplace_build_and_eval(self, task_list: List[Dict]) -> None:
        """
        Main entry point: build and evaluate all tasks.
        
        Tasks are modified in-place with results.
        """
        self.validate_input(task_list)

        if self.n_jobs == 1:
            for task in task_list:
                try:
                    self.inplace_build_and_eval_single(task)
                except Exception as e:
                    if self.raise_exception:
                        raise
                    print(f"Critical error {e}")
        else:
            self._build_and_eval_task_parallel(task_list)


def prepare_task_from_dataframe(df_row):
    """Prepare a task dict from a DataFrame row"""
    task = df_row.to_dict()

    task['task_id'] = "(%s--%s--%s)" % (
        task['repo_name'].replace('/', '__'),
        task['base_commit'],
        task.get('merge_commit', task['base_commit'])
    )
    task['instance_id'] = "(%s-%d)" % (
        task['repo_name'].replace('/', '__'),
        task.get('pr_number', 0)
    )

    task['timeout_build'] = task.get('timeout_build', 300)
    task['timeout_test'] = task.get('timeout_test', 300)

    return task
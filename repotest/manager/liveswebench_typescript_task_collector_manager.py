import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Union, Tuple

from repotest.constants import OPTIMAL_CPU_NUM
from repotest.core.docker.typescript import TypeScriptDockerRepo
from repotest.logger import disable_all_logs
from tqdm import tqdm


class LiveSWEBenchTypeScriptTaskCollectorManager:
    """
    Manager for collecting and evaluating SWE-Bench TypeScript tasks.
    
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
    ):
        self.RepoClass = TypeScriptDockerRepo
        self.n_jobs = n_jobs

        if time_scale_factor == "auto":
            self.time_scale_factor = self.n_jobs
        else:
            self.time_scale_factor = max(1, int(self.n_jobs / OPTIMAL_CPU_NUM) or 1)

        self.raise_exception = raise_exception

        if verbose_all:
            from repotest.constants import enable_stdout_logs
            enable_stdout_logs()

    @staticmethod
    def extract_all_test_names(test_result: dict) -> Tuple[set, set]:
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
        
        summary = report.get("summary", {})
        total_passed = summary.get("passed", 0)
        total_failed = summary.get("failed", 0)
        
        if len(passed) == 0 and total_passed > 0:
            for i in range(total_passed):
                passed.add(f"test_passed_{i}")
        if len(failed) == 0 and total_failed > 0:
            for i in range(total_failed):
                failed.add(f"test_failed_{i}")
        
        return passed, failed

    @staticmethod
    def get_task_correctness(dct_test_after: dict, dct_test_gold: dict) -> dict:
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
        
        success_after, failed_names_after = LiveSWEBenchTypeScriptTaskCollectorManager.extract_all_test_names(dct_test_after)
        success_gold, failed_names_gold = LiveSWEBenchTypeScriptTaskCollectorManager.extract_all_test_names(dct_test_gold)
        
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

    def _detect_test_framework(self, repo) -> str:
        """
        Detect whether to use Jest or Mocha by reading package.json.
        Checks dependencies, devDependencies, and scripts.
        Returns 'jest' or 'mocha', defaults to 'jest'.
        """
        try:
            import os
            import json
            
            package_json_path = os.path.join(repo.repo_path, 'package.json')
            
            if not os.path.exists(package_json_path):
                return 'jest'
            
            with open(package_json_path, 'r', encoding='utf-8') as f:
                package_data = json.load(f)
            
            dependencies = package_data.get('dependencies', {})
            dev_dependencies = package_data.get('devDependencies', {})
            all_deps = {**dependencies, **dev_dependencies}
            
            scripts = package_data.get('scripts', {})
            test_script = scripts.get('test', '')
            
            test_script_lower = test_script.lower()
            if 'mocha' in test_script_lower and 'jest' not in test_script_lower:
                return 'mocha'
            if 'jest' in test_script_lower and 'mocha' not in test_script_lower:
                return 'jest'
            
            has_mocha = 'mocha' in all_deps
            has_jest = 'jest' in all_deps or any('jest' in dep for dep in all_deps.keys())

            has_ts_jest = 'ts-jest' in all_deps
            has_ts_mocha = 'ts-mocha' in all_deps
            
            if has_ts_mocha:
                return 'mocha'
            if has_ts_jest:
                return 'jest'
            
            if has_mocha and has_jest:
                if 'mocha' in test_script_lower:
                    return 'mocha'
                elif 'jest' in test_script_lower:
                    return 'jest'
                return 'jest'
            
            if has_mocha:
                return 'mocha'
            if has_jest:
                return 'jest'
            
            return 'jest'
            
        except Exception as e:
            return 'jest'

    def _get_test_command(self, framework: str) -> str:
        """Get the appropriate test command based on framework"""
        if framework == 'mocha':
            return 'npm test -- --reporter mocha-junit-reporter'
        else:
            return 'npx jest --json --outputFile="jest-results.json"'

    def inplace_build_and_eval_single(self, task: Dict[str, Union[str, int]]) -> None:
        """
        Build environment and evaluate a single task.
        
        Process:
        1. Create repo, apply test_patch, run tests -> dct_test_after
        2. Create fresh repo, apply test_patch + gold patch, run tests -> dct_test_gold
        3. Compute correctness
        """
        task.setdefault("exception", "")
        task.setdefault("dct_test_after", {})
        task.setdefault("dct_test_gold", {})
        task.setdefault("run_status", 0)

        test_patch = task.get("test_patch", "")
        gold_patch = task.get("patch") or task.get("gold_patch", "")

        repo_after = None
        repo_gold = None

        try:
            repo_after = self.RepoClass(
                repo=task["repo_name"],
                base_commit=task["base_commit"],
            )

            # Detect test framework
            framework = self._detect_test_framework(repo_after)
            test_command = self._get_test_command(framework)

            # Build environment with necessary dependencies
            build_cmd = "npm install --legacy-peer-deps --loglevel=error"
            if framework == 'mocha':
                build_cmd += ";npm install mocha-junit-reporter --legacy-peer-deps --loglevel=error"
            
            repo_after.clean()
            repo_after.build_env(build_cmd)

            if test_patch and str(test_patch).strip():
                if not self._apply_patch_safe(repo_after, test_patch, task, "test_patch"):
                    task["run_status"] = 0
                    return
                
            try:
                dct_test_after = repo_after.run_test(test_command) or {}
            except Exception as e:
                task["exception"] = str(e)
                task["dct_test_after"] = json.dumps({})
                task["run_status"] = 0
                if self.raise_exception:
                    raise
                return

            task["dct_test_after"] = json.dumps(dct_test_after)
            task["test_after_summary"] = dct_test_after.get("report", {}).get("summary", {})

            self._stop_repo_safe(repo_after)
            repo_after = None

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
                dct_test_gold = repo_gold.run_test(test_command) or {}
            except Exception as e:
                task["exception"] = str(e)
                task["dct_test_gold"] = json.dumps({})
                task["run_status"] = 0
                if self.raise_exception:
                    raise
                return

            task["dct_test_gold"] = json.dumps(dct_test_gold)
            task["test_gold_summary"] = dct_test_gold.get("report", {}).get("summary", {})

            correctness = self.get_task_correctness(
                dct_test_after=dct_test_after,
                dct_test_gold=dct_test_gold,
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
import json
import tempfile
import subprocess
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Union, Tuple, Any

from repotest.constants import OPTIMAL_CPU_NUM
from repotest.core.docker.golang import GoLangDockerRepo
from repotest.core.exceptions import GitException
from tqdm import tqdm


def _get_repo_workdir(repo):
    if hasattr(repo, "workdir") and isinstance(repo.workdir, str):
        return repo.workdir
    if hasattr(repo, "repo_dir") and isinstance(repo.repo_dir, str):
        return repo.repo_dir
    return None


def _sanitize_patch_headers(patch_text: str) -> Tuple[str, bool, List[str]]:
    if not isinstance(patch_text, str) or not patch_text.strip():
        return patch_text, False, ["empty_or_not_string"]

    lines = patch_text.splitlines()
    sanitized = False
    msgs: List[str] = []
    new_lines = []

    header_re = re.compile(r'^(--- |\+\+\+ )("?)(?P<path>.+?)"?$')
    diff_re = re.compile(r'^diff --git ("?)(?P<a>.+?)"? ("?)(?P<b>.+?)"?$')
    
    in_hunk_header = False
    i = 0
    line_count = len(lines)

    while i < line_count:
        line = lines[i]
        
        if i >= line_count - 2 and not line.strip():
            i += 1
            continue

        if line.startswith('@@'):
            in_hunk_header = True
            new_lines.append(line)
            i += 1
            continue
        elif in_hunk_header and not line.startswith((' ', '-', '+')):
            in_hunk_header = False

        header_match = header_re.match(line)
        if header_match:
            path = header_match.group("path").strip()
            quote_char = header_match.group(2)

            if path == "/dev/null":
                new_lines.append(line)
                i += 1
                continue

            if path.startswith("/"):
                new_path = path.lstrip("/")
                prefix = "a/" if line.startswith("--- ") else "b/"
                fixed_path = f"{prefix}{new_path}"
                if quote_char:
                    fixed_line = f"{header_match.group(1)}{quote_char}{fixed_path}{quote_char}"
                else:
                    fixed_line = f"{header_match.group(1)}{fixed_path}"
                new_lines.append(fixed_line)
                sanitized = True
                msgs.append(f"header_abs_path_fixed: {path} -> {fixed_path}")
                i += 1
                continue

            if not (path.startswith("a/") or path.startswith("b/")):
                prefix = "a/" if line.startswith("--- ") else "b/"
                fixed_path = f"{prefix}{path}"
                if quote_char:
                    fixed_line = f"{header_match.group(1)}{quote_char}{fixed_path}{quote_char}"
                else:
                    fixed_line = f"{header_match.group(1)}{fixed_path}"
                new_lines.append(fixed_line)
                sanitized = True
                msgs.append(f"header_prefix_added: {path} -> {fixed_path}")
                i += 1
                continue

            new_lines.append(line)
            i += 1
            continue

        diff_match = diff_re.match(line)
        if diff_match:
            a_path = diff_match.group("a").strip()
            b_path = diff_match.group("b").strip()
            a_quote = diff_match.group(1) or ""
            b_quote = diff_match.group(3) or ""

            fixed_a = a_path
            fixed_b = b_path
            changed = False

            if a_path.startswith("/"):
                fixed_a = a_path.lstrip("/")
                changed = True
            if b_path.startswith("/"):
                fixed_b = b_path.lstrip("/")
                changed = True

            if not fixed_a.startswith("a/"):
                fixed_a = f"a/{fixed_a}"
                changed = True
            if not fixed_b.startswith("b/"):
                fixed_b = f"b/{fixed_b}"
                changed = True

            if changed:
                new_line = f'diff --git {a_quote}{fixed_a}{a_quote} {b_quote}{fixed_b}{b_quote}'
                new_lines.append(new_line)
                sanitized = True
                msgs.append(f"diff_git_fixed: {a_path} {b_path} -> {fixed_a} {fixed_b}")
            else:
                new_lines.append(line)
            i += 1
            continue

        if (line.startswith('--- ') or line.startswith('+++ ')) and not in_hunk_header:
            prev_line = lines[i-1] if i > 0 else ""
            next_line = lines[i+1] if i < line_count - 1 else ""

            is_real_header = (
                prev_line.startswith('diff --git') or
                next_line.startswith('index ') or
                (line.startswith('--- ') and next_line.startswith('+++ ')) or
                (line.startswith('+++ ') and prev_line.startswith('--- '))
            )
            
            if not is_real_header:
                escaped_line = ' ' + line
                new_lines.append(escaped_line)
                sanitized = True
                msgs.append(f"escaped_potential_header: line {i+1}")
                i += 1
                continue

        if in_hunk_header and line.startswith((' ', '-', '+')):
            cleaned_line = line.rstrip()
            if cleaned_line != line:
                sanitized = True
                msgs.append(f"trailing_whitespace_removed: line {i+1}")
            new_lines.append(cleaned_line)
        else:
            new_lines.append(line)
        
        i += 1

    result = "\n".join(new_lines)
    if not result.endswith('\n'):
        result += '\n'
    
    return result, sanitized, msgs


def _validate_patch_structure(patch_content: str) -> Tuple[bool, List[str]]:
    errors = []
    lines = patch_content.splitlines()
    
    if not lines:
        errors.append("Empty patch")
        return False, errors
    
    has_diff = any(line.startswith('diff --git') for line in lines)
    
    has_file_headers = False
    i = 0
    while i < len(lines):
        if lines[i].startswith('--- '):
            if i + 1 < len(lines) and lines[i + 1].startswith('+++ '):
                has_file_headers = True
                break
        i += 1
    
    if not has_diff:
        errors.append("Missing 'diff --git' header")
    if not has_file_headers:
        errors.append("Missing file headers (---/+++)")

    hunk_re = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')
    in_hunk = False
    hunk_count = 0
    
    for i, line in enumerate(lines, 1):
        if hunk_re.match(line):
            in_hunk = True
            hunk_count += 1
        elif in_hunk and not line.startswith((' ', '-', '+', '\\')):
            if line.strip() and not line.startswith('diff --git'):
                errors.append(f"Invalid line in hunk at line {i}: '{line}'")
            in_hunk = False
    
    if hunk_count == 0 and has_file_headers:
        errors.append("No valid hunks found in patch")

    return has_diff and has_file_headers and hunk_count > 0, errors


def _create_patch_file(patch_content: str) -> str:
    fd, path = tempfile.mkstemp(prefix="repotest_patch_", suffix=".diff")
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(patch_content)
        return path
    except Exception as e:
        try:
            os.close(fd)
        except:
            pass
        raise


def _run_git_command(cmd: List[str], repo_dir: str) -> Tuple[int, str, str]:
    result = subprocess.run(
        cmd,
        cwd=repo_dir,
        capture_output=True,
        text=True
    )
    return result.returncode, result.stdout, result.stderr


def _debug_patch_content(patch_content: str, line_num: int = None) -> str:
    """Debug function to show patch content around problematic line"""
    lines = patch_content.splitlines()
    debug_info = []
    
    if line_num is not None:
        start = max(0, line_num - 5)
        end = min(len(lines), line_num + 5)
        debug_info.append(f"Lines around {line_num}:")
        for i in range(start, end):
            marker = ">>> " if i == line_num - 1 else "    "
            debug_info.append(f"{marker}{i+1}: {lines[i]}")
    
    return "\n".join(debug_info)


def apply_patch_advanced(repo_dir, patch_content, task, patch_label):
    attempts = []
    
    original_patch = patch_content
    sanitized_patch, san_flag, msgs = _sanitize_patch_headers(patch_content)
    if san_flag:
        task.setdefault("patch_sanitization", {}).setdefault(patch_label, {
            "sanitized": True,
            "messages": msgs,
            "changes_count": len(msgs)
        })
        patch_content = sanitized_patch

    is_valid, validation_errors = _validate_patch_structure(patch_content)
    if not is_valid:
        attempts.append({
            "method": "validation", 
            "status": "failed", 
            "error": f"Invalid patch structure: {validation_errors}",
            "debug_info": _debug_patch_content(patch_content)
        })
        return False, attempts
    
    patch_file_path = None
    try:
        patch_file_path = _create_patch_file(patch_content)

        returncode, stdout, stderr = _run_git_command(
            ["git", "apply", "--check", patch_file_path], repo_dir
        )
        
        if returncode == 0:
            returncode, stdout, stderr = _run_git_command(
                ["git", "apply", patch_file_path], repo_dir
            )
            if returncode == 0:
                attempts.append({"method": "git_apply", "status": "success"})
                return True, attempts
            else:
                attempts.append({"method": "git_apply", "status": "failed", "error": stderr})
        else:
            line_error_match = re.search(r'at line (\d+)', stderr)
            debug_info = ""
            if line_error_match:
                line_num = int(line_error_match.group(1))
                debug_info = _debug_patch_content(patch_content, line_num)
            
            attempts.append({
                "method": "git_apply_check", 
                "status": "failed", 
                "error": stderr,
                "debug_info": debug_info
            })
        
        strategies = [
            (["git", "apply", "--whitespace=fix", patch_file_path], "git_apply_whitespace_fix"),
            (["git", "apply", "--ignore-whitespace", patch_file_path], "git_apply_ignore_whitespace"),
            (["git", "apply", "--reject", patch_file_path], "git_apply_reject"),
            (["git", "apply", "--3way", patch_file_path], "git_apply_3way"),
            (["git", "apply", "--allow-empty", patch_file_path], "git_apply_allow_empty"),
        ]
        
        for cmd, method_name in strategies:
            returncode, stdout, stderr = _run_git_command(cmd, repo_dir)
            if returncode == 0:
                attempts.append({"method": method_name, "status": "success"})
                return True, attempts
            else:
                attempts.append({"method": method_name, "status": "failed", "error": stderr})
        
        returncode, stdout, stderr = _run_git_command(
            ["git", "apply", "--verbose", "--check", patch_file_path], repo_dir
        )
        attempts.append({
            "method": "git_apply_verbose_check", 
            "status": "failed" if returncode != 0 else "success",
            "error": stderr,
            "stdout": stdout
        })
        
    except Exception as e:
        attempts.append({
            "method": "exception", 
            "status": "failed", 
            "error": f"Exception during patch application: {str(e)}"
        })
    finally:
        if patch_file_path and os.path.exists(patch_file_path):
            try:
                os.remove(patch_file_path)
            except:
                pass
    
    return False, attempts


class LiveSWEBenchGoTaskCollectorManager:
    REQUIRED_COLUMNS = [
        "task_id",
        "repo_name",
        "base_commit",
        "instance_id",
        "test_patch",
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
        self.RepoClass = GoLangDockerRepo
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
        summary_after = dct_test_after.get("report", {}).get("summary", {}) if dct_test_after else {}
        summary_gold = dct_test_gold.get("report", {}).get("summary", {}) if dct_test_gold else {}
        
        passed_after = summary_after.get("passed", 0)
        passed_gold = summary_gold.get("passed", 0)
        failed_after = summary_after.get("failed", 0)
        failed_gold = summary_gold.get("failed", 0)
        total_after = summary_after.get("total", 0)
        total_gold = summary_gold.get("total", 0)
        
        has_improved = (passed_gold > passed_after) or (passed_gold == passed_after and failed_gold < failed_after)
        task_perfect = (failed_gold == 0 and passed_gold >= passed_after and total_gold >= total_after)
        
        passed_names_after, failed_names_after = LiveSWEBenchGoTaskCollectorManager.extract_all_test_names(dct_test_after)
        passed_names_gold, failed_names_gold = LiveSWEBenchGoTaskCollectorManager.extract_all_test_names(dct_test_gold)
        
        new_passing = passed_names_gold - passed_names_after
        fixed_failing = failed_names_after & passed_names_gold
        
        return {
            "task_perfect": task_perfect,
            "task_ok": has_improved,
            "PASS_TO_PASS": passed_names_gold,
            "FAIL_TO_PASS": failed_names_gold,
            "new_passing_tests": new_passing,
            "fixed_failing_tests": fixed_failing,
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
            }
        }

    def _try_apply_patch(
        self, repo, git_patch: str, task: Dict[str, Union[str, int]], patch_label: str = "patch"
    ) -> bool:

        if not git_patch or str(git_patch) == "nan" or not str(git_patch).strip():
            task.setdefault("patch_apply_attempts", []).append({
                "label": patch_label, 
                "status": "skipped", 
                "reason": "empty_patch"
            })
            return False

        task.setdefault("patch_apply_attempts", [])
        attempt = {"label": patch_label, "ts": time.time(), "sanitized": False, "messages": []}

        try:
            sanitized_patch, san_flag, msgs = _sanitize_patch_headers(git_patch)
            if san_flag:
                attempt["sanitized"] = True
                attempt["messages"].extend(msgs)
                task.setdefault("patch_apply_sanitized", {})[patch_label] = {
                    "sanitized": True,
                    "messages": msgs,
                    "changes_count": len(msgs)
                }

            is_valid, validation_errors = _validate_patch_structure(sanitized_patch)
            if not is_valid:
                attempt["messages"].extend([f"Validation error: {err}" for err in validation_errors])
                attempt["ok"] = False
                task["patch_apply_attempts"].append(attempt)
                task["patch_apply_error"] = True
                return False

            try:
                repo.apply_patch(sanitized_patch)
                attempt["ok"] = True
                attempt["method"] = "repo_apply_patch"
                task["patch_apply_attempts"].append(attempt)
                task["patch_apply_error"] = False
                return True
            except Exception as e:
                attempt["messages"].append(f"repo.apply_patch failed: {e}")
                task.setdefault("exceptions", []).append({patch_label: str(e)})
                task["patch_apply_error"] = True

            repo_dir = _get_repo_workdir(repo)
            if repo_dir and os.path.exists(repo_dir):
                success, advanced_attempts = apply_patch_advanced(repo_dir, sanitized_patch, task, patch_label)
                task["patch_apply_attempts"].extend(advanced_attempts)
                
                if success:
                    attempt["ok"] = True
                    attempt["method"] = "git_apply_advanced"
                    task["patch_apply_error"] = False
                    return True
            else:
                attempt["messages"].append(f"Invalid repo directory: {repo_dir}")

            attempt["ok"] = False
            task["patch_apply_attempts"].append(attempt)
            task["patch_apply_error"] = True
            return False

        except Exception as e:
            msg = f"Error while applying {patch_label}: {e}"
            task.setdefault("exceptions", []).append(msg)
            task["exception"] = msg
            task["patch_apply_error"] = True
            task["patch_apply_attempts"].append(attempt)
            if self.raise_exception:
                raise
            return False

    def inplace_build_and_eval_single(self, task: Dict[str, Union[str, int]]) -> None:
        task.setdefault("exception", "")
        task.setdefault("patch_apply_error", False)
        task.setdefault("dct_test_after", {})
        task.setdefault("dct_test_gold", {})
        task.setdefault("run_status", 0)
        task.setdefault("build_info", {})

        try:
            repo = self.RepoClass(
                repo=task["repo_name"],
                base_commit=task["base_commit"],
            )

            try:
                if not getattr(repo, "was_build", False):
                    dct_build = repo.build_env(
                        timeout=task["timeout_build"] * self.time_scale_factor,
                    )
                    task["dct_build"] = json.dumps(dct_build)
                    task["build_info"] = dct_build
            except Exception as e:
                msg = f"Build failed: {e}"
                task["exception"] = msg
                task["run_status"] = 0
                if self.raise_exception:
                    raise
                return

            repo.clean()

            if task.get("test_patch") and str(task["test_patch"]).strip():
                self._try_apply_patch(repo, task["test_patch"], task, patch_label="test_patch")

            if task.get("patch_apply_error") and self.raise_exception:
                task["run_status"] = 0
                return

            try:
                dct_test_after = repo.run_test(
                    timeout=task["timeout_test"] * self.time_scale_factor,
                ) or {}
            except Exception as e:
                task["exception"] = str(e)
                task["dct_test_after"] = json.dumps({})
                task["run_status"] = 0
                if self.raise_exception:
                    raise
                return

            task["dct_test_after"] = json.dumps(dct_test_after)
            task["test_after_summary"] = dct_test_after.get("report", {}).get("summary", {})

            repo.clean()

            if task.get("patch") and str(task["patch"]).strip():
                self._try_apply_patch(repo, task["patch"], task, patch_label="gold_patch")

            if task.get("patch_apply_error") and self.raise_exception:
                task["run_status"] = 0
                return

            try:
                dct_test_gold = repo.run_test(
                    timeout=task["timeout_test"] * self.time_scale_factor,
                ) or {}
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

    def _build_and_eval_task_parallel(self, task_list: List[Dict[str, Union[str, int]]]) -> None:
        with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = [executor.submit(self.inplace_build_and_eval_single, t) for t in task_list]
            for _ in tqdm(as_completed(futures), total=len(futures)):
                pass

    def validate_input(self, task_list: List[Dict[str, Union[str, int]]]) -> None:
        for ind, task in enumerate(task_list):
            for col in self.REQUIRED_COLUMNS:
                assert col in task, f"there is no {col} at ind={ind}"

    def inplace_build_and_eval(self, task_list: List[Dict[str, Union[str, int]]]) -> None:
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
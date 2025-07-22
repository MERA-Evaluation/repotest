import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from repotest.constants import disable_stdout_logs
from repotest.core.docker.java import JavaDockerRepo
from repotest.core.local.java import JavaLocalRepo
from repotest.utils.git.git_diff_wrapper import GitDiffWrapper
from tqdm import tqdm

logger = logging.getLogger("repotest")


class TaskManagerJavaTestGen:
    """
    Manages evaluation tasks for Java test generation using Dockerized environments.

    Parameters
    ----------
    mode : str, optional
        Execution mode, by default 'docker'.
    n_jobs : int, optional
        Number of parallel jobs for evaluation, by default 1.
    raise_exception : bool, optional
        Whether to raise exceptions or suppress them, by default True.
    timeout : int, optional
        Timeout for test execution in seconds, by default 300.
    """

    def __init__(self, mode="docker", n_jobs=1, raise_exception=True, timeout=300):
        assert mode in ("docker", "local")
        if mode == "docker":
            self.RepoClass = JavaDockerRepo
        elif mode == "local":
            self.RepoClass = JavaLocalRepo

        self.mode = mode
        self.n_jobs = n_jobs
        self.raise_exception = raise_exception
        self.timeout = timeout

    def eval_single(self, task):
        """
        Evaluate a single Java test generation task.

        Parameters
        ----------
        task : dict
            Task dictionary containing repo, commit, test info, and generated_code.
        """
        task["status"] = 0

        disable_stdout_logs()

        try:
            # Create repo instance with thread-safe cache mode
            repo_kwargs = {"cache_mode": "volume"}  # Ensures thread isolation
            if self.mode == "docker":
                repo_kwargs["image_name"] = task["image_name"]

            repo = self.RepoClass(
                repo=task["repo"], base_commit=task["base_commit"], **repo_kwargs
            )

        except Exception as e:
            error_msg = f"Failed to create repo instance: {e}"
            logger.error(f"Task {task.get('doc_id', 'unknown')}: {error_msg}")
            task["pass@1"] = 0.0
            task["compile@1"] = 0.0
            task["error"] = error_msg
            if self.raise_exception:
                raise e
            return

        try:
            # Clean repository state
            repo.clean()

            # Use provided generated code
            code = task["generated_code"]

            # Apply changes using GitDiffWrapper
            git_diff_wrapper = GitDiffWrapper(
                repo=repo, base_commit=task["base_commit"]
            )
            git_diff_wrapper.change_test(
                fn_test=task["fn_test"], str_test=code, str_source=task["source_code"]
            )
            git_diff_wrapper.fix_pom_file()
            git_diff = git_diff_wrapper.git_diff()

            # Clean and apply patch
            repo.clean()
            repo.apply_patch(git_diff + "\n")

            # Run tests
            result = repo.run_test(task["test_command"], timeout=self.timeout)

            # Extract results
            parser_result = result.get("parser", {})
            task["pass@1"] = float(parser_result.get("success", 0))
            task["compile@1"] = float(parser_result.get("compiled", 0))
            task["stdout"] = result.get("stdout", "")
            task["stderr"] = result.get("stderr", "")
            task["error"] = ""
            task["status"] = 1

        except Exception as e:
            error_msg = f"Error during evaluation: {e}"
            logger.error(f"Task {task.get('doc_id', 'unknown')}: {error_msg}")
            task["pass@1"] = 0.0
            task["compile@1"] = 0.0
            task["error"] = error_msg
            if self.raise_exception:
                raise e

    def eval_task_single(self, task_list):
        """Evaluate tasks sequentially."""
        for task in tqdm(task_list, desc="Evaluating tasks"):
            self.eval_single(task)

    def eval_task_parallel(self, task_list):
        """Evaluate tasks in parallel."""
        with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = [executor.submit(self.eval_single, task) for task in task_list]
            for _ in tqdm(
                as_completed(futures), total=len(futures), desc="Evaluating tasks"
            ):
                pass  # Results are stored in-place in task dictionaries

    def eval_task_list(self, task_list):
        """Evaluate all tasks."""
        if self.n_jobs == 1:
            self.eval_task_single(task_list)
        else:
            self.eval_task_parallel(task_list)

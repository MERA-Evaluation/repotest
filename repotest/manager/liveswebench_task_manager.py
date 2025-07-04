from tqdm import tqdm
import json
from repotest.core.docker.python import PythonDockerRepo
from repotest.core.local.python import PythonLocalRepo
from repotest.core.exceptions import GitException
from repotest.constants import OPTIMAL_CPU_NUM
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Union
import os

class LiveSWEBenchTaskManager:
    """
    Manager for evaluating LiveSWE-bench tasks using either Docker or local environments.

    Parameters
    ----------
    mode : str, optional
        The execution mode, either 'docker' or 'local'. Default is 'docker'.
    n_jobs : int, optional
        Number of parallel jobs to run. Default is 1.
    raise_exception : bool, optional
        Whether to raise exceptions during task execution. Default is True.
    verbose_all : bool, optional
        Enable verbose logging. Default is False.

    Attributes
    ----------
    REQUIRED_COLUMND : List[str]
        Required keys in each task.
    time_scale_factor : int
        Scaling factor for timeouts based on number of jobs.
    RepoClass : type
        Class used to handle repositories (either Docker or Local).
    """

    REQUIRED_COLUMND = ["instance_id", "repo", 
                        "base_commit", 
                        "image_name",
                        "test_patch", 
                        "command_test_small",
                        "timeout_build",
                        "timeout_test"
                       ]
    time_scale_factor: int = 1

    def __init__(
        self,
        column_patch = 'patch_model',
        mode: str = 'docker',
        n_jobs: int = OPTIMAL_CPU_NUM,
        raise_exception: bool = True,
        verbose_all: bool = False,
        time_scale_factor = 'auto'
    ):
        assert mode in ('docker', 'local')
        if mode == 'docker':
            self.RepoClass = PythonDockerRepo
        else:
            self.RepoClass = PythonLocalRepo

        self.mode = mode
        self.n_jobs = n_jobs
        if time_scale_factor == 'auto':
            self.time_scale_factor = self.n_jobs
        else:
            self.time_scale_factor = max(1, self.n_jobs / OPTIMAL_CPU_NUM)
        
        self.raise_exception = raise_exception
        self.column_patch = column_patch
        
        if verbose_all:
            from repotest.constants import enable_stdout_logs
            enable_stdout_logs()
    
    @staticmethod
    def extract_test(test_result: dict) -> tuple[set, set]:
        """
        Extracts passed and failed test names from a test result dictionary.

        Parameters
        ----------
        test_result : dict
            Dictionary containing test report information.

        Returns
        -------
        passed : set
            Set of test names that passed.
        failed : set
            Set of test names that failed.
        """
        list_of_tests = test_result.get('report', {}).get('tests', {})
        passed = set()
        failed = set()
        was = set()

        for d in list_of_tests:
            test_name = d['nodeid']
            assert test_name not in was
            was.add(test_name)
            if d['outcome'] == 'passed':
                passed.add(test_name)
            else:
                failed.add(test_name)

        return passed, failed

    def inplace_build_and_eval_single(self, task: Dict[str, Union[str, int]]) -> None:
        """
        Build and evaluate a single task in-place.

        Parameters
        ----------
        task : dict
            Task containing repository and command information.
        """
        try:
            repo = self.RepoClass(
                repo=task['repo'],
                base_commit=task['base_commit'],
                **({"image_name": task['image_name']} if self.mode == 'docker' else {})
            )
            if repo.was_build:
                if self.mode == 'docker':
                    print(f"Using image {repo.default_image_name} for {task['repo']}")
                    repo.image_name = repo.default_image_name
            else:
                print("Building ...")
                dct_build = repo.build_env(
                    task['command_build'],
                    timeout=task['timeout_build'] * self.time_scale_factor
                )
                task['dct_build'] = json.dumps(dct_build)
                print("Build success")

            repo.clean()
            repo.apply_patch(task['test_patch'])
            repo.apply_patch(task[self.column_patch])
            
            dct_test = repo.run_test(
                task['command_test_small'],
                timeout=task['timeout_test'] * self.time_scale_factor
            )
            
            task['dct_test'] = json.dumps(dct_test)
            success, failed = LiveSWEBenchTaskManager.extract_test(dct_test)
            if (set(success) & set(task['PASS_TO_PASS']) == set(task['PASS_TO_PASS'])):
                print("Solved", task['instance_id'])
                task['solved'] = 1
            else:
                print("Failed", task['instance_id'])
                task['solved'] = 0

        except GitException as e:
            print(f"Repo {task['repo']} {task['base_commit']} was deleted/moved")
            if self.raise_exception:
                raise e
        except Exception as e:
            print(f"Critical fail {task['repo']} {task['base_commit']}")
            if self.raise_exception:
                raise e

    def _build_and_eval_task_parallel(self, task_list: List[Dict[str, Union[str, int]]]) -> None:
        """
        Internal helper to run tasks in parallel.

        Parameters
        ----------
        task_list : list of dict
            List of tasks to process.
        """
        with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = [executor.submit(self.inplace_build_and_eval_single, task) for task in task_list]
            for _ in tqdm(as_completed(futures), total=len(futures)):
                pass

    def validate_input(self, task_list: List[Dict[str, Union[str, int]]]) -> None:
        """
        Validate required fields in task list.

        Parameters
        ----------
        task_list : list of dict
            List of tasks to validate.

        Raises
        ------
        AssertionError
            If required keys are missing from any task.
        """
        for ind, task in enumerate(task_list):
            for column in self.REQUIRED_COLUMND:
                assert column in task, f"there is no {column} at ind={ind}"

    def inplace_build_and_eval(self, task_list: List[Dict[str, Union[str, int]]]) -> None:
        """
        Build and evaluate tasks in-place, sequentially or in parallel.

        Parameters
        ----------
        task_list : list of dict
            List of tasks to evaluate.
        """
        self.validate_input(task_list)

        if self.n_jobs == 1:
            for task in task_list:
                try:
                    self.inplace_build_and_eval_single(task)
                except Exception as e:
                    if self.raise_exception:
                        raise e
                    else:
                        print(f"Critical error {e}")
        else:
            self._build_and_eval_task_parallel(task_list)
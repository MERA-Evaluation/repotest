import logging
import os
from tqdm import tqdm

from repotest.core.docker.java import JavaDockerRepo
from repotest.core.local.java import JavaLocalRepo
from repotest.constants import OPTIMAL_CPU_NUM
from repotest.core.exceptions import GitException
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Union

from repotest.parsers.java.surefire_report import (
    find_test_reports,
    find_all_test_report_dirs,
    )

logger = logging.getLogger("repotest")

# назвать pipeline ?
class JavaEvaluatorRealcode:
    """
    Manages evaluation and build tasks for real-world Java repositories using Dockerized environments.

    Parameters
    ----------
    mode : str, optional
        Execution mode, by default 'docker'.
    n_jobs : int, optional
        Number of parallel jobs, by default 1.
    gen_columns : list of str, optional
        Columns containing generated test results, by default 
        ['test_gt', 'test_pass', 'test_return_empty_str', 'test_gen'].
    raise_exception : bool, optional
        Whether to raise exceptions or suppress them, by default True.
    """
    
    build_success_status = {}
    
    def __init__(self,
                 mode='docker',
                 n_jobs=OPTIMAL_CPU_NUM,
                 gen_columns=['gt', 'stub'],
                 raise_exception=True,
                 n_jobs_build=OPTIMAL_CPU_NUM                
                ):
        assert mode in ('docker', 'local')
        if mode == 'docker':
            self.RepoClass = JavaDockerRepo
        elif mode == 'local':
            self.RepoClass = JavaLocalRepo
        
        self.mode = mode
        self.n_jobs = n_jobs
        self.n_jobs_build = n_jobs_build
        
        self.gen_columns = gen_columns
        self.raise_exception = raise_exception

    @staticmethod
    def extract_test(report_json: dict):
        list_of_tests = report_json.get('parser_xml', {})
        passed = set()
        failed = set()
        was = set()
        for test_suite in list_of_tests:
            cls_name = test_suite['class_name']

            for func_name in test_suite.get('passed', []):
                test_name = f'{cls_name} {func_name}'
                assert test_name not in was
                was.add(test_name)
                passed.add(test_name)
            
            # Что делать со skipped ?
            for field in ['failure', 'error', 'system-error']:
                for func_name in test_suite.get(field, []):
                    test_name = f'{cls_name} {func_name}'
                    assert test_name not in was
                    was.add(test_name)
                    failed.add(test_name)

        return passed, failed

    def get_passed_dict(self, task: dict) -> dict:
        passed, failed = self.extract_test(task['test_dry_run'])
        res = {}
        res['pass_dry_run'] = int(len(passed) > 0)
        for key in self.gen_columns:
            if (key in task) or (key == "gen"):
                passed_current, failed_current = self.extract_test(task["test_" + key])
                res_column_name = f"pass_{key}"
                res[res_column_name] = int((passed_current != set()) & ((passed_current & passed) == passed))
        return res
    
    def _new_repo(self, task: dict) -> Union[JavaDockerRepo, JavaLocalRepo]:
        try:
            kwargs = {'image_name': task['image_name']} if self.mode == 'docker' else dict()
            repo = self.RepoClass(repo=task['repo'],
                                  base_commit=task['base_commit'],
                                  **kwargs
                                 ) 
        except Exception as e:
            print(task['repo'], ' moved', e)
            if self.raise_exception:
                raise e
        return repo


    def eval_single(self, task: dict):
        repo_id = task['repo']
        if self.build_success_status.get(repo_id, 0) == 0:
            logger.info(f"[Test failure] Skip {repo_id} because it was unable to build earlier")
            task['status'] = 0
            return None
        
        repo = self._new_repo(task)
        repo.clean()
        task['test_dry_run'] = repo.run_test(task['test_command'], timeout=1800)

        for gen_column in self.gen_columns:
            old_test_reports = find_test_reports(repo.cache_folder)
            old_test_dirs = find_all_test_report_dirs(repo.cache_folder)
            ok = repo.clean_dirs(old_test_dirs)
            if not ok:
                logger.info("[Test failure] Unable to wipe test reports dirs")
            for path in old_test_reports:
                assert not os.path.exists(path), f'[Test failure] Found old test results at {path}'

            # repo = self._new_repo(task)
            repo.clean()
            repo.change_file_realcode(fn_relative=task['file_path'], 
                                      left_context=task['left_context'], 
                                      gt=task[gen_column], 
                                      right_context=task['right_context']
                                     )
            task['test_' + gen_column] = repo.run_test(task['test_command'], timeout=1200)
        
        passed_dict = self.get_passed_dict(task)
        for key, value in passed_dict.items():
            assert key not in task
            task[key] = value
        
        task['status'] = 1
        return None
    
    def eval_tasks_in_sequence(self, task_list: List[dict]):
        for task in tqdm(task_list, desc='test'):
            self.eval_single(task)
        return None
    
    def eval_tasks_parallel(self, task_list: List[dict]):
        with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = [executor.submit(self.eval_single, task) for task in task_list]
            for _ in tqdm(as_completed(futures), total=len(futures), desc='test'):
                pass  # We don't need the result since it's in-place
        return None
        
    def eval_task_list(self, task_list: List[dict]):
        if self.n_jobs == 1:
            self.eval_tasks_in_sequence(task_list)
        else:
            self.eval_tasks_parallel(task_list)
    
    def inplace_build_and_eval(self, task_list: List[dict]):
        print("Running `git clone` ...")
        self.build_task_list(task_list)
        print("Running tests ...")
        self.eval_task_list(task_list)
    
    @staticmethod
    def get_build_task_list(task_list: List[dict]):
        build_task_list = []
        was = set()
        for task in task_list:
            key = task['repo']
            if key not in was:
                was.add(key)
                build_task_list.append(task)
        return build_task_list

    def build_single(self, task: dict):
        repo = self._new_repo(task)
        return None

    def build_tasks_in_sequence(self, task_list: List[dict]):
        build_task_list = self.get_build_task_list(task_list)
        self.build_success_status = {}
        for task in tqdm(build_task_list, desc='build'):
            repo_id = task['repo']
            self.build_success_status[repo_id] = 0
            try:
                self.build_single(task)
                self.build_success_status[repo_id] = 1
            except GitException as e:
                if self.raise_exception:
                    raise e
        return None
                    
    def build_tasks_parallel(self, task_list: List[dict]):
        build_task_list = self.get_build_task_list(task_list)
        self.build_success_status = {}
        
        def _build(task):
            repo_id = task['repo']
            self.build_success_status[repo_id] = 0
            try:
                self.build_single(task)
                self.build_success_status[repo_id] = 1
            except GitException as e:
                if self.raise_exception:
                    raise e
        
        with ThreadPoolExecutor(max_workers=self.n_jobs_build) as executor:
            futures = [executor.submit(_build, task) for task in build_task_list]
            for _ in tqdm(as_completed(futures), total=len(futures), desc='build'):
                pass  # We don't need the result since it's in-place
        return None
       
    def build_task_list(self, task_list: List[dict]):
        if self.n_jobs_build == 1:
            self.build_tasks_in_sequence(task_list)
        else:
            self.build_tasks_parallel(task_list)

from tqdm import tqdm

from repotest.core.docker.python import PythonDockerRepo
from repotest.core.local.python import PythonLocalRepo
from repotest.constants import OPTIMAL_CPU_NUM
from repotest.core.exceptions import GitException
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

class TaskManagerRealcode:
    """
    Manages evaluation and build tasks for real-world Python repositories using Dockerized environments.

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
                 gen_columns=['gt', 'pass', 'return_empty_str', "gen"],
                 raise_exception=True,
                 n_jobs_build=OPTIMAL_CPU_NUM                
                ):
        assert mode in ('docker', 'local')
        if mode == 'docker':
            self.RepoClass = PythonDockerRepo
        elif mode == 'local':
            self.RepoClass = PythonLocalRepo
        
        self.mode = mode
        self.n_jobs = n_jobs
        self.n_jobs_build = n_jobs_build
        
        self.gen_columns = gen_columns
        self.raise_exception = raise_exception
    
    @staticmethod
    def extract_test(report_json):
        list_of_tests = report_json.get('report', {}).get('tests', {})
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

    
    def get_passed_dict(self, task):
        passed, failed = self.extract_test(task["test_dry_run"])
        res = {}
        res['pass_dry_run'] = int(len(passed) > 0)
        for key in self.gen_columns:
            if (key in task) or (key == "gen"):
                passed_current, failed_current = self.extract_test(task["test_" + key])
                res_column_name = f"pass_{key}"
                res[res_column_name] = int((passed_current != set()) & ((passed_current & passed) == passed))
        return res

    def eval_single(self, task):
        if self.build_success_status.get((task['repo'], task['base_commit']), 0) == 0:
            return
        task['status'] = 0
        passed_dict = None
        try:
            repo = self.RepoClass(repo=task['repo'],
                                  base_commit=task['base_commit'],
                                  **({"image_name": task['image_name']} if self.mode=='docker' else {})
                                 ) 
        except Exception as e:
            print(task['repo'], ' moved', e)
            if self.raise_exception:
                raise e
            finally_fill = True
        else:
            finally_fill = False

        try:
            if (not repo.was_build) or ("passed_dict" in task):
                return

            repo.clean()
            if self.mode == 'docker':
                repo.image_name = repo.default_image_name

            task['test_dry_run'] = repo.run_test(task['test_command'], timeout=300)

            for gen_column in self.gen_columns:
                repo.clean()
                repo.change_file_realcode(fn_relative=task['fn'], 
                                          left_context=task['left_context'], 
                                          gt=task[gen_column], 
                                          right_context=task['right_context']
                                         )
                task['test_' + gen_column] = repo.run_test(task['test_command'], timeout=300)

            passed_dict = self.get_passed_dict(task)
            for key, value in passed_dict.items():
                assert key not in task
                task[key] = value
            task['status'] = 1
        except Exception as e:
            if self.raise_exception:
                raise e
            finally_fill = True
        finally:
            if passed_dict is None:
                task['pass_dry_run'] = 0
                for key in self.gen_columns:
                    if (key in task) or (key == "gen"):
                        task[f'pass_{key}'] = 0

    @staticmethod
    def get_build_task_list(task_list):
        build_task_list = []
        was = set()
        for task in task_list:
            key = (task['repo'], task['base_commit'])
            if key not in was:
                was.add(key)
                build_task_list.append(task)
        assert len(set([(task['repo'], task['base_commit']) for task in build_task_list])) == len(build_task_list)
        return build_task_list

    def build_single(self, task):
        try:
            repo = self.RepoClass(repo=task['repo'],
                                  base_commit=task['base_commit'],
                                  **({"image_name": task['image_name']} if self.mode == 'docker' else {})
                                  ) 
        except Exception as e:
            print(task['repo'], ' moved', e)
            raise e        
        if not repo.was_build:
            repo.build_env(command=task['build_command'],
                           timeout=task.get('build_timeout', 3000))

    def build_task_list_single(self, task_list):
        build_task_list = self.get_build_task_list(task_list)
        self.build_success_status = {}
        for task in tqdm(build_task_list):
            task_id = (task['repo'], task['base_commit'])
            self.build_success_status[task_id] = 0
            try:
                self.build_single(task)
                self.build_success_status[task_id] = 1
            except GitException as e:
                if self.raise_exception:
                    raise e
                    
    def build_task_list_parallel(self, task_list):
        build_task_list = self.get_build_task_list(task_list)
        self.build_success_status = {}
        
        def build(task):
            task_id = (task['repo'], task['base_commit'])
            self.build_success_status[task_id] = 0
            try:
                self.build_single(task)
                self.build_success_status[task_id] = 1
            except GitException as e:
                if self.raise_exception:
                    raise e
        with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = [executor.submit(build, task) for task in build_task_list]
            for _ in tqdm(as_completed(futures), total=len(futures)):
                pass  # We don't need the result since it's in-place
       
    def build_task_list(self, task_list):
        if self.n_jobs_build == 1:
            self.build_task_list_single(task_list)
        else:
            self.build_task_list_parallel(task_list)
    
    def eval_task_single(self, task_list):
        for task in tqdm(task_list):
            self.eval_single(task)
    
    def eval_task_parallel(self, task_list):
        with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = [executor.submit(self.eval_single, task) for task in task_list]
            for _ in tqdm(as_completed(futures), total=len(futures)):
                pass  # We don't need the result since it's in-place
        
    def eval_task_list(self, task_list):
        if self.n_jobs == 1:
            self.eval_task_single(task_list)
        else:
            self.eval_task_parallel(task_list)
    
    def inplace_build_and_eval(self, task_list):
        print("Building envs ...")
        self.build_task_list(task_list)
        print("Running tests ...")
        self.eval_task_list(task_list)
        
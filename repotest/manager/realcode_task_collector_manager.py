from tqdm import tqdm

from repotest.core.docker.python import PythonDockerRepo
from repotest.core.local.python import PythonLocalRepo
from repotest.constants import OPTIMAL_CPU_NUM
from repotest.parsers.python.collect_task import TaskCollector
from repotest.core.exceptions import GitException
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import json

class RealcodeTaskCollectorManager:
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
                 n_jobs_build=OPTIMAL_CPU_NUM,
                 timeout=300
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
        self.timeout = timeout
    
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
                res[res_column_name] = int((passed_current & passed) == passed)
        return res

    def eval_single(self, task):
        task['status'] = 0
        
        try:
            repo = self.RepoClass(repo=task['repo'],
                                  base_commit=task['base_commit'],
                                  **({"image_name": task['image_name']} if self.mode=='docker' else {})
                                 ) 
        except Exception as e:
            print(task['repo'], ' moved', e)
            raise e
                
        repo.clean()
        command_build_and_test = task['command_build'] + \
                         (';\n' if task['command_build'][-1] != ';' else '\n' ) + \
                             task['command_test']
        
        task['command_build_and_test'] = command_build_and_test
        dct_build_and_test = repo.run_test(command_build_and_test, 
                                       timeout=self.timeout
                                      )
        task['dct_build_and_test'] = json.dumps(dct_build_and_test)
        
        collector = TaskCollector(repo.cache_folder, mode=self.mode)
        df_problems = collector.data
        n_good_candidates = ((df_problems['PASS_TO_PASS'].apply(len)>0) &\
                             df_problems['doc'].notna() & \
                             (df_problems['intent_type'] == 'function')
                            ).sum()
        
        print("Collected %s %s %d/%d"%(task['repo'], task['base_commit'], 
                                       n_good_candidates, len(df_problems)
                                      )
             )
        df_problems['tests']        = df_problems['tests'].apply(lambda x: json.dumps(list(x)))
        df_problems['PASS_TO_PASS'] = df_problems['PASS_TO_PASS'].apply(lambda x: json.dumps(list(x)))
        df_problems['FAIL_TO_PASS'] = df_problems['FAIL_TO_PASS'].apply(lambda x: json.dumps(list(x)))
        task['problems'] = json.dumps(list(df_problems.T.to_dict().values()))
        
        task['status'] = 1

    def collect_task_single(self, task_list):
        for task in tqdm(task_list):
            try:
                self.eval_single(task)
            except Exception as e:
                if self.raise_exception:
                    raise e
    
    def collect_task_parallel(self, task_list):
        with ThreadPoolExecutor(max_workers=self.n_jobs) as executor:
            futures = [executor.submit(self.eval_single, task) for task in task_list]
            for _ in tqdm(as_completed(futures), total=len(futures)):
                pass  # We don't need the result since it's in-place
        
    def collect_task_list(self, task_list):
        if self.n_jobs == 1:
            self.collect_task_single(task_list)
        else:
            self.collect_task_parallel(task_list)
    
    def inplace_collect(self, task_list):
        self.collect_task_list(task_list)
        
# # Example of ussage
# task_list = [{'repo': 'mzaja/betfair-database',
#   'base_commit': '7759d5337b780d3007c37d62421ffe5490dc4a26',
#   'image_name': 'python:3.11',
#   'command_build': 'if [ -f requirements-dev.txt ]; then\n    pip install -r requirements-dev.txt\nelif [ -f requirements_dev.txt ]; then\n    pip install -r requirements_dev.txt\nelif [ -f requirements.txt ]; then\n    pip install -r requirements.txt\nfi\npip install . && pip install pytest pytest-json-report pytest-cov',
#   'command_test': 'pytest --cov=. --cov-branch --cov-context=test --cov-report=annotate --json-report --json-report-file=report_pytest.json'},
#  {'repo': 'onlyfanfuriks/simple-reg-cleaner',
#   'base_commit': '66ea893fdca6593a62729361c5858a6c2a7b1e3f',
#   'image_name': 'python:3.11',
#   'command_build': 'if [ -f requirements-dev.txt ]; then\n    pip install -r requirements-dev.txt\nelif [ -f requirements_dev.txt ]; then\n    pip install -r requirements_dev.txt\nelif [ -f requirements.txt ]; then\n    pip install -r requirements.txt\nfi\npip install . && pip install pytest pytest-json-report pytest-cov',
#   'command_test': 'pytest --cov=. --cov-branch --cov-context=test --cov-report=annotate --json-report --json-report-file=report_pytest.json'},
#  {'repo': 'ahartlba/decorator_validation',
#   'base_commit': '462096d0da0872ecfbdd6b565bd3d6e407e7206c',
#   'image_name': 'python:3.11',
#   'command_build': 'if [ -f requirements-dev.txt ]; then\n    pip install -r requirements-dev.txt\nelif [ -f requirements_dev.txt ]; then\n    pip install -r requirements_dev.txt\nelif [ -f requirements.txt ]; then\n    pip install -r requirements.txt\nfi\npip install . && pip install pytest pytest-json-report pytest-cov',
#   'command_test': 'pytest --cov=. --cov-branch --cov-context=test --cov-report=annotate --json-report --json-report-file=report_pytest.json'}
# ]

# manager = RealcodeTaskCollectorManager(mode='docker', n_jobs=2, raise_exception=False)
# manager.inplace_collect(task_list)

# # See problems
# pd.DataFrame(json.loads(task_list[3]['problems']))

# Collected mzaja/betfair-database 7759d5337b780d3007c37d62421ffe5490dc4a26 93/184
# Collected onlyfanfuriks/simple-reg-cleaner 66ea893fdca6593a62729361c5858a6c2a7b1e3f 1/49
# Collected ahartlba/decorator_validation 462096d0da0872ecfbdd6b565bd3d6e407e7206c 5/181

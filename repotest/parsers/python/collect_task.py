import ast
import glob
import os
import json
from bisect import bisect_right
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional, Any, Union
from repotest.constants import REPOTEST_MAIN_FOLDER

import coverage
import pandas as pd
from functools import cached_property, lru_cache


class LineIndexMap:
    """
    A class to map line numbers to intervals and retrieve associated data.

    Attributes
    ----------
    intervals : List[Tuple[int, int]]
        Sorted list of intervals (start_line, end_line).
    data : Dict[Tuple[int, int], Any]
        Dictionary mapping intervals to their associated data.
    """

    def __init__(self, data: Dict[Tuple[int, int], Any]) -> None:
        """
        Initialize the LineIndexMap with interval-data pairs.

        Parameters
        ----------
        data : Dict[Tuple[int, int], Any]
            Dictionary where keys are intervals (start_line, end_line) and values are associated data.
        """
        self.intervals: List[Tuple[int, int]] = sorted(data.keys())
        self.data: Dict[Tuple[int, int], Any] = data

    def __call__(self, line_number: int) -> List[Any]:
        """
        Retrieve data for intervals that contain the given line number.

        Parameters
        ----------
        line_number : int
            The line number to search for.

        Returns
        -------
        List[Any]
            List of data associated with intervals containing the line number.
        """
        idx: int = bisect_right(self.intervals, (line_number, float('inf')))
        result: List[Any] = []

        for i in range(idx - 1, -1, -1):
            start, end = self.intervals[i]
            if start <= line_number <= end:
                result.append(self.data[(start, end)])
            else:
                break

        return result[::-1]


class ContextParser:
    """
    Recursively parse a Python file and extract function and class definitions
    as test candidates.
    """

    def __init__(self, fn: str) -> None:
        """
        Parameters
        ----------
        fn : str
            Path to the Python file to parse.
        """
        self.fn: str = fn
        self.problems: List[Dict[str, Any]] = []

        with open(fn, "r") as file:
            source_code: str = file.read()
            self.lines: List[str] = source_code.split('\n')
            try:
                tree = ast.parse(source_code, filename=fn)
            except SyntaxError:
                # Example of error: from {{cookiecutter.package_name}}.example import hello
                return

        self.dfs(tree)

    def parse_node(self, node: Union[ast.FunctionDef, ast.ClassDef], intent_type: str) -> Dict[str, Any]:
        """
        Parse a node into a structured dictionary.

        Parameters
        ----------
        node : ast.FunctionDef or ast.ClassDef
            AST node to parse.
        intent_type : str
            Either 'function' or 'class'.

        Returns
        -------
        Dict[str, Any]
            Structured representation of the node.
        """
        first_line = node.body[0]
        if isinstance(first_line, ast.Expr) and isinstance(first_line.value, ast.Constant):
            l = first_line.end_lineno
            r = node.end_lineno
            left_context = '\n'.join(self.lines[:l]) + '\n'
            gt = '\n'.join(self.lines[l:r]) + '\n'
            right_context = '\n'.join(self.lines[r:]) + '\n'
            doc = ast.unparse(first_line)
        else:
            l = 99999
            if hasattr(first_line, "decorator_list") and len(first_line.decorator_list) > 0:
                l = first_line.decorator_list[0].lineno
            l = min(l, first_line.lineno - 1)
            r = node.end_lineno
            left_context = '\n'.join(self.lines[:l]) + '\n'
            gt = '\n'.join(self.lines[l:r]) + '\n'
            right_context = '\n'.join(self.lines[r:]) + '\n'
            doc = None

        return {
            'intent': f"{node.name}[{intent_type}]",
            'intent_type': intent_type,
            "intent_name": node.name,
            "l": l,
            "r": r,
            "left_context": left_context,
            "gt": gt,
            "right_context": right_context,
            'doc': doc,
            "_node": node,
            "fn": self.fn,
            "source": f"{self.fn}:{node.name}[{intent_type}]",
            "tests": set()
        }

    def dfs(self, ptr: ast.AST) -> None:
        """
        Recursively traverse the AST to find function/class definitions.

        Parameters
        ----------
        ptr : ast.AST
            The root AST node to begin traversal from.
        """
        if isinstance(ptr, ast.FunctionDef):
            self.problems.append(self.parse_node(ptr, 'function'))
        elif isinstance(ptr, ast.ClassDef):
            self.problems.append(self.parse_node(ptr, 'class'))

        for child in getattr(ptr, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                self.dfs(child)

    def __len__(self) -> int:
        return len(self.problems)

    def __getitem__(self, ind: int) -> Dict[str, Any]:
        return self.problems[ind]

    def __repr__(self) -> str:
        return f"Problems(n_problems={len(self)})"

    def index_dict(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        """
        Build a dictionary mapping line intervals to problem objects.

        Returns
        -------
        Dict[Tuple[int, int], Dict[str, Any]]
        """
        return {(obj['l'], obj['r']): obj for obj in self.problems}

    def show(self, ind: int) -> None:
        """
        Print detailed information about a problem.

        Parameters
        ----------
        ind : int
            Index of the problem to show.
        """
        for k, v in self[ind].items():
            if isinstance(v, int):
                print(f'\t{k}={v}')
            else:
                print(f"\t{k}")
                print(v)
                print('== === ' * 7)


class TaskCollector:
    """
    Collect coverage data and map it to parsed code elements.
    """

    def __init__(self, 
                 folder: str, 
                 mode: str='docker',
                 drop_ast_column: bool = True
                ) -> None:
        """
        Parameters
        ----------
        folder : str
            Root directory containing the Python source and `.coverage` file.
        """
        # ToDo: quick fix to relative folder
        self.mode = mode
        assert self.mode in ("local", "docker")
        self.drop_ast_column = drop_ast_column
        
        self.folder: str = folder
        self.calculate_index()
        self.calculate_failed_passed_tests_set()
    
    @cached_property
    def cov_data(self) -> coverage.CoverageData:
        """
        Load and return coverage data.

        Returns
        -------
        coverage.CoverageData

        Raises
        ------
        FileNotFoundError
            If `.coverage` file does not exist.
        """
        data_file = os.path.join(self.folder, ".coverage")
        if not os.path.exists(data_file):
            raise FileNotFoundError(f"No .coverage file found at {data_file}")
        cov = coverage.Coverage(data_file=data_file)
        cov.load()
        return cov.get_data()

    @cached_property
    def python_file_list(self) -> List[str]:
        """
        Return a list of all Python files under the folder.

        Returns
        -------
        List[str]
        """
        return glob.glob(f"{self.folder}/**/*.py", recursive=True)

    def calculate_index(self) -> None:
        """
        Generate mapping of Python files to LineIndexMaps.
        """
        self.index: Dict[str, LineIndexMap] = {}
        for fn in self.python_file_list:
            file_index = ContextParser(fn).index_dict()
            for ptr in file_index.values():
                ptr['_fn_inside_repo'] = ptr['fn']
                ptr['fn'] = self.fn_to_docker_fn(ptr['fn'])
            
            if file_index:
                self.index[self.fn_to_docker_fn(fn)] = LineIndexMap(file_index)
    
    def fn_to_docker_fn(self, fn):
        #ToDo: fix this madnes. The problem that inside pytest .coverage file, fn = "/run_dir/some_file.py"
        # really there is ~/.cache/repotest/runs/sf824jsdf/some_file.py
        # This bug cause when attach volume to /run_dir/ instead of using same folder
        # This increase spead at realcode/liveswebench tasks, but cause this error
        if self.mode == 'docker':
            _, fn_relative = fn[len(os.path.join(REPOTEST_MAIN_FOLDER, "runs/")):].split('/', 1)
            fn = os.path.join("/run_dir/", fn_relative)
        
        if fn.startswith("/home/paadamenko/"):
            fn = "/data/adam/" + fn[len("/home/paadamenko/"):]
        
        return fn
    
    def run(self) -> None:
        """
        Enrich indexed problems with test coverage information.
        """
        for _fn in self.python_file_list:            
            fn = self.fn_to_docker_fn(_fn)
            dict_lineno_test_list = self.cov_data.contexts_by_lineno(fn)
            if dict_lineno_test_list:
                for line_num, test_list in dict_lineno_test_list.items():
                    test_files = list(set(test.split('[')[0] for test in test_list if test))
                    if test_files:
                        if fn in self.index:
                            for obj in self.index[fn](line_num):
                                obj.setdefault("tests", set()).update(test_files)

    def compute_coverage(self, row):
        #ToDo: think about how to manage this better
        fn_inside_repo = self.fn_to_docker_fn(row['_fn_inside_repo'])
        lines_covered = set(self.cov_data.lines(fn_inside_repo) or [])
        total_lines = set(range(row['l'], row['r'] + 1))
        if not total_lines:
            return 0.0
        covered = total_lines & lines_covered
        return round(100 * len(covered) / len(total_lines), 2)
    
    @cached_property
    def data(self) -> pd.DataFrame:
        """
        Returns
        -------
        pd.DataFrame
            A dataframe of all collected problem objects enriched with coverage info.
        """
        self.run()
        data = []
        for problem_obj in self.index.values():
            for problem_dict in problem_obj.data.values():
                data.append(problem_dict)
        data = pd.DataFrame(data)
        assert data['tests'].apply(lambda x: isinstance(x, set)).all()
        data['PASS_TO_PASS'] = data['tests'].apply(lambda x: 
                                                   [t for i in x 
                                                    if (t:=i.split('|')[0]) in self.passed_tests_set
                                                   ]
                                                  )
        data['FAIL_TO_PASS'] = data['tests'].apply(lambda x: 
                                                   [t for i in x 
                                                    if (t:=i.split('|')[0]) in self.failed_tests_set
                                                   ]
                                                  )
        if self.drop_ast_column:
            data.drop("_node", axis = 1, inplace = True)
        
        data["coverage_rate"] = data.apply(self.compute_coverage, axis=1)

        return data
    
    def calculate_failed_passed_tests_set(self) -> Tuple[Set[str], Set[str]]:
        """Extract sets of passed and failed test node IDs from pytest JSON report.

        Returns
        -------
        Tuple[Set[str], Set[str]]
            A tuple containing two sets:
            - First set contains node IDs of passed tests
            - Second set contains node IDs of failed tests

        Raises
        ------
        FileNotFoundError
            If the pytest JSON report file is not found in the specified folder.
        AssertionError
            If any test node ID appears in both passed and failed sets (invalid state),
            or if a test node ID appears multiple times in the same result set.

        Examples
        --------
        >>> passed, failed = get_failed_passed_tests_set("test_results")
        >>> print(f"Passed: {len(passed)}, Failed: {len(failed)}")
        """
        fn_pytest_json = os.path.join(self.folder, "report_pytest.json")
        if not os.path.exists(fn_pytest_json):
            raise FileNotFoundError(f"Pytest JSON report not found: {fn_pytest_json}")

        with open(fn_pytest_json, 'r', encoding='utf-8') as f:
            pytest_json = json.load(f)

        self.passed_tests_set: Set[str] = set()
        self.failed_tests_set: Set[str] = set()

        for test_case in pytest_json.get('tests', []):
            nodeid = test_case['nodeid']
            outcome = test_case['outcome']

            if outcome == 'passed':
                if nodeid in self.passed_tests_set:
                    raise AssertionError(f"Duplicate passed test: {nodeid}")
                self.passed_tests_set.add(nodeid)
            else:
                if nodeid in self.failed_tests_set:
                    raise AssertionError(f"Duplicate failed test: {nodeid}")
                self.failed_tests_set.add(nodeid)

        if self.passed_tests_set & self.failed_tests_set:
            raise AssertionError("Some tests appear in both passed and failed sets")


    def validate(self):
        assert self.data['source'].nunique() == self.data.shape[0]

# # ## Example of ussage
# repo = PythonLocalRepo(repo = "mlizzi/slack-progress-bar",
#                        base_commit = "d2d6d955fb8a0423ab89c1bac6c4f70101e6b8af",
# #                      image_name = "python:3.11.11-slim-bookworm"
#                         )
# repo.clean()
# dict_test = repo(command_build="pip install .;\npip install pytest;\npip install pytest-json-report;\npip install pytest-cov" ,
#                  command_test="pytest --cov=. --cov-branch --cov-context=test --cov-report=annotate --json-report --json-report-file=report_pytest.json"
#                 )
# print("report/summary", dict_test.get('report', {}).get('summary', {}))
# print("was_build:", repo.was_build)

# collector = TaskCollector(repo.cache_folder, mode='local')

# # Tasks at realcode format
# collector.data
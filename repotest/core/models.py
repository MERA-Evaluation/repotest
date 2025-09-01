import hashlib
import json
import os
from dataclasses import dataclass, asdict
from typing import List, Optional
from repotest.constants import DEFAULT_CACHE_FOLDER
from repotest.core.docker.python import PythonDockerRepo
from repotest.core.local.python import PythonLocalRepo

DEFAULT_CACHE_FOLDER = DEFAULT_CACHE_FOLDER[:-len("repos")]

@dataclass
class Task:
    """Base class for all tasks."""
    repo: str
    base_commit: str
    image_name: str
    command_build: str
    command_test: str
    fail_to_pass: Optional[List[str]] = None
    pass_to_pass: Optional[List[str]] = None
    patch: str = ""
    timeout_build: int = 300
    timeout_test: int = 600
    _ok: bool | None = None
    
    @property
    def task_id(self) -> str:
        """
        Calculate a unique and deterministic MD5 hash for the task configuration.
        This is used as an identifier. Since the object is mutable, this property
        is recalculated on every access to reflect the current state.
        """
        # Convert the dataclass instance to a dictionary.
        task_dict = self.to_dict()
        # Serialize to a JSON string with sorted keys for a consistent hash.
        task_json = json.dumps(task_dict, sort_keys=True, separators=(',', ':'))
        # Return the MD5 hash as a hex digest
        return f"{self.repo.split('/')[-1]}-{self.base_commit[-4:]}-{hashlib.md5(task_json.encode('utf-8')).hexdigest()[:4]}"

    def to_dict(self) -> dict:
        """Return the dataclass fields as a dictionary."""
        return asdict(self)

    def save(self) -> None:
        """
        Save the task data as a JSON file in the default cache folder.
        The file will be located at: DEFAULT_CACHE_FOLDER/tasks/{task_id}.json.
        """
        folder_path = os.path.join(DEFAULT_CACHE_FOLDER, 'tasks')
        os.makedirs(folder_path, exist_ok=True)
        file_path = os.path.join(folder_path, f'{self.task_id}.json')
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
@dataclass
class PythonTask(Task):
    """Task for a standard Python project."""
    image_name: str = 'python:3.11'
    command_build: str = 'pip install -e .[test]\npip install pytest-json-report'
    command_test: str  = 'pytest --json-report --json-report-file=report_pytest.json'

    def _set_params(self, mode='docker', save=True):
        self._mode = mode
        self._save = save
        if self._mode not in ('docker', 'local'):
            raise NotImplementedError(f"Unknown _mode {self_mode}")
    
    def _init_repo(self):
        if self._mode == 'docker':
            _class = PythonDockerRepo
        elif self._mode == 'local':
            _class = PythonLocalRepo
        else:
            raise NotImplementedError(f"Unknown _mode {self_mode}")
        self._repo = _class(repo = self.repo,
                            base_commit = self.base_commit,
                            image_name = self.image_name
                           )
        
    def _build_env(self):
        res = self._repo.build_env(self.command_build, timeout = self.timeout_build)
        if self._save:
            self.dct_build = res
        return res
    
    def _run_test(self):
        self._ok = False
        res = self._repo.run_test(self.command_test, timeout = self.timeout_test)
        if self._save:
            self.dct_test = res
        
        n = res['report'].get("summary", {}).get("passed")
        if n > 0:
            self._ok = True
        
        return res
    
    def save(self) -> None:
        """
        Save the task data as a JSON file in the default cache folder.
        The file will be located at: DEFAULT_CACHE_FOLDER/tasks/{task_id}.json.
        """
        folder_path = os.path.join(DEFAULT_CACHE_FOLDER, 'tasks')
        os.makedirs(folder_path, exist_ok=True)
        file_path = os.path.join(folder_path, f'{self.task_id}.json')
        
        with open(file_path, 'w', encoding='utf-8') as f:
            dct = self.to_dict()
            for key in ['dct_test', 'dct_build']:
                dct[key] = getattr(self, key, None)
            json.dump(dct, f, ensure_ascii=False, indent=2)
    
    def run(self, mode='docker', save=True):
        self._set_params(mode=mode, save=save)
        self._init_repo()
        self._build_env()
        self._run_test()
        self.save()
        
@dataclass
class PythonRealCodeCollectTask(PythonTask):
    """
    Task for a Python project with code coverage enabled.
    Inherits commands from PythonTask and extends them.
    """
    _command_build: str = ""
    _command_test: str = ""
    def __post_init__(self):
        self._command_build = self.command_build
        self._command_test = self.command_test
        self.command_build += "\npip install pytest-cov"
        self.command_test: str = (
        "pytest --cov=. --cov-branch --cov-context=test "
        "--cov-report=annotate --json-report "
        "--json-report-file=report_pytest.json"
    )
        self.command_build_test = self.command_build + '\n' + self.command_test
    
import os
from repotest.core.local.base import AbstractLocalRepo
from repotest.constants import DEFAULT_EVAL_TIMEOUT_INT, DEFAULT_BUILD_TIMEOUT_INT, CONDA_ENV_NAME, DEFAULT_CACHE_FOLDER
from repotest.parsers.python.pytest_stdout import parse_pytest_stdout
from repotest.core.exceptions import TimeOutException

from typing import Dict
import json

import logging
logger = logging.getLogger("repotest")

class PythonLocalRepo(AbstractLocalRepo):
    """
    A class for managing and testing local Python repositories.

    Attributes
    ----------
    test_timeout : int
        Maximum time (in seconds) to wait for test execution (default is 60 seconds).
    """
    
    @property
    def conda_env_path(self):
        #return os.path.join(self.cache_folder, CONDA_ENV_NAME)
        return os.path.abspath(os.path.join(DEFAULT_CACHE_FOLDER, '../envs/', self.repo, self.base_commit, CONDA_ENV_NAME))

    def _mock_build_command(self, command):
        """Mocks a Conda environment creating."""
        #ToDo: understand why conda activate not working and fix this
        prefix = f"""conda create -p {self.conda_env_path}/ --copy -y python=3.11;
export CONDA_PREFIX={self.conda_env_path};
export PATH=$CONDA_PREFIX/bin:$PATH;
"""
        if not command.startswith(prefix):
            return prefix + command
        logger.debug("Export environment already in command.")
        return command
    
    def build_env(
        self,
        command: str = """pip install .
pip install pytest pytest-json-report
""",
        timeout: int = DEFAULT_BUILD_TIMEOUT_INT,
    ) -> None:
        """
        Builds the testing environment using Conda.

        Parameters
        ----------
        command : str, optional
            Shell command for setting up the environment.
        timeout : int, optional
            Maximum time to wait for environment setup.

        Returns
        -------
        None
        """
        command = self._mock_build_command(command)
        return self.subprocess_run(command=command, timeout=timeout)

    def _mock_conda_env(self, command: str) -> str:
        """
        Mocks a Conda environment by setting environment variables.

        Parameters
        ----------
        command : str
            The command to modify.

        Returns
        -------
        str
            Modified command with environment settings.

        Examples
        --------
        >>> repo = PythonLocalRepo("myrepo", "abc123")
        >>> repo._mock_conda_env("pytest")
        'export CONDA_PREFIX=$(pwd)/{CONDA_ENV_NAME}\\nexport PATH=$CONDA_PREFIX/bin:$PATH\\nalias pytest="python -m pytest"\\npytest'
        """
        #ToDo: understand why conda activate not working and fix this
        prefix =f"""export CONDA_PREFIX={self.conda_env_path}
export PATH=$CONDA_PREFIX/bin:$PATH
alias pytest="python -m pytest"
"""
        if not command.startswith(prefix):
            return prefix + command
        logger.debug("Export environment already in command.")
        return command
    
    @property
    def was_build(self):
        fn_conda_history = os.path.join(self.conda_env_path, "conda-meta/history")
        if os.path.exists(fn_conda_history):
            return True
        else:
            return False
    
    def __call__(self, 
                 command_build: str, 
                 command_test: str,
                 timeout_build:int = DEFAULT_BUILD_TIMEOUT_INT,
                 timeout_test:int = DEFAULT_EVAL_TIMEOUT_INT
                 ):
        """
        Runs the build and test process for the Python repository.

        Parameters
        ----------
        command_build : str
            Command to build the environment.
            timeout_build : int, optional
            Maximum time to wait for environment setup.
        """
        if not self.was_build:
            self.build_env(command = command_build, timeout=timeout_build)
        res = self.run_test(command = command_test, timeout=timeout_test)
        return res
    
    def run_test(
        self,
        command: str = "pytest --json-report",
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
    ) -> Dict[str, str | int | dict]:
        """
        Runs tests using Conda and pytest.

        Parameters
        ----------
        command : str, optional
            Custom command to execute tests.
        timeout : int, optional
            Maximum time to wait for test execution.

        Returns
        -------
        dict
            A dictionary containing the test results.

        Examples
        --------
        >>> repo = PythonLocalRepo("myrepo", "abc123")
        >>> repo.run_test()
        {'stdout': '...', 'stderr': '...', 'returncode': 0, 'report': {...}}
        """
        command = self._mock_conda_env(command)
        result = {}
        try:
            result = self.subprocess_run(command, timeout=timeout)
        except TimeOutException as e:
            logger.warning(e, exc_info=True)
            self.return_code = 2
            self.stderr = "Timeout exception"
            result['returncode'] = self.return_code
            result['stdout'] = self.stdout
            result['stderr'] = self.stderr
        except Exception as e:
            logger.critical(e, exc_info=True)
            raise e
        
        result["parser"] = parse_pytest_stdout(self.stdout)

        fn_json_result = os.path.join(self.cache_folder, "report_pytest.json")
        result["report"] = json.load(open(fn_json_result)) if os.path.exists(fn_json_result) else {}

        return result

from abc import abstractmethod
import subprocess
import logging
from repotest.core.base import AbstractRepo
from repotest.constants import DEFAULT_EVAL_TIMEOUT_INT, DEFAULT_CACHE_FOLDER
from repotest.parsers.python.pytest_stdout import parse_pytest_stdout
from repotest.core.exceptions import TimeOutException
import os, shutil
from typing import Dict, List
import psutil

logger = logging.getLogger("repotest")


class AbstractLocalRepo(AbstractRepo):
    """
    Base class for managing a local repository.

    Parameters
    ----------
    repo : str
        The repository name.
    base_commit : str
        The base commit for the repository.
    default_cache_folder : str, optional
        Default folder for cache storage (default is '~/.cache/repo_test/').
    default_url : str, optional
        The URL of the repository (default is 'http://github.com').

    Examples
    --------
    >>> repo = AbstractLocalRepo("myrepo", "abc123")
    """

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
    ) -> None:
        super().__init__(
            repo=repo,
            base_commit=base_commit,
            default_cache_folder=default_cache_folder,
            default_url=default_url,
        )

    def subprocess_run(self, command: str, timeout: int) -> Dict[str, str | int]:
        """
        Runs a shell command with a timeout using `subprocess.run`.

        Parameters
        ----------
        command : str
            The shell command to execute.
        timeout : int
            The maximum number of seconds to wait for execution.

        Returns
        -------
        dict
            A dictionary containing:
            - 'stdout': str, standard output from execution.
            - 'stderr': str, standard error from execution.
            - 'returncode': int, process return code.

        Examples
        --------
        >>> repo = AbstractLocalRepo("myrepo", "abc123")
        >>> repo.subprocess_run("echo 'Hello, World!'", 5)
        {'stdout': 'Hello, World!\\n', 'stderr': '', 'returncode': 0}
        """
        logger.debug("subprocess.run(%s)"%command)
        try:
            result = subprocess.run(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cache_folder,
                text=True,
                timeout=timeout,
            )
            self.stdout = result.stdout
            self.stderr = result.stderr
            self.returncode = result.returncode
        # except subprocess.TimeoutExpired:
        #     self.stdout = ""
        #     self.stderr = f"Test execution timed out after {timeout} seconds."
            self.returncode = -1  # Custom return code for timeout
        except subprocess.TimeoutExpired as e:
            self.stdout = ""
            self.stderr = f"\nTest execution timed out after {timeout} seconds.\n"
            self.returncode = 2
            raise TimeOutException(f"Command execution(local) timed out after {timeout} seconds.") from e
        
        logger.info(f"Process finished with return code: {self.returncode}")

        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
        }

    def subprocess_popen(self, command: str, timeout: int) -> Dict[str, str | int]:
        """
        Runs a shell command asynchronously with real-time streaming.

        Parameters
        ----------
        command : str
            The shell command to execute.
        timeout : int
            The maximum number of seconds to wait for execution.

        Returns
        -------
        dict
            A dictionary containing:
            - 'stdout': str, standard output from execution.
            - 'stderr': str, standard error from execution.
            - 'returncode': int, process return code.

        Examples
        --------
        >>> repo = AbstractLocalRepo("myrepo", "abc123")
        >>> repo.subprocess_popen("echo 'Hello'", 5)
        {'stdout': 'Hello\\n', 'stderr': '', 'returncode': 0}
        """
        logger.debug("subprocess.Popen(%s)"%command)
        process = subprocess.Popen(
            command, 
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cache_folder,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        #This is not going to work at max
        # ToDo: fix this to use 1 fixed cpu per 1 pid
        # ToDo: check that this is working at linux
        # This works at linux, but push everything to 1 cpu
        # if DEFAULT_CONTAINER_CPUSET_CPUS:
        #     proc = psutil.Process(process.pid)
        #     # Set CPU affinity for parent            
        #     if hasattr(proc, "cpu_affinity"):  # macOS won't have this
        #         proc.cpu_affinity([int(DEFAULT_CONTAINER_CPUSET_CPUS)])

        self.stdout, self.stderr = "", ""

        try:
            for line in iter(process.stdout.readline, ""):
                if line:
                    logger.debug(line.strip())
                    self.stdout += line

            for line in iter(process.stderr.readline, ""):
                if line:
                    logger.warning(line.strip())
                    self.stderr += line

            process.wait(timeout)

        except subprocess.TimeoutExpired as e:
            process.kill()
            self.stderr += f"\nTest execution timed out after {timeout} seconds.\n"
            self.returncode = 2
            raise TimeOutException(f"Command execution(local) timed out after {timeout} seconds.") from e
        
        self.returncode = process.returncode

        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
        }
    
    def clean_dirs(self, dir_paths: List[str]) -> bool:
        """Cleanup some dir with all subdirs and files using an Alpine container."""
        logger.debug("Remove dirs: %s", ', '.join(dir_paths))
        try:
            for dir_path in dir_paths:
                if os.path.exists(dir_path):  # Check if path exists first
                    shutil.rmtree(dir_path)  # Replaces the manual recursive deletion
            return True
        except Exception as e:
            logger.error(e, exc_info=True)
            return False
        
    #ToDo: test that refactored verson works correctly
    # @classmethod
    # def _clean_dir_recursive(cls, dir_path: str):
    #     #ToDo: use shutil.rmtree()
    #     for file_or_dir in os.listdir(dir_path):
    #         path = os.path.join(dir_path, file_or_dir)
    #         if os.path.isfile(path):
    #             os.remove(path)
    #         elif os.path.isdir(path):
    #             cls._clean_dir_recursive(path)
    #     os.rmdir(dir_path)
    #     return None

    # def clean_dirs(self, dir_paths: List[str]) -> bool:
    #     """
    #     Cleanup some dir with all subdirs and files using an Alpine container.
    #     """
    #     paths_txt = ", ".join(dir_paths)
    #     logger.debug(f"Remove dirs: {paths_txt}")
    #     try:
    #         for dir_path in dir_paths:
    #             self._clean_dir_recursive(dir_path)
    #         return True
    #     except Exception as e:
    #         logger.error(e)
    #         return False
            
    @abstractmethod
    def build_env(self, command):
        pass
    
    @abstractmethod
    def run_test(self, command):
        pass
import os
import docker
from docker.errors import DockerException
from repotest.core.base import AbstractRepo
from repotest.core.docker.base import AbstractDockerRepo
from repotest.constants import DEFAULT_EVAL_TIMEOUT_INT, DEFAULT_BUILD_TIMEOUT_INT, DEFAULT_CACHE_FOLDER
import time
from repotest.parsers.java.maven_stdout import analyze_maven_stdout
from repotest.core.exceptions import TimeOutException
from repotest.parsers.java.surefire_report import (
    find_test_reports,
    parse_xml_test_report,
    group_test_cases_by_status,
    )
import logging
from functools import cached_property

logger = logging.getLogger("repotest")

class JavaDockerRepo(AbstractDockerRepo):
    """
    A class for managing and testing Java repositories in a Docker container.
    """
    def __init__(self, 
                 repo: str, 
                 base_commit: str,
                 default_cache_folder: str = DEFAULT_CACHE_FOLDER, 
                 default_url: str = 'http://github.com',
                 image_name: str = "maven:3.9.9-eclipse-temurin-23-alpine",
                 cache_mode: str = "volume"
                 ) -> None:
        """
        Initializes the Docker repository manager.

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
        image_name : str, optional
            The Docker image name to use (default is "maven:3.9.9-eclipse-temurin-23-alpine").
        cache_mode : str, optional
            The cache mode to use, must be one of ('download', 'shared', 'local', 'volume') (default is "volume").
        """
        super().__init__(repo=repo,
                         base_commit=base_commit,
                         default_cache_folder=default_cache_folder,
                         default_url=default_url,
                         image_name=image_name,
                         cache_mode=cache_mode)
    
    @cached_property
    def user_mvn_folder(self) -> str:
        """
        Get the user's local Maven repository folder.

        Returns
        -------
        str
            The path to the user's Maven repository folder.
        """
        return os.path.expanduser("~/.m2/repository")
    
    @cached_property
    def local_mvn_folder(self) -> str:
        """
        Get the local cache Maven repository folder.

        Returns
        -------
        str
            The path to the local Maven repository folder.
        """
        return os.path.join(
            self.cache_folder, 
            ".m2/repository"
        )
    
    def build_env(self, 
                  command: str,
                  timeout: int = DEFAULT_BUILD_TIMEOUT_INT
                 ) -> None:
        """
        Build the environment inside the Docker container.

        Parameters
        ----------
        command : str
            The command to execute inside the container.
        timeout : int, optional
            The maximum execution time allowed for the command (default is DEFAULT_BUILD_TIMEOUT_INT).
        """
        logger.info("build_env(%s, %s)"%(command, timeout))
        logger.warning("build_env for %s is not implemented yet"%self)
        pass

    def change_file_realcode(self, fn_relative, left_context: str, gt: str, right_context: str):
        #ToDo: create one universal method at BASE
        assert self.file_contain(fn_relative, left_context)
        
        right_context = right_context
        while right_context and right_context[-1] == '\n':
            right_context = right_context[:-1]
        
        assert self.file_contain(fn_relative, right_context)
        # Есть подозрение, что ошибки форматирования вызваны
        # избыточными отступами. И часто левая и правая части уже имеют переносы строк,
        # если их специально не удаляли при "распиле" файла.
        if not left_context.endswith('\n') and not gt.startswith('\n'):
            gt = '\n' + gt
        if not gt.endswith('\n') and not right_context.startswith('\n'):
            gt = gt + '\n'

        self.change_file(fn_relative, 
                         left_context + gt + right_context
                         )
    def run_test(self, 
                 command: str,
                 timeout: int = DEFAULT_EVAL_TIMEOUT_INT
                 ) -> dict:
        """
        Run a test command inside a Docker container.

        Parameters
        ----------
        command : str
            The command to execute inside the container.
        timeout : int, optional
            The timeout in seconds for command execution (default is DEFAULT_EVAL_TIMEOUT_INT).

        Returns
        -------
        dict
            A dictionary containing the test results with the following keys:
            - 'stdout': str, standard output from the test execution.
            - 'stderr': str, standard error from the test execution.
            - 'returncode': int, the return code from the container.
            - 'parser': dict, the parsed Maven stdout results.
        
        Notes
        -----
        The container is run with the repository's cache folder mounted as a volume. 
        The container is automatically cleaned up after execution.
        """
        logger.debug("mvn_load_mode %s" % self.cache_mode)
        if self.cache_mode == 'build':
            raise NotImplementedError("Build mode not implemented yet")
        
        #self.container_name = self.default_container_name
        volume_mount = {self.cache_folder: {'bind': self.cache_folder, 'mode': 'rw'}}
        
        if self.cache_mode == "shared":
            mvn_folder = self.user_mvn_folder
            volume_mount[mvn_folder] = {'bind': mvn_folder, 'mode': 'rw'}
            #ToDo: think again about thi logic
            command += f" -Dmaven.repo.local={mvn_folder}"
        elif self.cache_mode == "local":
            mvn_folder = self.local_mvn_folder
            volume_mount[mvn_folder] = {'bind': mvn_folder, 'mode': 'rw'}
            command += f" -Dmaven.repo.local={mvn_folder}"
        elif self.cache_mode == 'volume':
            self.create_volume('maven-cache')
            volume_mount["maven-cache"] = {'bind': "/root/.m2", 'mode': 'rw'}
            command += " -Dmaven.repo.local=/root/.m2"
        
        logger.debug("Running command in Docker container: %s" % command)
        logger.debug("Using image: %s" % self.image_name)
        logger.debug("Mounting volume: %s to container." % self.cache_folder)
        
        self.start_container(image_name=self.image_name,
                             container_name=self.container_name,
                             volumes=volume_mount,
                             working_dir=self.cache_folder
                            )
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c '{command}'", timeout=timeout)
        except TimeOutException:
            logger.critical("Timeout exception %s"%self)
            self.return_code = 2
            self.stderr = b'Timeout exception'
        self.evaluation_time = time.time() - self.evaluation_time

        self.stop_container()
        self._convert_std_from_bytes_to_str()
        
        report = []
        test_reports_paths = find_test_reports(self.cache_folder)
        for report_path in test_reports_paths:
            testsuite = parse_xml_test_report(report_path)
            entry = group_test_cases_by_status(testsuite)
            report.append(entry)
        
        return {
                'stdout': self.stdout,
                'stderr': self.stderr,
                'std': self.std,
                'returncode': self.return_code,
                "parser": analyze_maven_stdout(stdout=self.stdout, 
                                               full_path=self.default_cache_folder),
                "time": self.evaluation_time,
                "parser_xml": report # ToDo: rename parser_xml -> report
              }

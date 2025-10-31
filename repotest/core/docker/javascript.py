import json
import logging
import os
import time
from enum import Enum, auto
from functools import cached_property
from typing import Dict, Literal, Optional

from docker.errors import APIError, ImageNotFound
from repotest.constants import (DEFAULT_BUILD_TIMEOUT_INT,
                                DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT,
                                DOCKER_PYTHON_DEFAULT_IMAGE)
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException
from repotest.parsers.python.javascript_stout import parse_test_stdout
from repotest.core.docker.types import CacheMode
import xmltodict

logger = logging.getLogger("repotest")
    

class JavaScriptDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Python repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = "node:22",
        cache_mode: CacheMode = "volume",
    ) -> None:
        super().__init__(
            repo=repo,
            base_commit=base_commit,
            default_cache_folder=default_cache_folder,
            default_url=default_url,
            image_name=image_name,
            cache_mode=cache_mode,
        )

      
    @cached_property
    def _user_npm_cache(self) -> str:
        return os.path.expanduser("~/.npm")
    
    @cached_property
    def _local_npm_cache(self) -> str:
        return os.path.join(self.cache_folder, ".npm_cache")
    
    @cached_property
    def _local_javascript_cache(self) -> str:
        return os.path.join(self.cache_folder, ".javascript_cache")
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("npm-cache")
            self.create_volume("javascript-cache")
            volumes["npm-cache"] = {"bind": "/root/.npm", "mode": "rw"}
            volumes["javascript-cache"] = {"bind": "/root/.cache/javascript", "mode": "rw"}
        elif self.cache_mode == "shared":
            if os.path.exists(self._user_npm_cache):
                volumes[self._user_npm_cache] = {"bind": "/root/.npm", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_npm_cache, exist_ok=True)
            os.makedirs(self._local_javascript_cache, exist_ok=True)
            volumes[self._local_npm_cache] = {"bind": "/root/.npm", "mode": "rw"}
            volumes[self._local_javascript_cache] = {"bind": "/root/.cache/javascript", "mode": "rw"}
        
        return volumes

    def build_env(
        self,
        command: str = "npm install --legacy-peer-deps --loglevel=error;npm install mocha-junit-reporter --legacy-peer-deps --loglevel=error",
        timeout: int = DEFAULT_BUILD_TIMEOUT_INT,
        commit_image=True,
        stop_container=True,
        push_image=False,
    ) -> Dict[str, object]:
        """Build the environment inside the Docker container."""
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")  # build_dir')

        logger.info(
            "Starting container",
            extra={
                "command": command,
                "image": self.image_name,
                "volumes": volumes,
            },
        )

        self.start_container(
            image_name=self.image_name,
            container_name=self.container_name,
            volumes=volumes,
            working_dir="/run_dir",  # build_dir'
        )
        command = "ulimit -n 65535;\n" + command
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c '{command}'", timeout=timeout)
        except TimeOutException:
            logger.error("Timeout exception during build_env")
            self.return_code = 2
            self.stderr += b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()

        if self._FALL_WITH_TIMEOUT_EXCEPTION:
            raise TimeOutException(f"Command '{command}' timed out after {timeout}s.")

        if commit_image:
            self._commit_container_image()

        if push_image:
            self.push_image()

        if stop_container:
            self.stop_container()

        return self._format_results()

    def _image_exists(self, name: str) -> bool:
        """Check if a Docker image exists."""
        try:
            self.docker_client.images.get(name)
            return True
        except ImageNotFound:
            return False
        except APIError as e:
            logger.warning(f"Docker API error when checking image: {e}")
            return False

    @property
    def was_build(self) -> bool:
        """Check if the image was already built."""
        return self._image_exists(self.default_image_name)

    def _mock_path(self, command: str) -> str:
        """Ensure PATH and PYTHONPATH are set correctly."""
        prefix = """ulimit -n 65535;"""
        # For symplicity we are working in mount directory
        # echo "">report_pytest.json; - create the file, without this line, there is a 30% change of OSError
        # Normal way to fix it - not working at mount directory, but it will overcomplex the whole project a lot
        return command if command.startswith(prefix) else prefix + command
    
    def read_mocha_xml(self):
        fn_mocha = os.path.join(self.cache_folder, 'test-results.xml')
        if not os.path.exists(fn_mocha):
            logger.critical("file %s not exist (full: %s)", "test-results.xml", fn)
            return {}
        
        dct = xmltodict.parse(open(fn_mocha, "r").read())
        assert 'summary' not in dct

        n_total = int(dct['testsuites']['@tests'])
        n_failed = int(dct['testsuites']['@failures'])
        
        dct_summary = {'total': n_total,
                       'passed': n_total - n_failed,
                       'failed': n_failed,
                       'collected': n_total
                      }
        
        # I want to have summary first order
        return {"summary": dct_summary, **dct}

    
    def read_jest_json(self):
        fn_jest = os.path.join(self.cache_folder, 'jest-results.json')
        if not os.path.exists(fn_jest):
            logger.critical("file %s not exist (full: %s)", "test-results.xml", fn)
            return {}

        dct = json.load(open(fn_jest, "r"))
        assert 'summary' not in dct

        n_total = dct['numTotalTests']
        n_passed = dct['numPassedTests']
        n_failed = dct['numFailedTests'] + dct['numPendingTests'] + dct['numTodoTests']

        dct_summary = {'total': n_total,
                       'passed': n_passed,
                       'failed': n_failed,
                       'collected': n_total
                    }

        # I want to have summary first order
        return {"summary": dct_summary, **dct}

    def read_jest_or_mocha(self):
        fn_mocha = os.path.join(self.cache_folder, 'test-results.xml')
        fn_jest  = os.path.join(self.cache_folder, 'jest-results.json')

        test_exist_mocha = os.path.exists(fn_mocha)
        test_exist_jest = os.path.exists(fn_jest)

        if test_exist_mocha & test_exist_jest:
            logger.critical("Found mocha and jest mocha=%s, jest=%s", fn_mocha, fn_jest)
            return {"mocha": self.read_mocha_xml(),
                    "jest": self.read_jest_json(),
                    }
        elif not (test_exist_mocha | test_exist_jest):
            logger.critical("There are no mocha or jest results")
            return {}
        elif test_exist_mocha:
            logger.debug("Find mocha test")
            return self.read_mocha_xml()
        elif test_exist_jest:
            logger.debug("Find jest test")
            return self.read_jest_json()
        
        raise ValueError("Unexpected behaviour, not all corner cases were processeded")

    def run_test(
        self,
        command: str = "npm test -- --reporter mocha-junit-reporter",
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
        stop_container: bool = True,
    ) -> Dict[str, object]:
        """Run tests inside the Docker container."""
        #ToDo: move workdir to constants
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(
            image_name=self.image_name,
            container_name=self.container_name,
            volumes=volumes,
            working_dir="/run_dir",
        )

        command = self._mock_path(command)

        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c '{command}'", timeout=timeout)
        except TimeOutException:
            logger.error("Timeout exception during test execution")
            self.return_code = 2
            self.stderr = b"Timeout exception"
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        report = self.read_jest_or_mocha()

        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()

        return self._format_results(report = report)

    def _format_results(self, report: Optional[Dict] = None) -> Dict[str, object]:
        """Format results into a consistent dictionary structure."""
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "std": self.std,
            "returncode": self.return_code,
            "parser": parse_test_stdout(self.stdout),
            "report": report,
            "time": self.evaluation_time,
            "run_id": self.run_id,
        }

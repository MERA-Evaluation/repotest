import json
import logging
import os
import time
from enum import Enum, auto
from functools import cached_property
from typing import Dict, Optional, Literal

import docker
from docker.errors import DockerException, APIError, ImageNotFound

from repotest.core.docker.base import AbstractDockerRepo
from repotest.constants import (
    DEFAULT_EVAL_TIMEOUT_INT,
    DEFAULT_BUILD_TIMEOUT_INT,
    DEFAULT_CACHE_FOLDER,
    DOCKER_PYTHON_DEFAULT_IMAGE,
)
from repotest.core.exceptions import TimeOutException
from repotest.parsers.python.pytest_stdout import parse_pytest_stdout

logger = logging.getLogger("repotest")


class CacheMode(Enum):
    DOWNLOAD = auto()
    SHARED = auto()
    LOCAL = auto()
    VOLUME = auto()


class PythonDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Python repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = DOCKER_PYTHON_DEFAULT_IMAGE,
        cache_mode: Literal["download", "shared", "local", "volume"] = "volume",
    ) -> None:
        super().__init__(
            repo=repo,
            base_commit=base_commit,
            default_cache_folder=default_cache_folder,
            default_url=default_url,
            image_name=image_name,
            cache_mode=cache_mode,
        )
    
    # @cached_property
    # def container_name(self):
    #     return self.default_container_name + "-" + self.run_id

    @cached_property
    def _user_pip_cache(self) -> str:
        return os.path.expanduser("~/.cache/pip")

    @cached_property
    def _local_pip_cache(self) -> str:
        return os.path.join(self.cache_folder, ".pip_cache")

    def _setup_container_volumes(self, workdir = None) -> Dict[str, Dict[str, str]]:
        """Configure volume mounts based on cache mode."""
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_pip_cache] = {"bind": self._user_pip_cache, "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_pip_cache] = {"bind": self._local_pip_cache, "mode": "rw"}
        elif self.cache_mode == 'volume':
            self.create_volume('pip-cache')
            logger.debug("cache_mode=volume")
            volumes["pip-cache"] = {'bind': "/root/.cache/pip", 'mode': 'rw'}
        
        return volumes

    def build_env(
        self, command: str, timeout: int = DEFAULT_BUILD_TIMEOUT_INT,
        commit_image = True,
        stop_container = True,
        push_image = False
    ) -> Dict[str, object]:
        """Build the environment inside the Docker container."""
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir='/run_dir') #build_dir')

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
            working_dir='/run_dir' #build_dir'
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

    def _commit_container_image(self, retries: int = 3, delay: int = 10) -> None:
        """Commit the container to an image with retry logic."""
        for attempt in range(retries):
            try:
                self.container.commit(self.default_image_name)
                logger.info("Successfully committed container to image")
                self.image_name = self.default_image_name
                return
            except APIError as e:
                logger.warning(f"Failed to commit image (attempt {attempt + 1}): {e}")
                if attempt == retries - 1:
                    raise
                time.sleep(delay)

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

    def __call__(
        self,
        command_build: str,
        command_test: str,
        image_name_from: str = DOCKER_PYTHON_DEFAULT_IMAGE,
        timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
        timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT,
    ) -> Dict[str, object]:
        """Run build and test commands in sequence."""
        if not self.was_build:
            logger.debug(f"Building image from {self.default_image_name}")
            self.build_env(command=command_build, timeout=timeout_build)
        elif self.image_name != self.default_image_name:
            self.image_name = self.default_image_name

        logger.info("Starting test execution")
        return self.run_test(command=command_test, timeout=timeout_test)

    def _mock_path(self, command: str) -> str:
        """Ensure PATH and PYTHONPATH are set correctly."""
        prefix = """export PYTHONPATH=.;
export PATH=$PYTHONPATH:$PATH;
echo "">report_pytest.json;
ulimit -n 65535;
"""
        # For symplicity we are working in mount directory
        # echo "">report_pytest.json; - create the file, without this line, there is a 30% change of OSError
        # Normal way to fix it - not working at mount directory, but it will overcomplex the whole project a lot
        return command if command.startswith(prefix) else prefix + command

    def run_test(
        self,
        command: str = "pytest tests",
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
        stop_container: bool = True
    ) -> Dict[str, object]:
        """Run tests inside the Docker container."""
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(
            image_name=self.image_name,
            container_name=self.container_name,
            volumes=volumes,
            working_dir="/run_dir"
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
        pytest_json = {}
        fn_json_result = os.path.join(self.cache_folder, "report_pytest.json")

        if os.path.exists(fn_json_result):
            try:
                with open(fn_json_result, "r") as f:
                    pytest_json = json.load(f)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON report at {fn_json_result}")

        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()

        return self._format_results(pytest_json=pytest_json)

    def _format_results(self, pytest_json: Optional[Dict] = None) -> Dict[str, object]:
        """Format results into a consistent dictionary structure."""
        return {"stdout": self.stdout,
                "stderr": self.stderr,
                "std": self.std,
                "returncode": self.return_code,
                "parser": parse_pytest_stdout(self.stdout),
                "report": pytest_json or {},
                "time": self.evaluation_time,
                "run_id": self.run_id,
            }
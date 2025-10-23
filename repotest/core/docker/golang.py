import json
import logging
import os
import time
from functools import cached_property
from typing import Dict, Literal, Optional

from docker.errors import APIError, ImageNotFound
from repotest.constants import (
    DEFAULT_BUILD_TIMEOUT_INT,
    DEFAULT_CACHE_FOLDER,
    DEFAULT_EVAL_TIMEOUT_INT,
)
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException

logger = logging.getLogger("repotest")


def parse_go_test_json(stdout: str) -> Dict[str, object]:
    """
    Parse Go test JSON output from `go test -json` command.
    
    Parameters
    ----------
    stdout : str
        Raw stdout from go test -json command
        
    Returns
    -------
    Dict[str, object]
        Parsed test results with packages and tests information
        
    Examples
    --------
    >>> output = '{"Time":"2024-01-01T10:00:00Z","Action":"pass","Package":"example/test","Elapsed":0.1}'
    >>> result = parse_go_test_json(output)
    >>> result['packages']['example/test']['status']
    'pass'
    """
    if not stdout or not stdout.strip():
        return {
            "packages": {},
            "tests": {},
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        }

    packages = {}
    tests = {}
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    skipped_tests = 0

    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            action = event.get("Action", "")
            package = event.get("Package", "")
            test = event.get("Test", "")
            elapsed = event.get("Elapsed", 0)

            if package and not test:
                if package not in packages:
                    packages[package] = {
                        "name": package,
                        "status": None,
                        "elapsed": 0,
                    }
                if action in ("pass", "fail", "skip"):
                    packages[package]["status"] = action
                    packages[package]["elapsed"] = elapsed

            if test:
                test_key = f"{package}/{test}"
                if test_key not in tests:
                    tests[test_key] = {
                        "package": package,
                        "name": test,
                        "status": None,
                        "elapsed": 0,
                        "output": [],
                    }
                if action in ("pass", "fail", "skip"):
                    tests[test_key]["status"] = action
                    tests[test_key]["elapsed"] = elapsed
                    total_tests += 1
                    if action == "pass":
                        passed_tests += 1
                    elif action == "fail":
                        failed_tests += 1
                    elif action == "skip":
                        skipped_tests += 1
                elif action == "output" and "Output" in event:
                    tests[test_key]["output"].append(event["Output"])

        except (json.JSONDecodeError, KeyError, ValueError):
            continue

    return {
        "packages": packages,
        "tests": tests,
        "summary": {
            "total": total_tests,
            "passed": passed_tests,
            "failed": failed_tests,
            "skipped": skipped_tests,
        },
    }


class GoLangDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Go repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = "golang:latest",
        cache_mode: Literal["download", "shared", "local", "volume"] = "volume",
    ) -> None:
        """
        Initialize Go Docker repository manager.

        Parameters
        ----------
        repo : str
            Repository name in format "owner/repo"
        base_commit : str
            Git commit hash to test
        default_cache_folder : str, optional
            Cache directory path
        default_url : str, optional
            Git repository base URL
        image_name : str, optional
            Docker image for Go environment
        cache_mode : str, optional
            Cache mode: "local", "shared", "download", or "volume"
        """
        super().__init__(
            repo=repo,
            base_commit=base_commit,
            default_cache_folder=default_cache_folder,
            default_url=default_url,
            image_name=image_name,
            cache_mode=cache_mode,
        )
        self.stdout = ""
        self.stderr = ""
        self.std = ""
        self.return_code = 0

    @cached_property
    def _user_go_cache(self) -> str:
        """Get user-level Go cache directory."""
        return os.path.expanduser("~/.cache/go-build")

    @cached_property
    def _local_go_cache(self) -> str:
        """Get local Go cache directory."""
        if not self.cache_folder:
            raise ValueError("cache_folder is not set")
        return os.path.join(self.cache_folder, ".go_cache")

    def _setup_container_volumes(
        self, workdir: Optional[str] = None
    ) -> Dict[str, Dict[str, str]]:
        """
        Configure volume mounts based on cache mode.

        Parameters
        ----------
        workdir : str, optional
            Working directory to mount

        Returns
        -------
        Dict[str, Dict[str, str]]
            Volume configuration dictionary
        """
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_go_cache] = {"bind": self._user_go_cache, "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_go_cache] = {"bind": self._local_go_cache, "mode": "rw"}
        elif self.cache_mode == "volume":
            self.create_volume("go-cache")
            logger.debug("cache_mode=volume for Go")
            volumes["go-cache"] = {"bind": "/go/pkg", "mode": "rw"}

        return volumes

    def build_env(
        self,
        command: str,
        timeout: int = DEFAULT_BUILD_TIMEOUT_INT,
        commit_image: bool = True,
        stop_container: bool = True,
        push_image: bool = False,
    ) -> Dict[str, object]:
        """
        Build the Go environment inside the Docker container.

        Parameters
        ----------
        command : str
            Build command to execute
        timeout : int, optional
            Maximum execution time in seconds
        commit_image : bool, optional
            Whether to commit container to image
        stop_container : bool, optional
            Whether to stop container after build
        push_image : bool, optional
            Whether to push image to registry

        Returns
        -------
        Dict[str, object]
            Build results with stdout, stderr, returncode, time, etc.

        Raises
        ------
        TimeOutException
            If build exceeds timeout
        """
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")

        logger.info(
            "Starting Go build container",
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
            working_dir="/run_dir",
        )

        command = "ulimit -n 65535;\n" + command

        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"sh -c '{command}'", timeout=timeout)
        except TimeOutException:
            logger.error("Timeout exception during Go build_env")
            self.return_code = 2
            self.stderr = self.stderr + b"Timeout exception" if isinstance(self.stderr, bytes) else "Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()

        if self._FALL_WITH_TIMEOUT_EXCEPTION:
            raise TimeOutException(
                f"Command '{command}' timed out after {timeout}s."
            )

        if commit_image:
            self._commit_container_image()

        if push_image:
            self.push_image()

        if stop_container:
            self.stop_container()

        return self._format_results()

    def _commit_container_image(
        self, retries: int = 3, delay: int = 10
    ) -> None:
        """
        Commit the container to an image with retry logic.

        Parameters
        ----------
        retries : int, optional
            Number of retry attempts
        delay : int, optional
            Delay between retries in seconds
        """
        for attempt in range(retries):
            try:
                self.container.commit(self.default_image_name)
                logger.info("Successfully committed Go container to image")
                self.image_name = self.default_image_name
                return
            except APIError as e:
                logger.warning(
                    f"Failed to commit Go image (attempt {attempt + 1}): {e}"
                )
                if attempt == retries - 1:
                    raise
                time.sleep(delay)

    def _image_exists(self, name: str) -> bool:
        """
        Check if a Docker image exists.

        Parameters
        ----------
        name : str
            Image name to check

        Returns
        -------
        bool
            True if image exists, False otherwise
        """
        try:
            self.docker_client.images.get(name)
            return True
        except ImageNotFound:
            return False
        except APIError as e:
            logger.warning(f"Docker API error when checking Go image: {e}")
            return False

    @property
    def was_build(self) -> bool:
        """Check if the Go image was already built."""
        return self._image_exists(self.default_image_name)

    def __call__(
        self,
        command_build: str,
        command_test: str,
        timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
        timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT,
    ) -> Dict[str, object]:
        """
        Run build and test commands in sequence.

        Parameters
        ----------
        command_build : str
            Build command
        command_test : str
            Test command
        timeout_build : int, optional
            Build timeout in seconds
        timeout_test : int, optional
            Test timeout in seconds

        Returns
        -------
        Dict[str, object]
            Test results
        """
        if not self.was_build:
            logger.debug(f"Building Go image from {self.default_image_name}")
            self.build_env(command=command_build, timeout=timeout_build)
        elif self.image_name != self.default_image_name:
            self.image_name = self.default_image_name

        logger.info("Starting Go test execution")
        return self.run_test(command=command_test, timeout=timeout_test)

    def run_test(
        self,
        command: str = "go test -json ./...",
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
        stop_container: bool = True,
    ) -> Dict[str, object]:
        """
        Run Go tests inside the Docker container.

        Parameters
        ----------
        command : str
            Test command to execute
        timeout : int, optional
            Maximum execution time in seconds
        stop_container : bool, optional
            Whether to stop container after tests

        Returns
        -------
        Dict[str, object]
            Test results with parsed output and summary

        Raises
        ------
        TimeOutException
            If tests exceed timeout (optional based on _FALL_WITH_TIMEOUT_EXCEPTION)
        """
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(
            image_name=self.image_name,
            container_name=self.container_name,
            volumes=volumes,
            working_dir="/run_dir",
        )

        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"sh -c '{command}'", timeout=timeout)
        except TimeOutException:
            logger.error("Timeout exception during Go test execution")
            self.return_code = 2
            self.stderr = b"Timeout exception"
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()

        go_test_json = {}
        if self.cache_folder is None:
            fn_json_result = "gotest_results.jsonl"
        else:
            fn_json_result = os.path.join(self.cache_folder, "gotest_results.jsonl")

        if os.path.exists(fn_json_result):
            try:
                with open(fn_json_result, "r") as f:
                    go_test_json = {"raw_output": f.read()}
            except IOError as e:
                logger.warning(
                    f"Failed to read Go test results at {fn_json_result}: {e}"
                )

        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()

        return self._format_results(go_test_json=go_test_json)

    def _format_results(
        self, go_test_json: Optional[Dict] = None
    ) -> Dict[str, object]:
        """
        Format results into a consistent dictionary structure.

        Parameters
        ----------
        go_test_json : Dict, optional
            Parsed test results from file

        Returns
        -------
        Dict[str, object]
            Formatted results dictionary
        """
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "std": self.std,
            "returncode": self.return_code,
            "parser": parse_go_test_json(self.stdout),
            "report": go_test_json or {},
            "time": self.evaluation_time,
            "run_id": self.run_id,
        }

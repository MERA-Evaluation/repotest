import json
import logging
import os
import time
from functools import cached_property
from typing import Dict, Literal, Optional

from docker.errors import APIError, ImageNotFound
from repotest.constants import (DEFAULT_BUILD_TIMEOUT_INT,
                                DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT,
                                DOCKER_PYTHON_DEFAULT_IMAGE)
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException, GitPatchFailed
from repotest.parsers.python.pytest_stdout import parse_pytest_stdout
from repotest.core.types import CacheMode, OutputBuildEnv, OutputTests, OutputSummary

logger = logging.getLogger("repotest")


class PythonDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Python repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = DOCKER_PYTHON_DEFAULT_IMAGE,
        cache_mode: CacheMode = "volume",
        working_mode = 'repo'
    ) -> None:
        super().__init__(
            repo=repo,
            base_commit=base_commit,
            default_cache_folder=default_cache_folder,
            default_url=default_url,
            image_name=image_name,
            cache_mode=cache_mode,
        )
        self.working_mode = working_mode
        if self.working_mode == 'docker':
            self.cp_testbed_rundir()
            self.apply_patch = self.apply_patch_alpine_container
        elif self.working_mode == 'repo':
            pass
        else:
            raise ValueError(f"Unknown working_mode={working_mode}")


    @cached_property
    def _user_pip_cache(self) -> str:
        return os.path.expanduser("~/.cache/pip")

    @cached_property
    def _local_pip_cache(self) -> str:
        return os.path.join(self.cache_folder, ".pip_cache")

    def _setup_container_volumes(self, workdir=None) -> Dict[str, Dict[str, str]]:
        """Configure volume mounts based on cache mode."""
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_pip_cache] = {
                "bind": self._user_pip_cache, "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_pip_cache] = {
                "bind": self._local_pip_cache,
                "mode": "rw",
            }
        elif self.cache_mode == "volume":
            self.create_volume("pip-cache")
            logger.debug("cache_mode=volume")
            volumes["pip-cache"] = {"bind": "/root/.cache/pip", "mode": "rw"}

        return volumes

    def build_env(
        self,
        command: str = "pip install -e .;\npip install pytest pytest-json-report;",
        timeout: int = DEFAULT_BUILD_TIMEOUT_INT,
        commit_image=True,
        stop_container=True,
        push_image=False,
    ) -> OutputBuildEnv:
        """Build the environment inside the Docker container."""
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(
            workdir="/run_dir")  # build_dir')

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
            
            # Copy run_dir to testbed after build completes
            logger.info("Copying /run_dir to /testbed")
            copy_command = "cp -r /run_dir /testbed"
            self.timeout_exec_run(f"bash -c '{copy_command}'", timeout=timeout)
        except TimeOutException:
            logger.error("Timeout exception during build_env")
            self.return_code = 2
            self.stderr += b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()

        if self._FALL_WITH_TIMEOUT_EXCEPTION:
            raise TimeOutException(
                f"Command '{command}' timed out after {timeout}s.")

        if commit_image:
            self._commit_container_image()

        if push_image:
            self.push_image()

        if stop_container:
            self.stop_container()

        return self._format_results(is_build=True)

    # ToDo: remove this is not good abstraction
    def __call__(
        self,
        command_build: str,
        command_test: str,
        image_name_from: str = DOCKER_PYTHON_DEFAULT_IMAGE,
        timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
        timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT,
    ) -> Dict[str, object]:
        # ToDo: delete __call__ everywhere, it was a bad desicion nnot transparent
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
        # For simplicity we are working in mount directory
        # echo "">report_pytest.json; - create the file, without this line, there is a 30% change of OSError
        # Normal way to fix it - not working at mount directory, but it will overcomplex the whole project a lot
        return command if command.startswith(prefix) else prefix + command

    def run_test(
        self,
        command: str = "pytest --json-report --json-report-file=report_pytest.json",
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
        stop_container: bool = True,
    ) -> OutputTests:
        """Run tests inside the Docker container."""

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
        pytest_json = {}
        fn_json_result = os.path.join(self.cache_folder, "report_pytest.json")

        if os.path.exists(fn_json_result):
            try:
                with open(fn_json_result, "r") as f:
                    pytest_json = json.load(f)
            except json.JSONDecodeError:
                logger.warning(
                    f"Failed to parse JSON report at {fn_json_result}")

        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()

        return self._format_results(pytest_json=pytest_json, is_build=False)

    def cp_testbed_rundir(self):
        """This change owner of run folder to root"""
        logger.info("Creating duplicate with all binaries /run_dir -> /testbed")
        volumes = self._setup_container_volumes(workdir="/run_dir/")
        self.start_container(
            image_name=self.image_name,
            container_name=self.container_name,
            volumes=volumes,
            working_dir="/run_dir",
        )
        
        create_folder_cmd = "rm -rf /run_dir/*;cp -r /testbed/* /run_dir/"
        self.timeout_exec_run(f"bash -c '{create_folder_cmd}'", timeout=5)
        self.stop_container()

    def run_testbed(
        self,
        patch: str,
        command: str = "pytest --json-report --json-report-file=report_pytest.json",
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
        stop_container: bool = True,
    ) -> OutputTests:
        """Run tests inside the Docker container from /testbed directory with patch applied."""
        

        # rm -rf /run_dir cp -r /testbed /run_dir
        self.cp_testbed_rundir()

        # Apply patch to cache_folder before starting container
        if patch and patch.strip():
            logger.info("Applying patch to repository")
            try:
                self.apply_patch_alpine_container(patch)
                logger.info("Patch applied successfully")
            except Exception as e:
                logger.error(f"Failed to apply patch: {e}")
                raise GitPatchFailed(f"Failed to apply patch: {e}") from e
        
        volumes = self._setup_container_volumes(workdir="/run_dir/")
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
        pytest_json = {}
        fn_json_result = os.path.join(self.cache_folder, "report_pytest.json")

        if os.path.exists(fn_json_result):
            try:
                with open(fn_json_result, "r") as f:
                    pytest_json = json.load(f)
            except json.JSONDecodeError:
                logger.warning(
                    f"Failed to parse JSON report at {fn_json_result}")

        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()

        return self._format_results(pytest_json=pytest_json, is_build=False)

    def _format_results(self, pytest_json: Optional[Dict] = None, is_build=False) -> OutputBuildEnv | OutputTests:
        """Format results into a consistent dictionary structure."""
        if is_build:
            OutputClass = OutputBuildEnv
        else:
            OutputClass = OutputTests

        parser = parse_pytest_stdout(self.stdout)

        # ToDo: move in abstract class
        # ToDo: types are simmilar for docker and local implementations
        if pytest_json and ('summary' in pytest_json):
            _from = 'report.json'
            summary_dict = pytest_json['summary']
        else:
            _from = 'stdout'
            summary_dict = parser['summary']

        n_passed = (summary_dict.get('passed', 0) + summary_dict.get('xpassed', 0))
        n_failed = (summary_dict.get('error', 0) +
                    summary_dict.get('failed', 0) +
                    summary_dict.get('xfailed', 0))
        n_error = summary_dict.get('error', 0)

        if (n_passed > 0) and (n_failed == 0):
            status = "Ok"
        elif (n_passed == 0):
            status = "Fail"
        else:
            status = 'Unknown'

        summary = OutputSummary(status=status,
                                passed=n_passed,
                                failed=n_failed,
                                total=n_passed + n_failed,
                                error=n_error,
                                collected=summary_dict.get("collected", -1),
                                _from=_from
                                )

        return OutputClass(stdout=self.stdout,
                           stderr=self.stderr,
                           std=self.std,
                           returncode=self.return_code,
                           parser=parse_pytest_stdout(self.stdout),
                           report=pytest_json or {},
                           time=self.evaluation_time,
                           run_id=self.run_id,
                           summary=summary
                           )

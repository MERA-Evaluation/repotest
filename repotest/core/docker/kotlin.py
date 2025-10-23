import json, logging, os, re, time
from functools import cached_property
from typing import Dict, Literal, Optional
from docker.errors import APIError, ImageNotFound
from repotest.constants import DEFAULT_BUILD_TIMEOUT_INT, DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException

logger = logging.getLogger("repotest")

def parse_kotlin_test_output(stdout: str) -> Dict[str, object]:
    """Parse Kotlin test output."""
    if not stdout:
        return {"tests": [], "summary": {"total": 0, "passed": 0, "failed": 0}, "status": "unknown"}
    
    result = {"tests": [], "summary": {"total": 0, "passed": 0, "failed": 0}, "status": "unknown", "raw_output": stdout}
    passed_patterns = [r"(\d+)\s+passed", r"(\d+)\s+test[s]?\s+passed", r"OK\s+\((\d+)\s+test"]
    failed_patterns = [r"(\d+)\s+failed", r"(\d+)\s+test[s]?\s+failed", r"FAIL(?:ED)?[:\s]+(\d+)"]
    
    for pat in passed_patterns:
        m = re.search(pat, stdout, re.IGNORECASE)
        if m:
            result["summary"]["passed"] = int(m.group(1))
            break
    
    for pat in failed_patterns:
        m = re.search(pat, stdout, re.IGNORECASE)
        if m:
            result["summary"]["failed"] = int(m.group(1))
            break
    
    result["summary"]["total"] = result["summary"]["passed"] + result["summary"]["failed"]
    result["status"] = "passed" if result["summary"]["failed"] == 0 and result["summary"]["total"] > 0 else ("failed" if result["summary"]["failed"] > 0 else "unknown")
    
    return result

class KotlinDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Kotlin repositories in a Docker container."""
    
    def __init__(self, repo: str, base_commit: str, default_cache_folder: str = DEFAULT_CACHE_FOLDER,
                 default_url: str = "http://github.com", image_name: str = "gradle:jdk11",
                 cache_mode: Literal["download", "shared", "local", "volume"] = "volume") -> None:
        super().__init__(repo=repo, base_commit=base_commit, default_cache_folder=default_cache_folder,
                         default_url=default_url, image_name=image_name, cache_mode=cache_mode)
        self.stdout = ""
        self.stderr = ""
        self.std = ""
        self.return_code = 0
    
    @cached_property
    def _user_kotlin_cache(self) -> str:
        return os.path.expanduser("~/.cache/kotlin")
    
    @cached_property
    def _local_kotlin_cache(self) -> str:
        return os.path.join(self.cache_folder, ".kotlin_cache")
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        if self.cache_mode == "volume":
            self.create_volume("kotlin-cache")
            volumes["kotlin-cache"] = {"bind": "/root/.cache/kotlin", "mode": "rw"}
        return volumes
    
    def build_env(self, command: str, timeout: int = DEFAULT_BUILD_TIMEOUT_INT, commit_image: bool = True,
                  stop_container: bool = True, push_image: bool = False) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c '{command}'", timeout=timeout)
        except TimeOutException:
            self.return_code = 2
            self.stderr += b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        if self._FALL_WITH_TIMEOUT_EXCEPTION:
            raise TimeOutException(f"Command timed out after {timeout}s.")
        if commit_image:
            self._commit_container_image()
        if push_image:
            self.push_image()
        if stop_container:
            self.stop_container()
        return self._format_results()
    
    def _commit_container_image(self, retries: int = 3, delay: int = 10) -> None:
        for attempt in range(retries):
            try:
                self.container.commit(self.default_image_name)
                self.image_name = self.default_image_name
                return
            except APIError:
                if attempt == retries - 1:
                    raise
                time.sleep(delay)
    
    def _image_exists(self, name: str) -> bool:
        try:
            self.docker_client.images.get(name)
            return True
        except (ImageNotFound, APIError):
            return False
    
    @property
    def was_build(self) -> bool:
        return self._image_exists(self.default_image_name)
    
    def __call__(self, command_build: str, command_test: str, timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
                 timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT) -> Dict[str, object]:
        if not self.was_build:
            self.build_env(command=command_build, timeout=timeout_build)
        return self.run_test(command=command_test, timeout=timeout_test)
    
    def run_test(self, command: str = "./gradlew test", timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
                 stop_container: bool = True) -> Dict[str, object]:
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c '{command}'", timeout=timeout)
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        test_results = {}
        fn_result = os.path.join(self.cache_folder, "test_results.txt")
        if os.path.exists(fn_result):
            try:
                with open(fn_result, "r") as f:
                    if fn_result.endswith(".json"):
                        test_results = json.load(f)
                    else:
                        test_results = {"raw_output": f.read()}
            except (IOError, json.JSONDecodeError):
                pass
        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()
        return self._format_results(test_json=test_results)
    
    def _format_results(self, test_json: Optional[Dict] = None) -> Dict[str, object]:
        return {"stdout": self.stdout, "stderr": self.stderr, "std": self.std, "returncode": self.return_code,
                "parser": parse_kotlin_test_output(self.stdout), "report": test_json or {},
                "time": self.evaluation_time, "run_id": self.run_id}

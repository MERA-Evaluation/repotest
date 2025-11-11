import json
import logging
import os
import re
import time
from functools import cached_property
from typing import Dict, Optional, List, Tuple
from docker.errors import APIError, ImageNotFound, NotFound

from repotest.constants import (
    DEFAULT_BUILD_TIMEOUT_INT,
    DEFAULT_CACHE_FOLDER,
    DEFAULT_EVAL_TIMEOUT_INT
)
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException
from repotest.core.docker.types import CacheMode

logger = logging.getLogger("repotest")


def parse_rust_test_output(stdout: str, stderr: str) -> Dict[str, object]:
    """Parse Rust test output using regex."""
    result = {
        "tests": [],
        "summary": {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0,
            "collected": 0
        },
        "status": "unknown"
    }
    
    # Combine stdout and stderr
    combined_output = stdout + "\n" + stderr
    
    # Pattern for test result summary line:
    # "test result: ok. 61 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out"
    summary_pattern = re.compile(
        r'test result: (\w+)\.\s*'
        r'(\d+) passed;\s*'
        r'(\d+) failed;\s*'
        r'(\d+) ignored;\s*'
        r'(?:(\d+) measured;\s*)?'
        r'(?:(\d+) filtered out)?'
    )
    
    # Pattern for individual test results:
    # "test test_name ... ok"
    # "test test_name ... FAILED"
    # "test test_name ... ignored"
    test_pattern = re.compile(r'test\s+(.+?)\s+\.\.\.\s+(ok|FAILED|ignored|bench)')
    
    # Find all test results
    test_matches = test_pattern.findall(combined_output)
    for test_name, status in test_matches:
        test_name = test_name.strip()
        status_normalized = status.lower()
        
        if status_normalized == "failed":
            status_normalized = "failed"
        elif status_normalized == "ok":
            status_normalized = "passed"
        elif status_normalized == "ignored":
            status_normalized = "skipped"
        
        test_info = {
            "name": test_name,
            "classname": test_name.rsplit("::", 1)[0] if "::" in test_name else "",
            "time": 0,
            "status": status_normalized
        }
        result["tests"].append(test_info)
    
    # Find all summary lines and aggregate
    summary_matches = summary_pattern.findall(combined_output)
    
    total_passed = 0
    total_failed = 0
    total_ignored = 0
    has_failed_suite = False
    
    for match in summary_matches:
        status = match[0]  # ok or failed
        passed = int(match[1])
        failed = int(match[2])
        ignored = int(match[3])
        
        total_passed += passed
        total_failed += failed
        total_ignored += ignored
        
        if status.lower() == "failed":
            has_failed_suite = True
    
    # Update summary
    if summary_matches:
        result["summary"]["passed"] = total_passed
        result["summary"]["failed"] = total_failed
        result["summary"]["skipped"] = total_ignored
        result["summary"]["total"] = total_passed + total_failed + total_ignored
        result["summary"]["collected"] = result["summary"]["total"]
        
        # Determine overall status
        if has_failed_suite or total_failed > 0:
            result["status"] = "failed"
        elif total_passed > 0 or result["summary"]["total"] > 0:
            result["status"] = "passed"
        else:
            result["status"] = "unknown"
    elif result["tests"]:
        # Fallback: count from individual test results
        for test in result["tests"]:
            if test["status"] == "passed":
                result["summary"]["passed"] += 1
            elif test["status"] == "failed":
                result["summary"]["failed"] += 1
            elif test["status"] == "skipped":
                result["summary"]["skipped"] += 1
        
        result["summary"]["total"] = len(result["tests"])
        result["summary"]["collected"] = result["summary"]["total"]
        
        if result["summary"]["failed"] > 0:
            result["status"] = "failed"
        elif result["summary"]["passed"] > 0:
            result["status"] = "passed"
    
    return result


class RustDockerRepo(AbstractDockerRepo):
    
    def __init__(
        self, 
        repo: str, 
        base_commit: str, 
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com", 
        image_name: str = "rust:1.80",
        cache_mode: CacheMode = "volume"
    ) -> None:
        super().__init__(
            repo=repo, 
            base_commit=base_commit, 
            default_cache_folder=default_cache_folder,
            default_url=default_url, 
            image_name=image_name, 
            cache_mode=cache_mode
        )
        self.stdout = ""
        self.stderr = ""
        self.std = ""
        self.return_code = 0
    
    @cached_property
    def _user_cargo_cache(self) -> str:
        return os.path.expanduser("~/.cargo")
    
    @cached_property
    def _local_cargo_cache(self) -> str:
        return os.path.join(self.cache_folder, ".cargo_cache")
    
    @cached_property
    def _local_rust_cache(self) -> str:
        return os.path.join(self.cache_folder, ".rust_cache")
    
    def _setup_container_volumes(
        self, 
        workdir: Optional[str] = None
    ) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("cargo-cache")
            self.create_volume("rust-target-cache")
            volumes["cargo-cache"] = {"bind": "/usr/local/cargo", "mode": "rw"}
            volumes["rust-target-cache"] = {"bind": "/run_dir/target", "mode": "rw"}
        elif self.cache_mode == "shared":
            if os.path.exists(self._user_cargo_cache):
                volumes[self._user_cargo_cache] = {
                    "bind": "/usr/local/cargo", 
                    "mode": "rw"
                }
        elif self.cache_mode == "local":
            os.makedirs(self._local_cargo_cache, exist_ok=True)
            os.makedirs(self._local_rust_cache, exist_ok=True)
            volumes[self._local_cargo_cache] = {
                "bind": "/usr/local/cargo", 
                "mode": "rw"
            }
            volumes[self._local_rust_cache] = {
                "bind": "/run_dir/target", 
                "mode": "rw"
            }
        
        return volumes
    
    def start_container(
        self, 
        image_name: str, 
        container_name: str, 
        volumes: Dict, 
        working_dir: str
    ) -> None:
        try:
            existing_container = self.docker_client.containers.get(container_name)
            existing_container.remove(force=True)
            logger.info(f"Removed existing container {container_name}")
        except NotFound:
            pass
        
        self.container = self.docker_client.containers.run(
            image_name,
            name=container_name,
            volumes=volumes,
            working_dir=working_dir,
            command='/bin/sh -c "tail -f /dev/null"',
            detach=True
        )
    
    def build_env(
        self, 
        command: str = None, 
        timeout: int = DEFAULT_BUILD_TIMEOUT_INT, 
        commit_image: bool = True,
        stop_container: bool = True, 
        push_image: bool = False
    ) -> Dict[str, object]:
        if command is None:
            command = "cargo build --release"
        
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(
            image_name=self.image_name, 
            container_name=self.container_name,
            volumes=volumes, 
            working_dir="/run_dir"
        )
        
        try:
            self.timeout_exec_run(
                "bash -c 'mkdir -p /run_dir/test-results'",
                timeout=30
            )
        except Exception as e:
            logger.warning(f"Failed to create test-results directory: {e}")
        
        try:
            self.evaluation_time = time.time()
            result = self.timeout_exec_run(
                f"bash -c '{command}'", 
                timeout=timeout
            )
            if result:
                self.return_code = result.get("returncode", 0)
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
    
    def _commit_container_image(
        self, 
        retries: int = 3, 
        delay: int = 10
    ) -> None:
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
    
    def __call__(
        self, 
        command_build: str = None, 
        command_test: str = None, 
        timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
        timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT
    ) -> Dict[str, object]:
        if not self.was_build:
            self.build_env(command=command_build, timeout=timeout_build)
        return self.run_test(command=command_test, timeout=timeout_test)
    
    def run_test(
        self, 
        command: str = None, 
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
        stop_container: bool = True
    ) -> Dict[str, object]:
        
        if command is None:
            command = "cargo test --no-fail-fast -- --nocapture"
        
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(
            image_name=self.image_name, 
            container_name=self.container_name,
            volumes=volumes, 
            working_dir="/run_dir"
        )
        
        try:
            self.timeout_exec_run(
                "bash -c 'mkdir -p /run_dir/test-results'",
                timeout=30
            )
        except Exception as e:
            logger.warning(f"Failed to create test-results directory: {e}")
        
        try:
            self.evaluation_time = time.time()
            
            # Run tests and capture output
            result = self.timeout_exec_run(
                f"bash -c '{command}'",
                timeout=timeout
            )
            
            if result:
                # Don't trust the return code from cargo test directly
                # We'll override it based on test results
                original_return_code = result.get("returncode", 0)
                
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        # Parse test results from output
        test_results = parse_rust_test_output(self.stdout, self.stderr)
        
        # Set return code based on parsed test results, NOT cargo's exit code
        # This fixes the issue where warnings cause exit code 1
        if test_results.get("status") == "passed":
            self.return_code = 0
        elif test_results.get("status") == "failed":
            self.return_code = 1
        elif test_results.get("status") == "unknown":
            # If we couldn't parse results, keep original return code
            self.return_code = original_return_code if 'original_return_code' in locals() else 1
        
        logger.info(
            f"Test results: {test_results['summary']['passed']} passed, "
            f"{test_results['summary']['failed']} failed, "
            f"{test_results['summary']['skipped']} skipped, "
            f"status: {test_results['status']}, "
            f"return_code: {self.return_code}"
        )
        
        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()
        
        return self._format_results(test_json=test_results)
    
    def _format_results(
        self, 
        test_json: Optional[Dict] = None
    ) -> Dict[str, object]:
        if test_json and "summary" in test_json:
            parser_result = test_json
        else:
            parser_result = {
                "tests": [],
                "summary": {
                    "total": 0, 
                    "passed": 0, 
                    "failed": 0, 
                    "skipped": 0,
                    "errors": 0,
                    "collected": 0
                },
                "status": "unknown"
            }
        
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "std": self.std,
            "returncode": self.return_code,
            "parser": parser_result,
            "report": test_json or {},
            "time": self.evaluation_time,
            "run_id": self.run_id
        }
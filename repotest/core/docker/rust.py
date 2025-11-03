import json, logging, os, time
from functools import cached_property
from typing import Dict, Literal, Optional
from docker.errors import APIError, ImageNotFound
from repotest.constants import DEFAULT_BUILD_TIMEOUT_INT, DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException
from repotest.core.docker.types import CacheMode

logger = logging.getLogger("repotest")

def parse_rust_test_report(report_path: str) -> Dict[str, object]:
    if not os.path.exists(report_path):
        return {}
    
    try:
        with open(report_path, "r") as f:
            content = f.read()
            
            if content.strip().startswith("{") or content.strip().startswith("["):
                return _parse_rust_json(content)
            
            import xml.etree.ElementTree as ET
            root = ET.fromstring(content)
            
            result = {
                "tests": [],
                "summary": {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errors": 0
                }
            }
            
            testsuites = root.findall(".//testsuite")
            if not testsuites and root.tag == "testsuite":
                testsuites = [root]
            
            for testsuite in testsuites:
                result["summary"]["total"] += int(testsuite.get("tests", 0))
                result["summary"]["failed"] += int(testsuite.get("failures", 0))
                result["summary"]["errors"] += int(testsuite.get("errors", 0))
                result["summary"]["skipped"] += int(testsuite.get("skipped", 0))
                
                for testcase in testsuite.findall("testcase"):
                    test_info = {
                        "name": testcase.get("name"),
                        "classname": testcase.get("classname"),
                        "time": float(testcase.get("time", 0)),
                        "status": "passed"
                    }
                    
                    failure = testcase.find("failure")
                    error = testcase.find("error")
                    skipped = testcase.find("skipped")
                    
                    if failure is not None:
                        test_info["status"] = "failed"
                        test_info["message"] = failure.get("message", "")
                        test_info["details"] = failure.text or ""
                    elif error is not None:
                        test_info["status"] = "error"
                        test_info["message"] = error.get("message", "")
                        test_info["details"] = error.text or ""
                    elif skipped is not None:
                        test_info["status"] = "skipped"
                        test_info["message"] = skipped.get("message", "")
                    
                    result["tests"].append(test_info)
            
            result["summary"]["passed"] = (
                result["summary"]["total"] 
                - result["summary"]["failed"] 
                - result["summary"]["errors"] 
                - result["summary"]["skipped"]
            )
            result["status"] = "passed" if (result["summary"]["failed"] + result["summary"]["errors"]) == 0 else "failed"
            
            return result
            
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to parse test report: {e}")
        return {}


def _parse_rust_json(content: str) -> Dict[str, object]:
    lines = content.strip().split('\n')
    
    result = {
        "tests": [],
        "summary": {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "errors": 0
        }
    }
    
    for line in lines:
        try:
            data = json.loads(line)
            
            if data.get("type") == "test":
                event = data.get("event")
                if event in ["ok", "failed", "ignored"]:
                    test_info = {
                        "name": data.get("name", ""),
                        "classname": "",
                        "time": data.get("exec_time", 0),
                        "status": "passed" if event == "ok" else ("failed" if event == "failed" else "skipped")
                    }
                    
                    if event == "failed" and "stdout" in data:
                        test_info["message"] = data.get("stdout", "")
                        test_info["details"] = data.get("stdout", "")
                    
                    result["tests"].append(test_info)
                    
                    if event == "ok":
                        result["summary"]["passed"] += 1
                    elif event == "failed":
                        result["summary"]["failed"] += 1
                    elif event == "ignored":
                        result["summary"]["skipped"] += 1
            
            elif data.get("type") == "suite":
                event = data.get("event")
                if event == "ok" or event == "failed":
                    result["summary"]["total"] = data.get("passed", 0) + data.get("failed", 0) + data.get("ignored", 0)
                    result["summary"]["passed"] = data.get("passed", 0)
                    result["summary"]["failed"] = data.get("failed", 0)
                    result["summary"]["skipped"] = data.get("ignored", 0)
        
        except json.JSONDecodeError:
            continue
    
    if result["summary"]["total"] == 0 and result["tests"]:
        result["summary"]["total"] = len(result["tests"])
    
    result["status"] = "passed" if result["summary"]["failed"] == 0 and result["summary"]["total"] > 0 else ("failed" if result["summary"]["failed"] > 0 else "unknown")
    
    return result


class RustDockerRepo(AbstractDockerRepo):
    
    def __init__(self, 
                 repo: str, 
                 base_commit: str, 
                 default_cache_folder: str = DEFAULT_CACHE_FOLDER,
                 default_url: str = "http://github.com", 
                 image_name: str = "rust:latest",
                 cache_mode: CacheMode = "volume"
                 ) -> None:
        super().__init__(repo=repo, base_commit=base_commit, default_cache_folder=default_cache_folder,
                         default_url=default_url, image_name=image_name, cache_mode=cache_mode)
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
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
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
                volumes[self._user_cargo_cache] = {"bind": "/usr/local/cargo", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_cargo_cache, exist_ok=True)
            os.makedirs(self._local_rust_cache, exist_ok=True)
            volumes[self._local_cargo_cache] = {"bind": "/usr/local/cargo", "mode": "rw"}
            volumes[self._local_rust_cache] = {"bind": "/run_dir/target", "mode": "rw"}
        
        return volumes
    
    def build_env(self, 
                  command: str, 
                  timeout: int = DEFAULT_BUILD_TIMEOUT_INT, 
                  commit_image: bool = True,
                  stop_container: bool = True, 
                  push_image: bool = False
                  ) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        try:
            self.timeout_exec_run(
                f"bash -c 'mkdir -p /run_dir/test-results'",
                timeout=30
            )
            
            result = self.timeout_exec_run(
                "bash -c 'cat /run_dir/Cargo.toml 2>/dev/null || echo \"\"'",
                timeout=30
            ) or {}
            
            cargo_toml_content = result.get("stdout", b"").decode("utf-8", errors="ignore")
            
            if "cargo-nextest" in cargo_toml_content or "nextest" in command:
                self.timeout_exec_run(
                    f"bash -c 'cargo install cargo-nextest || true'",
                    timeout=300
                )
            else:
                self.timeout_exec_run(
                    f"bash -c 'cargo install cargo2junit || true'",
                    timeout=300
                )
        except Exception as e:
            logger.warning(f"Failed to configure test tools: {e}")
        
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
    
    def run_test(self, command: str = "cargo test", timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
                 stop_container: bool = True) -> Dict[str, object]:
        
        if not self.was_build:
            logger.info("Building environment before running tests")
            self.build_env(command="cargo build", timeout=DEFAULT_BUILD_TIMEOUT_INT, commit_image=True, stop_container=True)
        
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        try:
            self.timeout_exec_run(
                f"bash -c 'mkdir -p /run_dir/test-results'",
                timeout=30
            )
        except Exception as e:
            logger.warning(f"Failed to create test-results directory: {e}")
        
        try:
            self.evaluation_time = time.time()
            
            modified_command = command
            if "cargo test" in command and "--format" not in command:
                modified_command = command.replace("cargo test", "cargo test -- --format json -Z unstable-options")
                self.timeout_exec_run(
                    f"bash -c '{modified_command} > /run_dir/test-results/test-output.json 2>&1'",
                    timeout=timeout
                )
            else:
                self.timeout_exec_run(f"bash -c '{command}'", timeout=timeout)
                
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        test_results = {}
        
        report_paths = [
            os.path.join(self.cache_folder, "test-results/test-output.json"),
            os.path.join(self.cache_folder, "test-results/junit.xml"),
            os.path.join(self.cache_folder, "target/nextest/default/junit.xml"),
        ]
        
        report_dir = os.path.join(self.cache_folder, "test-results")
        if os.path.exists(report_dir) and os.path.isdir(report_dir):
            for filename in os.listdir(report_dir):
                if filename.endswith((".json", ".xml")):
                    report_path = os.path.join(report_dir, filename)
                    parsed_report = parse_rust_test_report(report_path)
                    if parsed_report:
                        test_results = parsed_report
                        break
        
        if not test_results:
            for report_path in report_paths:
                if os.path.exists(report_path) and os.path.isfile(report_path):
                    parsed_report = parse_rust_test_report(report_path)
                    if parsed_report:
                        test_results = parsed_report
                        break
        
        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()
        
        return self._format_results(test_json=test_results)
    
    def _format_results(self, test_json: Optional[Dict] = None) -> Dict[str, object]:
        if test_json and "summary" in test_json:
            parser_result = test_json
        else:
            parser_result = {
                "tests": [],
                "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
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
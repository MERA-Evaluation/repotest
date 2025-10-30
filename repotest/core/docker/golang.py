import json
import logging
import os
import time
from functools import cached_property
from typing import Dict, Literal, Optional
from docker.errors import APIError, ImageNotFound
from repotest.constants import DEFAULT_BUILD_TIMEOUT_INT, DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException

logger = logging.getLogger("repotest")

def parse_go_test_report(report_path: str) -> Dict[str, object]:
    if not os.path.exists(report_path):
        return {}
    
    try:
        with open(report_path, "r") as f:
            content = f.read()
            
            if content.strip().startswith("{") or content.strip().startswith("["):
                return _parse_go_json(content)
            
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


def _parse_go_json(content: str) -> Dict[str, object]:
    lines = content.strip().split('\n')
    
    packages = {}
    tests = {}
    
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
                        "elapsed": 0
                    }
                if action in ("pass", "fail", "skip"):
                    packages[package]["status"] = action
                    packages[package]["elapsed"] = elapsed
            
            if test:
                test_key = f"{package}/{test}"
                if test_key not in tests:
                    tests[test_key] = {
                        "name": test,
                        "classname": package,
                        "time": 0,
                        "status": "unknown",
                        "output": []
                    }
                
                if action == "pass":
                    tests[test_key]["status"] = "passed"
                    tests[test_key]["time"] = elapsed
                    result["summary"]["passed"] += 1
                    result["summary"]["total"] += 1
                elif action == "fail":
                    tests[test_key]["status"] = "failed"
                    tests[test_key]["time"] = elapsed
                    result["summary"]["failed"] += 1
                    result["summary"]["total"] += 1
                elif action == "skip":
                    tests[test_key]["status"] = "skipped"
                    tests[test_key]["time"] = elapsed
                    result["summary"]["skipped"] += 1
                    result["summary"]["total"] += 1
                elif action == "output" and "Output" in event:
                    tests[test_key]["output"].append(event["Output"])
        
        except json.JSONDecodeError:
            continue
    
    for test_info in tests.values():
        if test_info.get("output"):
            test_info["message"] = "".join(test_info["output"])
            test_info["details"] = test_info["message"]
        result["tests"].append({
            "name": test_info["name"],
            "classname": test_info["classname"],
            "time": test_info["time"],
            "status": test_info["status"],
            "message": test_info.get("message", ""),
            "details": test_info.get("details", "")
        })
    
    result["status"] = "passed" if result["summary"]["failed"] == 0 and result["summary"]["total"] > 0 else ("failed" if result["summary"]["failed"] > 0 else "unknown")
    result["packages"] = packages
    
    return result


class GoLangDockerRepo(AbstractDockerRepo):
    
    def __init__(self, repo: str, base_commit: str, default_cache_folder: str = DEFAULT_CACHE_FOLDER,
                 default_url: str = "http://github.com", image_name: str = "golang:latest",
                 cache_mode: Literal["download", "shared", "local", "volume"] = "volume") -> None:
        super().__init__(repo=repo, base_commit=base_commit, default_cache_folder=default_cache_folder,
                         default_url=default_url, image_name=image_name, cache_mode=cache_mode)
        self.stdout = ""
        self.stderr = ""
        self.std = ""
        self.return_code = 0
    
    @cached_property
    def _user_go_cache(self) -> str:
        return os.path.expanduser("~/.cache/go-build")
    
    @cached_property
    def _local_go_cache(self) -> str:
        return os.path.join(self.cache_folder, ".go_cache")
    
    @cached_property
    def _local_gomod_cache(self) -> str:
        return os.path.join(self.cache_folder, ".gomod_cache")
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("go-cache")
            self.create_volume("gomod-cache")
            volumes["go-cache"] = {"bind": "/go/pkg", "mode": "rw"}
            volumes["gomod-cache"] = {"bind": "/root/.cache/go-build", "mode": "rw"}
        elif self.cache_mode == "shared":
            if os.path.exists(self._user_go_cache):
                volumes[self._user_go_cache] = {"bind": "/root/.cache/go-build", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_go_cache, exist_ok=True)
            os.makedirs(self._local_gomod_cache, exist_ok=True)
            volumes[self._local_go_cache] = {"bind": "/go/pkg", "mode": "rw"}
            volumes[self._local_gomod_cache] = {"bind": "/root/.cache/go-build", "mode": "rw"}
        
        return volumes
    
    def build_env(self, command: str, timeout: int = DEFAULT_BUILD_TIMEOUT_INT, commit_image: bool = True,
                  stop_container: bool = True, push_image: bool = False) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        try:
            
            self.timeout_exec_run(
                f"sh -c 'go install github.com/jstemmer/go-junit-report/v2@latest || true'",
                timeout=120
            )
        except Exception as e:
            logger.warning(f"Failed to install go-junit-report: {e}")
        
        command = "ulimit -n 65535;\n" + command
        
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"sh -c 'mkdir -p /run_dir/test-results && {command}'", timeout=timeout)
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
    
    def run_test(self, command: str = "go test -json ./...", timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
                 stop_container: bool = True) -> Dict[str, object]:
        
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        try:
            self.evaluation_time = time.time()
            
            modified_command = command
            if "go test" in command and "-json" not in command:
                modified_command = command.replace("go test", "go test -json")
            
            full_command = f"mkdir -p /run_dir/test-results && ({modified_command} 2>&1 | tee /run_dir/test-results/go-test.json | go-junit-report > /run_dir/test-results/junit.xml || {modified_command} > /run_dir/test-results/go-test.json)"
            
            self.timeout_exec_run(
                f"sh -c '{full_command}'",
                timeout=timeout
            )
                
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        test_results = {}

        cache_folder = self.cache_folder if self.cache_folder is not None else "."
        
        json_report_path = os.path.join(cache_folder, "test-results/go-test.json")
        if os.path.exists(json_report_path) and os.path.isfile(json_report_path):
            test_results = parse_go_test_report(json_report_path)
        
        if not test_results:
            xml_report_path = os.path.join(cache_folder, "test-results/junit.xml")
            if os.path.exists(xml_report_path) and os.path.isfile(xml_report_path):
                test_results = parse_go_test_report(xml_report_path)

        if not test_results:
            jsonl_report_path = os.path.join(cache_folder, "gotest_results.jsonl")
            if os.path.exists(jsonl_report_path) and os.path.isfile(jsonl_report_path):
                 test_results = parse_go_test_report(jsonl_report_path)
        
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
                "status": "unknown",
                "packages": {}
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
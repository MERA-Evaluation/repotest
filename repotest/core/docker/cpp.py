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

def parse_cpp_test_report(report_path: str) -> Dict[str, object]:
    if not os.path.exists(report_path):
        return {}
    
    try:
        with open(report_path, "r") as f:
            content = f.read()
            
            if content.strip().startswith("{") or content.strip().startswith("["):
                data = json.loads(content)
                
                if "tests" in data and "summary" in data:
                    return data
                
                return {}
            
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


class CppDockerRepo(AbstractDockerRepo):
    
    def __init__(self, repo: str, base_commit: str, default_cache_folder: str = DEFAULT_CACHE_FOLDER,
                 default_url: str = "http://github.com", image_name: str = "rikorose/gcc-cmake:latest",
                 cache_mode: Literal["download", "shared", "local", "volume"] = "volume") -> None:
        if default_cache_folder is None:
            default_cache_folder = DEFAULT_CACHE_FOLDER
        super().__init__(repo=repo, base_commit=base_commit, default_cache_folder=default_cache_folder,
                         default_url=default_url, image_name=image_name, cache_mode=cache_mode)
        self.stdout = ""
        self.stderr = ""
        self.std = ""
        self.return_code = 0
    
    @cached_property
    def _user_cmake_cache(self) -> str:
        return os.path.expanduser("~/.cmake")
    
    @cached_property
    def _local_cmake_cache(self) -> str:
        if self.cache_folder is None:
            return ".cmake_cache"
        return os.path.join(self.cache_folder, ".cmake_cache")
    
    @cached_property
    def _local_cpp_cache(self) -> str:
        if self.cache_folder is None:
            return ".cpp_cache"
        return os.path.join(self.cache_folder, ".cpp_cache")
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("cmake-cache")
            self.create_volume("cpp-cache")
            volumes["cmake-cache"] = {"bind": "/root/.cmake", "mode": "rw"}
            volumes["cpp-cache"] = {"bind": "/root/.cache/cpp", "mode": "rw"}
        elif self.cache_mode == "shared":
            user_cmake = os.path.expanduser("~/.cmake")
            if os.path.exists(user_cmake):
                volumes[user_cmake] = {"bind": "/root/.cmake", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_cmake_cache, exist_ok=True)
            os.makedirs(self._local_cpp_cache, exist_ok=True)
            volumes[self._local_cmake_cache] = {"bind": "/root/.cmake", "mode": "rw"}
            volumes[self._local_cpp_cache] = {"bind": "/root/.cache/cpp", "mode": "rw"}
        
        return volumes
    
    def _merge_reports(self, reports: list[Dict[str, object]]) -> Dict[str, object]:
        if not reports:
            return {}
        
        merged_result = {
            "tests": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}
        }
        
        for report in reports:
            if "tests" in report:
                merged_result["tests"].extend(report.get("tests", []))
            
            summary = report.get("summary", {})
            if isinstance(summary, dict):
                merged_result["summary"]["total"] += summary.get("total", 0)
                merged_result["summary"]["passed"] += summary.get("passed", 0)
                merged_result["summary"]["failed"] += summary.get("failed", 0)
                merged_result["summary"]["skipped"] += summary.get("skipped", 0)
                merged_result["summary"]["errors"] += summary.get("errors", 0)
        
        merged_result["status"] = "passed" if (merged_result["summary"]["failed"] + merged_result["summary"]["errors"]) == 0 and merged_result["summary"]["total"] > 0 else "failed"
        
        return merged_result
    
    def build_env(self, command: str, timeout: int = DEFAULT_BUILD_TIMEOUT_INT, commit_image: bool = True,
                  stop_container: bool = True, push_image: bool = False) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        try:           
            result = self.timeout_exec_run(
                "sh -c 'cat /run_dir/CMakeLists.txt 2>/dev/null || echo \"\"'",
                timeout=30
            ) or {}
            
            cmake_content = result.get("stdout", b"").decode("utf-8", errors="ignore")
            
            if "enable_testing" in cmake_content.lower() or "add_test" in cmake_content.lower():
                cmake_config = '''
                                set(CTEST_OUTPUT_ON_FAILURE ON)
                                enable_testing()
                                '''
                self.timeout_exec_run(
                    f"sh -c 'echo \"{cmake_config}\" >> /run_dir/CMakeLists.txt'",
                    timeout=30
                )
        except Exception as e:
            logger.warning(f"Failed to configure test reporters: {e}")
        
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
    
    def run_test(self, command: str = "ctest -V", timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
                 stop_container: bool = True) -> Dict[str, object]:
        
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        try:
            self.evaluation_time = time.time()
            
            modified_command = command
            if "ctest" in command and "--output-junit" not in command:
                modified_command = f"{command} --output-junit /run_dir/test-results/junit.xml"
            
            self.timeout_exec_run(f"sh -c 'mkdir -p /run_dir/test-results && {modified_command}'", timeout=timeout)
                
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        all_report_files = set()
        cache_folder = self.cache_folder if self.cache_folder is not None else "."
        
        report_dir = os.path.join(cache_folder, "test-results")
        if os.path.exists(report_dir) and os.path.isdir(report_dir):
            for filename in os.listdir(report_dir):
                if filename.endswith((".json", ".xml")):
                    all_report_files.add(os.path.join(report_dir, filename))

        testing_dir = os.path.join(cache_folder, "Testing")
        if os.path.exists(testing_dir) and os.path.isdir(testing_dir):
            tag_file = os.path.join(testing_dir, "TAG")
            if os.path.exists(tag_file):
                try:
                    with open(tag_file, "r") as f:
                        tag = f.readline().strip()
                        test_xml = os.path.join(testing_dir, tag, "Test.xml")
                        if os.path.exists(test_xml) and os.path.isfile(test_xml):
                            all_report_files.add(test_xml)
                except Exception as e:
                    logger.warning(f"Failed to read CTest results: {e}")
        
        parsed_reports = []
        for report_file in all_report_files:
            parsed_report = parse_cpp_test_report(report_file)
            if parsed_report and parsed_report.get("summary", {}).get("total", 0) > 0:
                parsed_reports.append(parsed_report)
        
        test_results = self._merge_reports(parsed_reports)
        
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
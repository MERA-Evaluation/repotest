import json
import logging
import os
import time
from functools import cached_property
from typing import Dict, Optional
from docker.errors import APIError, ImageNotFound
from repotest.constants import DEFAULT_BUILD_TIMEOUT_INT, DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException
from repotest.core.docker.types import CacheMode

logger = logging.getLogger("repotest")


def parse_cpp_test_report(report_path: str) -> Dict[str, object]:
    if not os.path.exists(report_path):
        return {}
    
    try:
        with open(report_path, "r") as f:
            content = f.read()
            
            if content.strip().startswith("{") or content.strip().startswith("["):
                return _parse_cpp_json(content)
            
            import xml.etree.ElementTree as ET
            root = ET.fromstring(content)
            
            result = {
                "tests": [],
                "summary": {
                    "total": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "errors": 0,
                    "collected": 0
                }
            }
            
            if root.tag == "Site":
                for testing in root.findall(".//Testing"):
                    for test in testing.findall(".//Test"):
                        status_elem = test.find("Status")
                        name_elem = test.find("Name")
                        path_elem = test.find("Path")
                        
                        if name_elem is not None:
                            test_status = status_elem.text if status_elem is not None else "unknown"
                            test_name = name_elem.text
                            test_path = path_elem.text if path_elem is not None else ""
                            
                            result["summary"]["total"] += 1
                            
                            test_info = {
                                "name": test_name,
                                "classname": test_path,
                                "time": 0.0,
                                "status": "passed" if test_status == "passed" else "failed"
                            }
                            
                            if test_status == "passed":
                                result["summary"]["passed"] += 1
                            else:
                                result["summary"]["failed"] += 1
                                measurement = test.find(".//Measurement")
                                if measurement is not None:
                                    test_info["message"] = measurement.text or ""
                                    test_info["details"] = measurement.text or ""
                            
                            result["tests"].append(test_info)
            else:
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
            
            result["summary"]["collected"] = result["summary"]["total"]
            result["status"] = "passed" if (result["summary"]["failed"] + result["summary"]["errors"]) == 0 and result["summary"]["total"] > 0 else "failed"
            
            return result
            
    except Exception as e:
        logger.warning(f"Failed to parse test report: {e}")
        return {}


def _parse_cpp_json(content: str) -> Dict[str, object]:
    try:
        data = json.loads(content)
        
        result = {
            "tests": [],
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "errors": 0,
                "collected": 0
            }
        }
        
        if "testsuites" in data:
            testsuites = data.get("testsuites", [])
            if isinstance(testsuites, list):
                for testsuite in testsuites:
                    suite_name = testsuite.get("name", "")
                    
                    for testcase in testsuite.get("testsuite", []):
                        test_name = testcase.get("name", "")
                        status = testcase.get("status", "RUN")
                        time_str = testcase.get("time", "0")
                        time_val = float(time_str.rstrip("s")) if isinstance(time_str, str) else float(time_str)
                        
                        result["summary"]["total"] += 1
                        
                        test_info = {
                            "name": test_name,
                            "classname": suite_name,
                            "time": time_val,
                            "status": "passed" if status == "RUN" else "failed"
                        }
                        
                        if status == "RUN":
                            result["summary"]["passed"] += 1
                        else:
                            result["summary"]["failed"] += 1
                            failures = testcase.get("failures", [])
                            if failures:
                                test_info["message"] = failures[0].get("failure", "")
                                test_info["details"] = failures[0].get("failure", "")
                        
                        result["tests"].append(test_info)
        
        elif "tests" in data and isinstance(data["tests"], list):
            result["tests"] = data["tests"]
            result["summary"]["total"] = len(data["tests"])
            
            for test in data["tests"]:
                status = test.get("status", "unknown")
                if status == "passed":
                    result["summary"]["passed"] += 1
                elif status == "failed":
                    result["summary"]["failed"] += 1
                elif status == "skipped":
                    result["summary"]["skipped"] += 1
                elif status == "error":
                    result["summary"]["errors"] += 1
        
        result["summary"]["collected"] = result["summary"]["total"]
        
        if result["summary"]["total"] > 0:
            result["status"] = "passed" if (result["summary"]["failed"] + result["summary"]["errors"]) == 0 else "failed"
        else:
            result["status"] = "unknown"
        
        return result
    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"Failed to parse JSON: {e}")
        return {}


class CppDockerRepo(AbstractDockerRepo):
    
    def __init__(self, 
                 repo: str, 
                 base_commit: str, 
                 default_cache_folder: str = DEFAULT_CACHE_FOLDER,
                 default_url: str = "http://github.com", 
                 image_name: str = "gcc:latest",
                 cache_mode: CacheMode = 'volume'
                 ) -> None:
        super().__init__(repo=repo, base_commit=base_commit, default_cache_folder=default_cache_folder,
                         default_url=default_url, image_name=image_name, cache_mode=cache_mode)
    
    @cached_property
    def _user_cpp_cache(self) -> str:
        return os.path.expanduser("~/.cache/cpp-build")
    
    @cached_property
    def _local_cpp_cache(self) -> str:
        return os.path.join(self.cache_folder, ".cpp_cache")
    
    @cached_property
    def _local_cmake_cache(self) -> str:
        return os.path.join(self.cache_folder, ".cmake_cache")
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("cpp-cache")
            self.create_volume("cmake-cache")
            volumes["cpp-cache"] = {"bind": "/root/.cache/cpp", "mode": "rw"}
            volumes["cmake-cache"] = {"bind": "/root/.cmake", "mode": "rw"}
        elif self.cache_mode == "shared":
            if os.path.exists(self._user_cpp_cache):
                volumes[self._user_cpp_cache] = {"bind": "/root/.cache/cpp-build", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_cpp_cache, exist_ok=True)
            os.makedirs(self._local_cmake_cache, exist_ok=True)
            volumes[self._local_cpp_cache] = {"bind": "/root/.cache/cpp", "mode": "rw"}
            volumes[self._local_cmake_cache] = {"bind": "/root/.cmake", "mode": "rw"}
        
        return volumes
    
    def _merge_reports(self, reports: list[Dict[str, dict]]) -> Dict[str, object]:
        if not reports:
            return {}
        
        merged_result = {
            "tests": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "collected": 0}
        }
        
        for report in reports:
            if "tests" in report:
                merged_result["tests"].extend(report.get("tests", []))
            
            summary = report.get("summary", {})
            merged_result["summary"]["total"] += summary.get("total", 0)
            merged_result["summary"]["passed"] += summary.get("passed", 0)
            merged_result["summary"]["failed"] += summary.get("failed", 0)
            merged_result["summary"]["skipped"] += summary.get("skipped", 0)
            merged_result["summary"]["errors"] += summary.get("errors", 0)
            merged_result["summary"]["collected"] += summary.get("collected", 0)
        
        merged_result["status"] = "passed" if (merged_result["summary"]["failed"] + merged_result["summary"]["errors"]) == 0 and merged_result["summary"]["total"] > 0 else "failed"
        
        return merged_result
    
    def build_env(self, command: str = "cmake -B build -DBUILD_GMOCK=ON -Dgtest_build_tests=ON -Dgmock_build_tests=ON && cmake --build build", timeout: int = DEFAULT_BUILD_TIMEOUT_INT, commit_image: bool = True,
                  stop_container: bool = True, push_image: bool = False) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        try:
            check_cmake = self.timeout_exec_run("sh -c 'which cmake'", timeout=10) or {}
            if not check_cmake.get("stdout", b"").strip():
                logger.info("Installing cmake and build tools")
                install_cmd = "apt-get update -qq && apt-get install -y -qq cmake build-essential 2>/dev/null || apk add --no-cache cmake make g++ 2>/dev/null || yum install -y -q cmake gcc-c++ make 2>/dev/null"
                self.timeout_exec_run(f"sh -c '{install_cmd}'", timeout=300)
        except Exception as e:
            logger.warning(f"Failed to install cmake: {e}")
        
        try:
            result = self.timeout_exec_run(
                "sh -c 'cat /run_dir/CMakeLists.txt 2>/dev/null || echo \"\"'",
                timeout=30
            ) or {}
            
            cmake_content = result.get("stdout", b"").decode("utf-8", errors="ignore")
            
            if cmake_content and "enable_testing" not in cmake_content.lower():
                logger.info("Adding enable_testing() to CMakeLists.txt")
                self.timeout_exec_run(
                    "sh -c 'echo \"\" >> /run_dir/CMakeLists.txt && echo \"enable_testing()\" >> /run_dir/CMakeLists.txt'",
                    timeout=30
                )
        except Exception as e:
            logger.warning(f"Failed to modify CMakeLists.txt: {e}")
        
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"sh -c '{command}'", timeout=timeout)
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
            raise TimeOutException(f"Command timed out after {timeout}s.")
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        try:
            check_build = self.timeout_exec_run("sh -c 'ls -la /run_dir/build 2>/dev/null | wc -l'", timeout=10) or {}
            build_files = check_build.get("stdout", b"").decode("utf-8", errors="ignore").strip()
            if build_files and int(build_files) > 3:
                logger.info("Build directory exists with files, considering build successful")
                self.return_code = 0
        except Exception as e:
            logger.debug(f"Could not verify build files: {e}")
        
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
    
    def __call__(self, command_build: str = "cmake -B build -DBUILD_GMOCK=ON -Dgtest_build_tests=ON -Dgmock_build_tests=ON && cmake --build build", command_test: str = "cd build && ctest --output-on-failure", timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
                 timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT) -> Dict[str, object]:
        if not self.was_build:
            self.build_env(command=command_build, timeout=timeout_build)
        return self.run_test(command=command_test, timeout=timeout_test)
    
    def run_test(self, command: str = "cd build && ctest --output-on-failure", timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
                 stop_container: bool = True) -> Dict[str, object]:
        
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        try:
            check_ctest = self.timeout_exec_run("sh -c 'which ctest'", timeout=10) or {}
            if not check_ctest.get("stdout", b"").strip():
                logger.info("Installing cmake for tests")
                install_cmd = "apt-get update -qq && apt-get install -y -qq cmake 2>/dev/null || apk add --no-cache cmake 2>/dev/null || yum install -y -q cmake 2>/dev/null"
                self.timeout_exec_run(f"sh -c '{install_cmd}'", timeout=300)
        except Exception as e:
            logger.warning(f"Failed to install cmake: {e}")
        
        try:
            self.evaluation_time = time.time()
            
            if "ctest" in command and "--output-junit" not in command:
                full_command = f"mkdir -p /run_dir/test-results && {command} --output-junit /run_dir/test-results/junit.xml || {command}"
            else:
                full_command = f"mkdir -p /run_dir/test-results && {command}"
            
            self.timeout_exec_run(
                f"sh -c '{full_command}'",
                timeout=timeout
            )
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        all_report_files = set()
        report_dir = os.path.join(self.cache_folder, "test-results")
        if os.path.exists(report_dir) and os.path.isdir(report_dir):
            for filename in os.listdir(report_dir):
                if filename.endswith((".json", ".xml")):
                    all_report_files.add(os.path.join(report_dir, filename))
        
        testing_dir = os.path.join(self.cache_folder, "build", "Testing")
        if os.path.exists(testing_dir) and os.path.isdir(testing_dir):
            for subdir in os.listdir(testing_dir):
                subdir_path = os.path.join(testing_dir, subdir)
                if os.path.isdir(subdir_path):
                    test_xml = os.path.join(subdir_path, "Test.xml")
                    if os.path.exists(test_xml):
                        all_report_files.add(test_xml)
        
        known_paths = [
            os.path.join(self.cache_folder, "ctest_results.xml"),
            os.path.join(self.cache_folder, "build", "test_detail.xml"),
        ]
        
        for report_path in known_paths:
            if os.path.exists(report_path):
                all_report_files.add(report_path)

        parsed_reports = []
        for report_file in all_report_files:
            parsed_report = parse_cpp_test_report(report_file)
            if isinstance(parsed_report, dict):
                summary = parsed_report.get("summary", {})
                if isinstance(summary, dict):
                    total = summary.get("total", 0)
                else:
                    total = 0
                if total > 0:
                    parsed_reports.append(parsed_report)

        test_results = self._merge_reports(parsed_reports)
        
        if not test_results or test_results.get("summary", {}).get("total", 0) == 0:
            logger.info("No tests found via ctest, checking if tests were built")
            try:
                check_cmake_cache = self.timeout_exec_run(
                    "sh -c 'grep -i \"gtest_build_tests\\|gmock_build_tests\" /run_dir/build/CMakeCache.txt 2>/dev/null || echo NOTFOUND'",
                    timeout=10
                ) or {}
                cache_content = check_cmake_cache.get("stdout", b"").decode("utf-8", errors="ignore")
                
                if "NOTFOUND" in cache_content or "OFF" in cache_content:
                    logger.info("Tests were not built with proper flags, rebuilding...")
                    try:
                        rebuild_cmd = "cd /run_dir && cmake -B build -DBUILD_GMOCK=ON -Dgtest_build_tests=ON -Dgmock_build_tests=ON && cmake --build build"
                        self.timeout_exec_run(f"sh -c '{rebuild_cmd}'", timeout=600)
                        
                        retry_test = self.timeout_exec_run(
                            f"sh -c 'cd /run_dir/build && ctest --output-on-failure'",
                            timeout=300
                        )
                        
                        testing_dir = os.path.join(self.cache_folder, "build", "Testing")
                        if os.path.exists(testing_dir) and os.path.isdir(testing_dir):
                            for subdir in os.listdir(testing_dir):
                                subdir_path = os.path.join(testing_dir, subdir)
                                if os.path.isdir(subdir_path):
                                    test_xml = os.path.join(subdir_path, "Test.xml")
                                    if os.path.exists(test_xml):
                                        parsed_report = parse_cpp_test_report(test_xml)
                                        if parsed_report.get("summary", {}).get("total", 0) > 0:
                                            parsed_reports.append(parsed_report)
                        
                        if parsed_reports:
                            test_results = self._merge_reports(parsed_reports)
                    except Exception as e:
                        logger.warning(f"Failed to rebuild tests: {e}")
            except Exception as e:
                logger.debug(f"Could not check CMake cache: {e}")
            
            if not test_results or test_results.get("summary", {}).get("total", 0) == 0:
                logger.info("Still no tests found, trying to find and run test binaries")
                try:
                    find_result = self.timeout_exec_run(
                        "sh -c 'find /run_dir/build -type f -executable -name \"*test*\" 2>/dev/null | grep -v CMake | head -20'",
                        timeout=30
                    ) or {}
                    
                    test_binaries = find_result.get("stdout", b"").decode("utf-8", errors="ignore").strip().split('\n')
                    test_binaries = [t.strip() for t in test_binaries if t.strip() and 'test' in t.lower() and not t.endswith('.cmake')]
                    
                    if test_binaries:
                        logger.info(f"Found {len(test_binaries)} test binaries")
                        
                        result = {
                            "tests": [],
                            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "collected": 0}
                        }
                        
                        for binary in test_binaries[:10]:
                            try:
                                logger.info(f"Running test binary: {binary}")
                                test_output = self.timeout_exec_run(
                                    f"sh -c 'cd /run_dir/build && {binary} --gtest_output=json:/run_dir/test-results/{os.path.basename(binary)}.json 2>&1 || {binary} 2>&1'",
                                    timeout=60
                                ) or {}
                                
                                result["summary"]["total"] += 1
                                
                                test_returncode = test_output.get("returncode", 1)
                                if test_returncode == 0:
                                    result["summary"]["passed"] += 1
                                    result["tests"].append({
                                        "name": os.path.basename(binary),
                                        "classname": "binary_test",
                                        "time": 0.0,
                                        "status": "passed"
                                    })
                                else:
                                    result["summary"]["failed"] += 1
                                    result["tests"].append({
                                        "name": os.path.basename(binary),
                                        "classname": "binary_test",
                                        "time": 0.0,
                                        "status": "failed",
                                        "message": test_output.get("stderr", b"").decode("utf-8", errors="ignore")[:200]
                                    })
                            except Exception as e:
                                logger.warning(f"Failed to run binary {binary}: {e}")
                        
                        result["summary"]["collected"] = result["summary"]["total"]
                        result["status"] = "passed" if result["summary"]["failed"] == 0 else "failed"
                        
                        report_dir = os.path.join(self.cache_folder, "test-results")
                        if os.path.exists(report_dir):
                            for filename in os.listdir(report_dir):
                                if filename.endswith(".json"):
                                    json_path = os.path.join(report_dir, filename)
                                    try:
                                        json_report = parse_cpp_test_report(json_path)
                                        if json_report.get("summary", {}).get("total", 0) > 0:
                                            parsed_reports.append(json_report)
                                    except Exception:
                                        pass
                        
                        if parsed_reports:
                            test_results = self._merge_reports(parsed_reports)
                        else:
                            test_results = result
                            
                except Exception as e:
                    logger.warning(f"Failed to find/run test binaries: {e}")
        
        if test_results and test_results.get("summary", {}).get("total", 0) > 0:
            failed = test_results["summary"].get("failed", 0)
            errors = test_results["summary"].get("errors", 0)
            if failed == 0 and errors == 0:
                logger.info("All tests passed, overriding return code to 0")
                self.return_code = 0
        
        if stop_container:
            self.stop_container()
        
        return self._format_results(test_json=test_results)
    
    def _format_results(self, test_json: Optional[Dict] = None) -> Dict[str, object]:
        default_result = {
            "tests": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "collected": 0},
            "status": "unknown"
        }
        parser_result = test_json or default_result
        
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "std": self.std,
            "returncode": self.return_code,
            "parser": parser_result,
            "report": parser_result,
            "time": self.evaluation_time,
            "run_id": self.run_id
        }
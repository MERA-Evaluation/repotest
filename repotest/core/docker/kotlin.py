import json
import logging
import os
import re
import time
from functools import cached_property
from typing import Dict, Optional, List, cast
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


def parse_gradle_console_output(stdout: str, stderr: str) -> Dict[str, object]:
    combined = stdout + "\n" + stderr
    
    result = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "collected": 0
    }
    
    for line in combined.split('\n'):
        match = re.search(r'(\d+) tests? completed(?:, (\d+) failed)?(?:, (\d+) skipped)?', line)
        if match:
            result["total"] = int(match.group(1))
            result["failed"] = int(match.group(2) or 0)
            result["skipped"] = int(match.group(3) or 0)
            result["passed"] = result["total"] - result["failed"] - result["skipped"]
            result["collected"] = result["total"]
            break
    
    return result


def parse_junit_xml_report(xml_path: str) -> Dict[str, object]:
    if not os.path.exists(xml_path):
        return {}
    
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
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
        
        testsuites = root.findall(".//testsuite")
        if not testsuites and root.tag == "testsuite":
            testsuites = [root]
        
        for testsuite in testsuites:
            tests_count = int(testsuite.get("tests", 0))
            failures_count = int(testsuite.get("failures", 0))
            errors_count = int(testsuite.get("errors", 0))
            skipped_count = int(testsuite.get("skipped", 0))
            
            result["summary"]["total"] += tests_count
            result["summary"]["failed"] += failures_count
            result["summary"]["errors"] += errors_count
            result["summary"]["skipped"] += skipped_count
            
            for testcase in testsuite.findall("testcase"):
                test_name = testcase.get("name", "")
                test_classname = testcase.get("classname", "")
                test_time = float(testcase.get("time", 0))
                
                full_name = f"{test_classname}.{test_name}" if test_classname else test_name
                
                test_info = {
                    "name": full_name or "unknown",
                    "classname": test_classname,
                    "time": test_time,
                    "status": "passed"
                }
                
                failure = testcase.find("failure")
                error = testcase.find("error")
                skipped = testcase.find("skipped")
                
                if failure is not None:
                    test_info["status"] = "failed"
                    test_info["message"] = failure.get("message", "")
                    test_info["details"] = (failure.text or "").strip()
                elif error is not None:
                    test_info["status"] = "error"
                    test_info["message"] = error.get("message", "")
                    test_info["details"] = (error.text or "").strip()
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
        
        has_failures = (result["summary"]["failed"] + result["summary"]["errors"]) > 0
        has_tests = result["summary"]["total"] > 0
        
        if has_tests:
            result["status"] = "failed" if has_failures else "passed"
        else:
            result["status"] = "unknown"
        
        return result
        
    except Exception as e:
        logger.warning(f"Failed to parse XML report {xml_path}: {e}")
        return {}


class KotlinDockerRepo(AbstractDockerRepo):
    
    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = "gradle:8.5-jdk17",
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
    def _user_gradle_cache(self) -> str:
        return os.path.expanduser("~/.gradle")
    
    @cached_property
    def _user_kotlin_cache(self) -> str:
        return os.path.expanduser("~/.kotlin")
    
    @cached_property
    def _local_gradle_cache(self) -> str:
        return os.path.join(self.cache_folder, ".gradle_cache")
    
    @cached_property
    def _local_kotlin_cache(self) -> str:
        return os.path.join(self.cache_folder, ".kotlin_cache")
    
    def _setup_container_volumes(
        self, 
        workdir: Optional[str] = None
    ) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("gradle-cache")
            self.create_volume("kotlin-cache")
            volumes["gradle-cache"] = {"bind": "/root/.gradle", "mode": "rw"}
            volumes["kotlin-cache"] = {"bind": "/root/.kotlin", "mode": "rw"}
        elif self.cache_mode == "shared":
            if os.path.exists(self._user_gradle_cache):
                volumes[self._user_gradle_cache] = {"bind": "/root/.gradle", "mode": "rw"}
            if os.path.exists(self._user_kotlin_cache):
                volumes[self._user_kotlin_cache] = {"bind": "/root/.kotlin", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_gradle_cache, exist_ok=True)
            os.makedirs(self._local_kotlin_cache, exist_ok=True)
            volumes[self._local_gradle_cache] = {"bind": "/root/.gradle", "mode": "rw"}
            volumes[self._local_kotlin_cache] = {"bind": "/root/.kotlin", "mode": "rw"}
        
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
        except NotFound:
            pass
        
        self.container = self.docker_client.containers.run(
            image_name,
            name=container_name,
            volumes=volumes,
            working_dir=working_dir,
            command='/bin/sh -c "tail -f /dev/null"',
            detach=True,
            shm_size='2g'
        )
    
    def _merge_reports(self, reports: List[Dict[str, object]]) -> Dict[str, object]:
        if not reports:
            return {
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
        
        merged_result = {
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
        
        for report in reports:
            if "tests" in report:
                tests = cast(List[Dict[str, object]], report.get("tests", []))
                merged_result["tests"].extend(tests)
            
            summary = cast(Dict[str, int], report.get("summary", {}))
            merged_result["summary"]["total"] += int(summary.get("total", 0))
            merged_result["summary"]["passed"] += int(summary.get("passed", 0))
            merged_result["summary"]["failed"] += int(summary.get("failed", 0))
            merged_result["summary"]["skipped"] += int(summary.get("skipped", 0))
            merged_result["summary"]["errors"] += int(summary.get("errors", 0))
        
        merged_result["summary"]["collected"] = merged_result["summary"]["total"]
        
        has_failures = (
            merged_result["summary"]["failed"] + 
            merged_result["summary"]["errors"]
        ) > 0
        has_tests = merged_result["summary"]["total"] > 0
        
        if has_tests:
            merged_result["status"] = "failed" if has_failures else "passed"
        else:
            merged_result["status"] = "unknown"
        
        return merged_result
    
    def _find_test_reports(self) -> List[str]:
        xml_paths = []
        
        for root, dirs, files in os.walk(self.cache_folder):
            for filename in files:
                if filename.endswith(".xml"):
                    full_path = os.path.join(root, filename)
                    if "test-results" in full_path or "/test/" in full_path:
                        xml_paths.append(full_path)
        
        logger.info(f"Found {len(xml_paths)} XML test report files")
        return xml_paths
    
    def build_env(
        self,
        command: str = "./gradlew build -x test --no-daemon",
        timeout: int = 1800,
        commit_image: bool = True,
        stop_container: bool = True,
        push_image: bool = False
    ) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        
        self.start_container(
            image_name=self.image_name,
            container_name=self.container_name,
            volumes=volumes,
            working_dir="/run_dir"
        )
        
        try:
            self.timeout_exec_run("chmod +x gradlew 2>/dev/null || true", timeout=10)
        except Exception:
            pass
        
        gradle_opts = (
            'export GRADLE_OPTS="-Xmx3g -Xms512m '
            '-XX:MaxMetaspaceSize=1g '
            '-Dorg.gradle.daemon=false '
            '-Dorg.gradle.parallel=true '
            '-Dorg.gradle.caching=true '
            '-Dorg.gradle.configureondemand=true"'
        )
        
        full_command = f"bash -c '{gradle_opts} && {command}'"
        
        try:
            self.evaluation_time = time.time()
            result = self.timeout_exec_run(full_command, timeout=timeout)
            if result:
                self.return_code = result.get("returncode", 0)
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Build timeout"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        if self._FALL_WITH_TIMEOUT_EXCEPTION:
            if stop_container:
                self.stop_container()
            raise TimeOutException(f"Build timeout after {timeout}s")
        
        if commit_image and self.return_code == 0:
            self._commit_container_image()
        
        if push_image:
            self.push_image()
        
        if stop_container:
            self.stop_container()
        
        return self._format_results(test_json=None)
    
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
    
    def __call__(
        self,
        command_build: str = "./gradlew build -x test --no-daemon",
        command_test: str = "./gradlew test --no-daemon",
        timeout_build: int = 1800,
        timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT
    ) -> Dict[str, object]:
        if not self.was_build:
            self.build_env(command=command_build, timeout=timeout_build)
        return self.run_test(command=command_test, timeout=timeout_test)
    
    def run_test(
        self,
        command: str = "./gradlew test --no-daemon",
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
        stop_container: bool = True
    ) -> Dict[str, object]:
        volumes = self._setup_container_volumes(workdir="/run_dir")
        
        self.start_container(
            image_name=self.image_name,
            container_name=self.container_name,
            volumes=volumes,
            working_dir="/run_dir"
        )
        
        try:
            self.timeout_exec_run("chmod +x gradlew 2>/dev/null || true", timeout=10)
        except Exception:
            pass
        
        gradle_opts = (
            'export GRADLE_OPTS="-Xmx3g -Xms512m '
            '-XX:MaxMetaspaceSize=1g '
            '-Dorg.gradle.daemon=false '
            '-Dorg.gradle.parallel=true"'
        )
        
        full_command = f"bash -c '{gradle_opts} && {command}'"
        
        original_return_code = 1
        
        try:
            self.evaluation_time = time.time()
            result = self.timeout_exec_run(full_command, timeout=timeout)
            if result:
                original_return_code = result.get("returncode", 1)
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Test timeout"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        except Exception as e:
            logger.error(f"Test execution error: {e}")
            self.return_code = 1
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        parsed_reports = []
        report_paths = self._find_test_reports()
        
        for report_path in report_paths:
            parsed_report = parse_junit_xml_report(report_path)
            
            if (parsed_report and 
                isinstance(parsed_report, dict) and 
                parsed_report.get("summary", {}).get("total", 0) > 0):
                parsed_reports.append(parsed_report)
        
        test_results = self._merge_reports(parsed_reports)
        
        if test_results["summary"]["total"] == 0:
            console_stats = parse_gradle_console_output(self.stdout, self.stderr)
            if console_stats["total"] > 0:
                test_results["summary"] = console_stats
                test_results["status"] = (
                    "failed" if (console_stats["failed"] > 0 or console_stats["errors"] > 0) 
                    else "passed"
                )
        
        if test_results.get("status") == "passed":
            self.return_code = 0
        elif test_results.get("status") == "failed":
            self.return_code = 1
        else:
            self.return_code = original_return_code
            if original_return_code == 0:
                test_results["status"] = "passed"
            else:
                test_results["status"] = "failed"
        
        logger.info(
            f"Tests: {test_results['summary']['total']}, "
            f"Passed: {test_results['summary']['passed']}, "
            f"Failed: {test_results['summary']['failed']}, "
            f"Status: {test_results['status']}"
        )
        
        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()
        
        return self._format_results(test_json=test_results)
    
    def _format_results(self, test_json: Optional[Dict] = None) -> Dict[str, object]:
        if test_json and test_json.get("summary", {}).get("total", 0) > 0:
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
                "status": test_json.get("status", "unknown") if test_json else "unknown"
            }
        
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
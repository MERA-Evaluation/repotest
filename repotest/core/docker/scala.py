import json, logging, os, re, time
from functools import cached_property
from typing import Dict, Literal, Optional, cast
from docker.errors import APIError, ImageNotFound
from repotest.constants import DEFAULT_BUILD_TIMEOUT_INT, DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException
from repotest.core.docker.types import CacheMode

logger = logging.getLogger("repotest")

def parse_sbt_stdout(stdout: str) -> Dict[str, object]:
    if not stdout:
        return {}
    
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
    
    for line in stdout.split('\n'):
        if '[info] -' in line or '[info] ScalaTest' in line:
            test_name = line.split('[info]')[-1].strip()
            if test_name and len(test_name) > 3:
                result["tests"].append({
                    "name": test_name,
                    "classname": "",
                    "time": 0,
                    "status": "passed"
                })
                result["summary"]["passed"] += 1
                result["summary"]["total"] += 1
        elif '[error]' in line and 'Failed:' in line:
            match = re.search(r'Failed:\s*(\d+)', line)
            if match:
                result["summary"]["failed"] = int(match.group(1))
        elif '[info] All tests passed' in line or '[success]' in line.lower():
            if result["summary"]["total"] == 0:
                result["summary"]["passed"] = 1
                result["summary"]["total"] = 1
    
    if result["summary"]["total"] > 0:
        result["status"] = "passed" if result["summary"]["failed"] == 0 else "failed"
    else:
        result["status"] = "unknown"
    
    return result


def parse_sbt_json_report(json_path: str) -> Dict[str, object]:
    if not os.path.exists(json_path):
        return {}
    
    try:
        with open(json_path, "r") as f:
            content = f.read()
            if content.strip().startswith("{") or content.strip().startswith("["):
                data = json.loads(content)
                return data
            
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
            
    except (json.JSONDecodeError, ET.ParseError, IOError) as e:
        logger.warning(f"Failed to parse test report: {e}")
        return {}


class ScalaDockerRepo(AbstractDockerRepo):
    
    def __init__(self, 
                 repo: str, 
                 base_commit: str, 
                 default_cache_folder: str = DEFAULT_CACHE_FOLDER,
                 default_url: str = "http://github.com", 
                 image_name: str = "hseeberger/scala-sbt:11.0.12_1.5.5_2.13.6",
                 cache_mode: CacheMode = "volume"
                 ) -> None:
        super().__init__(repo=repo, base_commit=base_commit, default_cache_folder=default_cache_folder,
                         default_url=default_url, image_name=image_name, cache_mode=cache_mode)
        self.stdout = ""
        self.stderr = ""
        self.std = ""
        self.return_code = 0
    
    @cached_property
    def _user_sbt_cache(self) -> str:
        return os.path.expanduser("~/.sbt")
    
    @cached_property
    def _local_sbt_cache(self) -> str:
        return os.path.join(self.cache_folder, ".sbt_cache")
    
    @cached_property
    def _local_ivy_cache(self) -> str:
        return os.path.join(self.cache_folder, ".ivy2_cache")
    
    @cached_property
    def _local_coursier_cache(self) -> str:
        return os.path.join(self.cache_folder, ".coursier_cache")
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("sbt-cache")
            self.create_volume("ivy2-cache")
            self.create_volume("coursier-cache")
            
            volumes["sbt-cache"] = {"bind": "/root/.sbt", "mode": "rw"}
            volumes["ivy2-cache"] = {"bind": "/root/.ivy2", "mode": "rw"}
            volumes["coursier-cache"] = {"bind": "/root/.cache/coursier", "mode": "rw"}
        elif self.cache_mode == "shared":
            if os.path.exists(self._user_sbt_cache):
                volumes[self._user_sbt_cache] = {"bind": "/root/.sbt", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_sbt_cache, exist_ok=True)
            os.makedirs(self._local_ivy_cache, exist_ok=True)
            os.makedirs(self._local_coursier_cache, exist_ok=True)
            volumes[self._local_sbt_cache] = {"bind": "/root/.sbt", "mode": "rw"}
            volumes[self._local_ivy_cache] = {"bind": "/root/.ivy2", "mode": "rw"}
            volumes[self._local_coursier_cache] = {"bind": "/root/.cache/coursier", "mode": "rw"}
        
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
                tests = cast(list[Dict[str, object]], report.get("tests", []))
                merged_result["tests"].extend(tests)
            
            summary = cast(Dict[str, int], report.get("summary", {}))
            merged_result["summary"]["total"] += int(summary.get("total", 0))
            merged_result["summary"]["passed"] += int(summary.get("passed", 0))
            merged_result["summary"]["failed"] += int(summary.get("failed", 0))
            merged_result["summary"]["skipped"] += int(summary.get("skipped", 0))
            merged_result["summary"]["errors"] += int(summary.get("errors", 0))
        
        merged_result["status"] = "passed" if (merged_result["summary"]["failed"] + merged_result["summary"]["errors"]) == 0 and merged_result["summary"]["total"] > 0 else "failed"
        
        return merged_result
    
    def build_env(self, command: str = "sbt compile", timeout: int = DEFAULT_BUILD_TIMEOUT_INT, commit_image: bool = True,
                  stop_container: bool = True, push_image: bool = False) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        sbt_opts = 'export SBT_OPTS="-Xmx4G -Xms2G -XX:+UseG1GC -XX:MaxMetaspaceSize=1G -XX:ReservedCodeCacheSize=256M"'
        
        try:
            self.timeout_exec_run(
                f'bash -c \'{sbt_opts} && echo "Test / parallelExecution := true" >> /run_dir/build.sbt || true\'',
                timeout=30
            )
        except Exception as e:
            logger.warning(f"Failed to configure SBT opts: {e}")
        
        full_command = f'{sbt_opts} && {command}'
        
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c '{full_command}'", timeout=timeout)
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
    
    def __call__(self, command_build: str = "sbt compile", command_test: str = "sbt test", 
                 timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
                 timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT) -> Dict[str, object]:
        if not self.was_build:
            self.build_env(command=command_build, timeout=timeout_build)
        return self.run_test(command=command_test, timeout=timeout_test)
    
    def run_test(self, command: str = "sbt test", timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
                 stop_container: bool = True) -> Dict[str, object]:
        
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        sbt_opts = 'export SBT_OPTS="-Xmx4G -Xms2G -XX:+UseG1GC -XX:MaxMetaspaceSize=1G -XX:ReservedCodeCacheSize=256M"'
        full_command = f'{sbt_opts} && {command}'
        
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c '{full_command}'", timeout=timeout)
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        parsed_reports = []
        report_files_found = set()
        
        report_search_paths = [
            (os.path.join(self.cache_folder, "target"), True),
            (os.path.join(self.cache_folder, "target/test-reports"), True),
            (os.path.join(self.cache_folder, "target/junit-xml-reports"), True),
            (os.path.join(self.cache_folder, "target/surefire-reports"), True),
            (os.path.join(self.cache_folder, "test-output"), True),
            (self.cache_folder, False),
        ]
        
        for search_path, recursive in report_search_paths:
            if not os.path.exists(search_path):
                continue
            
            if recursive and os.path.isdir(search_path):
                for root, dirs, files in os.walk(search_path):
                    for filename in files:
                        if filename.endswith(".xml") and ("TEST-" in filename or "test" in filename.lower()):
                            report_path = os.path.join(root, filename)
                            if report_path not in report_files_found:
                                parsed_report = parse_sbt_json_report(report_path)
                                if isinstance(parsed_report, dict) and cast(Dict, parsed_report).get("summary", {}).get("total", 0) > 0:
                                    parsed_reports.append(parsed_report)
                                    report_files_found.add(report_path)
            elif os.path.isdir(search_path):
                for filename in os.listdir(search_path):
                    if filename.endswith(".xml") and ("TEST-" in filename or "test" in filename.lower()):
                        report_path = os.path.join(search_path, filename)
                        if report_path not in report_files_found:
                            parsed_report = parse_sbt_json_report(report_path)
                            if isinstance(parsed_report, dict) and cast(Dict, parsed_report).get("summary", {}).get("total", 0) > 0:
                                parsed_reports.append(parsed_report)
                                report_files_found.add(report_path)

        test_results = self._merge_reports(parsed_reports)
        
        if not test_results and self.stdout:
            logger.info("XML reports not found, parsing stdout as fallback")
            test_results = parse_sbt_stdout(self.stdout)
        
        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()
        
        return self._format_results(sbt_json=test_results)
    
    def _format_results(self, sbt_json: Optional[Dict] = None) -> Dict[str, object]:
        if sbt_json and "summary" in sbt_json:
            parser_result = sbt_json
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
            "report": sbt_json or {},
            "time": self.evaluation_time, 
            "run_id": self.run_id
        }
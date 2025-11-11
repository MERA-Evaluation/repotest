import json, logging, os, time
from functools import cached_property
from typing import Dict, Literal, Optional
from docker.errors import APIError, ImageNotFound
from repotest.constants import DEFAULT_BUILD_TIMEOUT_INT, DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException
from repotest.core.docker.types import CacheMode

logger = logging.getLogger("repotest")

def parse_ruby_test_report(report_path: str) -> Dict[str, object]:
    if not os.path.exists(report_path):
        return {}
    
    try:
        with open(report_path, "r") as f:
            content = f.read()
            
            if content.strip().startswith("{") or content.strip().startswith("["):
                data = json.loads(content)
                
                if "examples" in data or "summary" in data:
                    return _parse_rspec_json(data)
                
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
                    "errors": 0,
                    "collected": 0
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
            result["summary"]["collected"] = result["summary"]["total"]
            result["status"] = "passed" if (result["summary"]["failed"] + result["summary"]["errors"]) == 0 and result["summary"]["total"] > 0 else "failed"
            
            return result
            
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Failed to parse test report: {e}")
        return {}


def _parse_rspec_json(data: Dict) -> Dict[str, object]:
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
    
    if "summary" in data:
        summary = data["summary"]
        result["summary"]["total"] = summary.get("example_count", 0)
        result["summary"]["failed"] = summary.get("failure_count", 0)
        result["summary"]["skipped"] = summary.get("pending_count", 0)
        result["summary"]["passed"] = result["summary"]["total"] - result["summary"]["failed"] - result["summary"]["skipped"]
    
    for example in data.get("examples", []):
        test_info = {
            "name": example.get("description", ""),
            "classname": example.get("full_description", ""),
            "time": example.get("run_time", 0),
            "status": example.get("status", "unknown")
        }
        
        if example.get("exception"):
            test_info["message"] = example["exception"].get("message", "")
            test_info["details"] = example["exception"].get("backtrace", "")
        
        result["tests"].append(test_info)
    
    result["summary"]["collected"] = result["summary"]["total"]
    result["status"] = "passed" if result["summary"]["failed"] == 0 and result["summary"]["total"] > 0 else ("failed" if result["summary"]["failed"] > 0 else "unknown")
    
    return result


class RubyDockerRepo(AbstractDockerRepo):
    def __init__(self, 
                 repo: str, 
                 base_commit: str, 
                 default_cache_folder: str = DEFAULT_CACHE_FOLDER,
                 default_url: str = "http://github.com",
                 image_name: str = "ruby:3.2",
                 cache_mode: CacheMode = "volume"
                ) -> None:
        super().__init__(repo=repo, base_commit=base_commit, default_cache_folder=default_cache_folder,
                         default_url=default_url, image_name=image_name, cache_mode=cache_mode)
        self.stdout = ""
        self.stderr = ""
        self.std = ""
        self.return_code = 0
    
    @cached_property
    def _user_gem_cache(self) -> str:
        return os.path.expanduser("~/.gem")
    
    @cached_property
    def _local_gem_cache(self) -> str:
        return os.path.join(self.cache_folder, ".gem_cache")
    
    @cached_property
    def _local_bundle_cache(self) -> str:
        return os.path.join(self.cache_folder, ".bundle_cache")
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("gem-cache")
            self.create_volume("bundle-cache")
            volumes["gem-cache"] = {"bind": "/usr/local/bundle", "mode": "rw"}
            volumes["bundle-cache"] = {"bind": "/root/.bundle", "mode": "rw"}
        elif self.cache_mode == "shared":
            if os.path.exists(self._user_gem_cache):
                volumes[self._user_gem_cache] = {"bind": "/usr/local/bundle", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_gem_cache, exist_ok=True)
            os.makedirs(self._local_bundle_cache, exist_ok=True)
            volumes[self._local_gem_cache] = {"bind": "/usr/local/bundle", "mode": "rw"}
            volumes[self._local_bundle_cache] = {"bind": "/root/.bundle", "mode": "rw"}
        
        return volumes
    
    def _merge_reports(self, reports: list[Dict[str, object]]) -> Dict[str, object]:
        if not reports:
            return {}
        
        merged_result = {
            "tests": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "collected": 0}
        }
        
        for report in reports:
            if "tests" in report:
                merged_result["tests"].extend(report.get("tests", []))
            
            summary: Dict = report.get("summary", {})
            merged_result["summary"]["total"] += summary.get("total", 0)
            merged_result["summary"]["passed"] += summary.get("passed", 0)
            merged_result["summary"]["failed"] += summary.get("failed", 0)
            merged_result["summary"]["skipped"] += summary.get("skipped", 0)
            merged_result["summary"]["errors"] += summary.get("errors", 0)
        
        merged_result["summary"]["collected"] = merged_result["summary"]["total"]
        merged_result["status"] = "passed" if (merged_result["summary"]["failed"] + merged_result["summary"]["errors"]) == 0 and merged_result["summary"]["total"] > 0 else "failed"
        
        return merged_result
    
    def _configure_test_reporters(self, command: str) -> None:
        try:
            result = self.timeout_exec_run(
                "bash -c 'cat /run_dir/Gemfile 2>/dev/null || echo \"\"'",
                timeout=30
            ) or {}
            
            gemfile_content = result.get("stdout", b"").decode("utf-8", errors="ignore")
            
            if "rspec" in gemfile_content.lower() or "rspec" in command.lower():
                self.timeout_exec_run(
                    "bash -c 'gem install rspec_junit_formatter || true'",
                    timeout=120
                )
                
                rspec_config = """require 'rspec_junit_formatter'
                                RSpec.configure do |config|
                                config.add_formatter RspecJunitFormatter, '/run_dir/test-results/rspec.xml'
                                config.add_formatter :json, '/run_dir/test-results/rspec.json'
                                end
                                """
                self.timeout_exec_run(
                    "bash -c \"cat <<'EOF' > /run_dir/.rspec_formatter.rb\n" + rspec_config + "\nEOF\"",
                    timeout=30
                )
            
            if "minitest" in gemfile_content.lower() or "minitest" in command.lower():
                self.timeout_exec_run(
                    "bash -c 'gem install minitest-reporters || true'",
                    timeout=120
                )
                
                minitest_config = """require 'minitest/reporters'
                                    Minitest::Reporters.use! [
                                    Minitest::Reporters::JUnitReporter.new('/run_dir/test-results')
                                    ]
                                """
                self.timeout_exec_run(
                    "bash -c \"cat <<'EOF' > /run_dir/.minitest_formatter.rb\n" + minitest_config + "\nEOF\"",
                    timeout=30
                )
        except Exception as e:
            logger.warning(f"Failed to configure test reporters: {e}")
    
    def build_env(self, command: str = "bundle install", timeout: int = DEFAULT_BUILD_TIMEOUT_INT, commit_image: bool = True,
                  stop_container: bool = True, push_image: bool = False) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        self._configure_test_reporters(command)
        
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c 'mkdir -p /run_dir/test-results && {command}'", timeout=timeout)
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
    
    def __call__(self, command_build: str = "bundle install", command_test: str = "bundle exec rspec", timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
                 timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT) -> Dict[str, object]:
        if not self.was_build:
            self.build_env(command=command_build, timeout=timeout_build)
        return self.run_test(command=command_test, timeout=timeout_test)
    
    def run_test(self, command: str = "bundle exec rspec", timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
                 stop_container: bool = True) -> Dict[str, object]:
        
        volumes = self._setup_container_volumes(workdir="/run_dir")
        self.start_container(image_name=self.image_name, container_name=self.container_name,
                           volumes=volumes, working_dir="/run_dir")
        
        self._configure_test_reporters(command)
        
        try:
            self.evaluation_time = time.time()
            
            modified_command = command
            prefix = ""
            if "rspec" in command.lower() and "--format" not in command:
                modified_command = f"{command} --require ./.rspec_formatter.rb"
            elif "minitest" in command.lower() or "test" in command.lower():
                prefix = 'RUBYOPT="-r ./.minitest_formatter.rb" '
                modified_command = command
            
            self.timeout_exec_run(f"bash -c 'mkdir -p /run_dir/test-results && {prefix}{modified_command}'", timeout=timeout)
                
        except TimeOutException:
            self.return_code = 2
            self.stderr = b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()
        
        all_report_files = set()
        
        report_dir = os.path.join(self.cache_folder, "test-results")
        if os.path.exists(report_dir) and os.path.isdir(report_dir):
            for filename in os.listdir(report_dir):
                if filename.endswith((".json", ".xml")):
                    all_report_files.add(os.path.join(report_dir, filename))
        
        known_paths = [
            os.path.join(self.cache_folder, "test-results/test-report.xml"),
            os.path.join(self.cache_folder, "test/reports"),
        ]
        
        for report_path in known_paths:
            if not os.path.exists(report_path):
                continue
            if os.path.isfile(report_path):
                all_report_files.add(report_path)
            elif os.path.isdir(report_path):
                    for filename in os.listdir(report_path):
                        if filename.endswith((".json", ".xml")):
                            all_report_files.add(os.path.join(report_path, filename))

        parsed_reports = []
        for report_file in all_report_files:
            parsed_report = parse_ruby_test_report(report_file)
            if parsed_report and parsed_report.get("summary", {}).get("total", 0) > 0:
                parsed_reports.append(parsed_report)

        test_results = self._merge_reports(parsed_reports)
        
        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
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
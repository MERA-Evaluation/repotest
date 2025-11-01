import json
import logging
import os
import time
from functools import cached_property
from typing import Dict, Optional
from docker.errors import APIError, ImageNotFound
from repotest.constants import (DEFAULT_BUILD_TIMEOUT_INT,
                                DEFAULT_CACHE_FOLDER, DEFAULT_EVAL_TIMEOUT_INT)
from repotest.core.docker.base import AbstractDockerRepo
from repotest.core.exceptions import TimeOutException
from repotest.parsers.python.javascript_stout import parse_test_stdout
from repotest.core.docker.types import CacheMode
import xmltodict

logger = logging.getLogger("repotest")
    

class TypeScriptDockerRepo(AbstractDockerRepo):

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = "node:18",
        cache_mode: CacheMode = "volume",
    ) -> None:
        super().__init__(
            repo=repo,
            base_commit=base_commit,
            default_cache_folder=default_cache_folder,
            default_url=default_url,
            image_name=image_name,
            cache_mode=cache_mode,
        )

      
    @cached_property
    def _user_npm_cache(self) -> str:
        return os.path.expanduser("~/.npm")
    
    @cached_property
    def _local_npm_cache(self) -> str:
        return os.path.join(self.cache_folder, ".npm_cache")
    
    @cached_property
    def _local_typescript_cache(self) -> str:
        return os.path.join(self.cache_folder, ".typescript_cache")
    
    def _setup_container_volumes(self, workdir: Optional[str] = None) -> Dict[str, Dict[str, str]]:
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}
        
        if self.cache_mode == "volume":
            self.create_volume("npm-cache")
            self.create_volume("typescript-cache")
            volumes["npm-cache"] = {"bind": "/root/.npm", "mode": "rw"}
            volumes["typescript-cache"] = {"bind": "/root/.cache/typescript", "mode": "rw"}
        elif self.cache_mode == "shared":
            if os.path.exists(self._user_npm_cache):
                volumes[self._user_npm_cache] = {"bind": "/root/.npm", "mode": "rw"}
        elif self.cache_mode == "local":
            os.makedirs(self._local_npm_cache, exist_ok=True)
            os.makedirs(self._local_typescript_cache, exist_ok=True)
            volumes[self._local_npm_cache] = {"bind": "/root/.npm", "mode": "rw"}
            volumes[self._local_typescript_cache] = {"bind": "/root/.cache/typescript", "mode": "rw"}
        
        return volumes

    def build_env(
        self,
        command: str = "npm install --legacy-peer-deps --loglevel=error;npm install mocha-junit-reporter --legacy-peer-deps --loglevel=error",
        timeout: int = DEFAULT_BUILD_TIMEOUT_INT,
        commit_image=True,
        stop_container=True,
        push_image=False,
    ) -> Dict[str, object]:
        self.container_name = self.default_container_name
        volumes = self._setup_container_volumes(workdir="/run_dir")

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
            working_dir="/run_dir",
        )
        command = "ulimit -n 65535;\n" + command
        try:
            self.evaluation_time = time.time()
            self.timeout_exec_run(f"bash -c '{command}'", timeout=timeout)
        except TimeOutException:
            logger.error("Timeout exception during build_env")
            self.return_code = 2
            self.stderr += b"Timeout exception"
            self._FALL_WITH_TIMEOUT_EXCEPTION = True
        finally:
            self.evaluation_time = time.time() - self.evaluation_time
            self._convert_std_from_bytes_to_str()

        if self._FALL_WITH_TIMEOUT_EXCEPTION:
            raise TimeOutException(f"Command '{command}' timed out after {timeout}s.")

        try:
            if "added" in self.stdout.lower() and "packages" in self.stdout.lower():
                logger.info("npm install completed successfully (packages added), overriding return code")
                self.return_code = 0
            elif "audited" in self.stdout.lower() and "packages" in self.stdout.lower():
                logger.info("npm install completed successfully (packages audited), overriding return code")
                self.return_code = 0
        except Exception as e:
            logger.debug(f"Could not check npm install success: {e}")

        if commit_image:
            self._commit_container_image()

        if push_image:
            self.push_image()

        if stop_container:
            self.stop_container()

        return self._format_results()

    def _image_exists(self, name: str) -> bool:
        try:
            self.docker_client.images.get(name)
            return True
        except ImageNotFound:
            return False
        except APIError as e:
            logger.warning(f"Docker API error when checking image: {e}")
            return False
    
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

    @property
    def was_build(self) -> bool:
        return self._image_exists(self.default_image_name)

    def _mock_path(self, command: str) -> str:
        prefix = """ulimit -n 65535;"""
        return command if command.startswith(prefix) else prefix + command
    
    def __call__(self, 
                 command_build: str = "npm install --legacy-peer-deps --loglevel=error;npm install mocha-junit-reporter --legacy-peer-deps --loglevel=error", 
                 command_test: str = "npm test -- --reporter mocha-junit-reporter", 
                 timeout_build: int = DEFAULT_BUILD_TIMEOUT_INT,
                 timeout_test: int = DEFAULT_EVAL_TIMEOUT_INT) -> Dict[str, object]:
        if not self.was_build:
            self.build_env(command=command_build, timeout=timeout_build)
        return self.run_test(command=command_test, timeout=timeout_test)
    
    def read_mocha_xml(self):
        fn_mocha = os.path.join(self.cache_folder, 'test-results.xml')
        if not os.path.exists(fn_mocha):
            logger.critical("file %s not exist (full: %s)", "test-results.xml", fn_mocha)
            return {}
        
        try:
            dct = xmltodict.parse(open(fn_mocha, "r").read())
            assert 'summary' not in dct

            n_total = int(dct['testsuites']['@tests'])
            n_failed = int(dct['testsuites']['@failures'])
            n_errors = int(dct['testsuites'].get('@errors', 0))
            n_skipped = int(dct['testsuites'].get('@skipped', 0))
            
            dct_summary = {
                'total': n_total,
                'passed': n_total - n_failed - n_errors - n_skipped,
                'failed': n_failed,
                'errors': n_errors,
                'skipped': n_skipped,
                'collected': n_total
            }
            
            return {"summary": dct_summary, **dct}
        except Exception as e:
            logger.warning(f"Failed to parse mocha XML: {e}")
            return {}

    def read_jest_json(self):
        fn_jest = os.path.join(self.cache_folder, 'jest-results.json')
        if not os.path.exists(fn_jest):
            logger.critical("file %s not exist (full: %s)", "jest-results.json", fn_jest)
            return {}

        try:
            dct = json.load(open(fn_jest, "r"))
            assert 'summary' not in dct

            n_total = dct['numTotalTests']
            n_passed = dct['numPassedTests']
            n_failed = dct['numFailedTests']
            n_pending = dct.get('numPendingTests', 0)
            n_todo = dct.get('numTodoTests', 0)

            dct_summary = {
                'total': n_total,
                'passed': n_passed,
                'failed': n_failed,
                'skipped': n_pending + n_todo,
                'errors': 0,
                'collected': n_total
            }

            return {"summary": dct_summary, **dct}
        except Exception as e:
            logger.warning(f"Failed to parse jest JSON: {e}")
            return {}

    def read_jest_or_mocha(self):
        fn_mocha = os.path.join(self.cache_folder, 'test-results.xml')
        fn_jest  = os.path.join(self.cache_folder, 'jest-results.json')

        test_exist_mocha = os.path.exists(fn_mocha)
        test_exist_jest = os.path.exists(fn_jest)

        if test_exist_mocha & test_exist_jest:
            logger.debug("Found both mocha and jest results, using jest")
            return self.read_jest_json()
        elif not (test_exist_mocha | test_exist_jest):
            logger.critical("There are no mocha or jest results")
            return {}
        elif test_exist_mocha:
            logger.debug("Find mocha test")
            return self.read_mocha_xml()
        elif test_exist_jest:
            logger.debug("Find jest test")
            return self.read_jest_json()
        
        return {}

    def run_test(
        self,
        command: str = "npm test -- --reporter mocha-junit-reporter",
        timeout: int = DEFAULT_EVAL_TIMEOUT_INT,
        stop_container: bool = True,
    ) -> Dict[str, object]:
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
        
        report = self.read_jest_or_mocha()
        
        if report and isinstance(report, dict) and 'summary' in report:
            summary = report['summary']
            if isinstance(summary, dict):
                total = summary.get('total', 0)
                failed = summary.get('failed', 0)
                if total > 0 and failed == 0:
                    logger.info("All tests passed, overriding return code to 0")
                    self.return_code = 0

        if stop_container and not self._FALL_WITH_TIMEOUT_EXCEPTION:
            self.stop_container()

        return self._format_results(report = report)

    def _format_results(self, report: Optional[Dict] = None) -> Dict[str, object]:
        parser_result = report if report else parse_test_stdout(self.stdout)
        
        if parser_result and isinstance(parser_result, dict) and 'summary' in parser_result:
            pass
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
            "report": report,
            "time": self.evaluation_time,
            "run_id": self.run_id,
        }
"""PHP language Docker repository management."""

import json
import logging
import os
import re
from functools import cached_property
from typing import Dict, Literal, Optional

from repotest.constants import (
    DEFAULT_BUILD_TIMEOUT_INT,
    DEFAULT_CACHE_FOLDER,
    DEFAULT_EVAL_TIMEOUT_INT,
)
from repotest.core.docker.base import AbstractDockerRepo

logger = logging.getLogger("repotest")

DOCKER_PHP_DEFAULT_IMAGE = "composer:latest"


class PhpDockerRepo(AbstractDockerRepo):
    """A class for managing and testing PHP repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = DOCKER_PHP_DEFAULT_IMAGE,
        cache_mode: Literal["download", "shared", "local", "volume"] = "volume",
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
    def _user_composer_cache(self) -> str:
        return os.path.expanduser("~/.composer")

    @cached_property
    def _local_composer_cache(self) -> str:
        return os.path.join(self.cache_folder, ".composer_cache")

    def _setup_container_volumes(self, workdir=None) -> Dict[str, Dict[str, str]]:
        """Configure volume mounts based on cache mode."""
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_composer_cache] = {"bind": "/tmp/composer", "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_composer_cache] = {"bind": "/tmp/composer", "mode": "rw"}
        elif self.cache_mode == "volume":
            self.create_volume("composer-cache")
            logger.debug("cache_mode=volume")
            volumes["composer-cache"] = {"bind": "/tmp/composer", "mode": "rw"}

        return volumes

    def _parse_phpunit_test_output(self, output: str) -> Dict[str, object]:
        """Parse PHPUnit test output."""
        results = {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "errors": 0}
        
        jsonl_path = os.path.join(self.cache_folder, "gotest_results.jsonl")
        if os.path.exists(jsonl_path):
            try:
                with open(jsonl_path, "r") as f:
                    content = f.read()
                    
                ok_match = re.search(r"OK \((\d+) tests?", content)
                failures_match = re.search(r"FAILURES!\s*Tests:\s*(\d+)", content)
                errors_match = re.search(r"Errors:\s*(\d+)", content)
                
                if ok_match:
                    results["passed"] = int(ok_match.group(1))
                    results["total"] = results["passed"]
                elif failures_match:
                    results["total"] = int(failures_match.group(1))
                    if errors_match:
                        results["errors"] = int(errors_match.group(1))
                    
            except IOError as e:
                logger.warning(f"Failed to parse PHPUnit test results: {e}")
        
        return results
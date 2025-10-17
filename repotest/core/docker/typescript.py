"""TypeScript language Docker repository management."""

import json
import logging
import os
from functools import cached_property
from typing import Dict, Literal, Optional

from repotest.constants import (
    DEFAULT_BUILD_TIMEOUT_INT,
    DEFAULT_CACHE_FOLDER,
    DEFAULT_EVAL_TIMEOUT_INT,
)
from repotest.core.docker.base import AbstractDockerRepo

logger = logging.getLogger("repotest")

DOCKER_TYPESCRIPT_DEFAULT_IMAGE = "node:latest"


class TypescriptDockerRepo(AbstractDockerRepo):
    """A class for managing and testing TypeScript repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = DOCKER_TYPESCRIPT_DEFAULT_IMAGE,
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
    def _user_yarn_cache(self) -> str:
        return os.path.expanduser("~/.cache/yarn")

    @cached_property
    def _local_yarn_cache(self) -> str:
        return os.path.join(self.cache_folder, ".yarn_cache")

    def _setup_container_volumes(self, workdir=None) -> Dict[str, Dict[str, str]]:
        """Configure volume mounts based on cache mode."""
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_yarn_cache] = {"bind": "/usr/local/share/.cache/yarn", "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_yarn_cache] = {"bind": "/usr/local/share/.cache/yarn", "mode": "rw"}
        elif self.cache_mode == "volume":
            self.create_volume("yarn-cache")
            logger.debug("cache_mode=volume")
            volumes["yarn-cache"] = {"bind": "/usr/local/share/.cache/yarn", "mode": "rw"}

        return volumes

    def _parse_jest_test_output(self, output: str) -> Dict[str, object]:
        """Parse Jest test output."""
        results = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
        
        json_path = os.path.join(self.cache_folder, "gotest_results.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r") as f:
                    test_data = json.load(f)
                    
                if "numPassedTests" in test_data:
                    results["passed"] = test_data["numPassedTests"]
                if "numFailedTests" in test_data:
                    results["failed"] = test_data["numFailedTests"]
                if "numPendingTests" in test_data:
                    results["skipped"] = test_data["numPendingTests"]
                if "numTotalTests" in test_data:
                    results["total"] = test_data["numTotalTests"]
                    
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to parse Jest test results: {e}")
        
        if results["total"] == 0:
            results["total"] = results["passed"] + results["failed"] + results["skipped"]
            
        return results
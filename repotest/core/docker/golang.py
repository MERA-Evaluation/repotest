"""Go language Docker repository management."""

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

DOCKER_GOLANG_DEFAULT_IMAGE = "golang:latest"


class GolangDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Go repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = DOCKER_GOLANG_DEFAULT_IMAGE,
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
    def _user_go_cache(self) -> str:
        return os.path.expanduser("~/.cache/go-build")

    @cached_property
    def _local_go_cache(self) -> str:
        return os.path.join(self.cache_folder or DEFAULT_CACHE_FOLDER, ".go_cache")

    def _setup_container_volumes(self, workdir=None) -> Dict[str, Dict[str, str]]:
        """Configure volume mounts based on cache mode."""
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_go_cache] = {"bind": "/go", "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_go_cache] = {"bind": "/go", "mode": "rw"}
        elif self.cache_mode == "volume":
            self.create_volume("go-cache")
            logger.debug("cache_mode=volume")
            volumes["go-cache"] = {"bind": "/go", "mode": "rw"}

        return volumes

    def _parse_go_test_output(self, output: str) -> Dict[str, int]:
        """Parse Go test JSON output."""
        results = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
        
        jsonl_path = os.path.join(self.cache_folder or DEFAULT_CACHE_FOLDER, "gotest_results.jsonl")
        if os.path.exists(jsonl_path):
            try:
                with open(jsonl_path, "r") as f:
                    for line in f:
                        if line.strip():
                            test_data = json.loads(line)
                            if test_data.get("Action") == "pass":
                                results["passed"] += 1
                            elif test_data.get("Action") == "fail":
                                results["failed"] += 1
                            elif test_data.get("Action") == "skip":
                                results["skipped"] += 1
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to parse Go test results: {e}")
        
        results["total"] = results["passed"] + results["failed"] + results["skipped"]
        return results
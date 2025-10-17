"""Ruby language Docker repository management."""

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

DOCKER_RUBY_DEFAULT_IMAGE = "ruby:latest"


class RubyDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Ruby repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = DOCKER_RUBY_DEFAULT_IMAGE,
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
    def _user_gem_cache(self) -> str:
        return os.path.expanduser("~/.gem")

    @cached_property
    def _local_gem_cache(self) -> str:
        return os.path.join(self.cache_folder, ".gem_cache")

    def _setup_container_volumes(self, workdir=None) -> Dict[str, Dict[str, str]]:
        """Configure volume mounts based on cache mode."""
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_gem_cache] = {"bind": "/usr/local/bundle", "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_gem_cache] = {"bind": "/usr/local/bundle", "mode": "rw"}
        elif self.cache_mode == "volume":
            self.create_volume("gem-cache")
            logger.debug("cache_mode=volume")
            volumes["gem-cache"] = {"bind": "/usr/local/bundle", "mode": "rw"}

        return volumes

    def _parse_rspec_test_output(self, output: str) -> Dict[str, object]:
        """Parse RSpec test output."""
        results = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
        
        json_path = os.path.join(self.cache_folder, "rspec_results.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r") as f:
                    test_data = json.load(f)
                    
                summary = test_data.get("summary", {})
                results["total"] = summary.get("example_count", 0)
                results["failed"] = summary.get("failure_count", 0)
                results["skipped"] = summary.get("pending_count", 0)
                results["passed"] = results["total"] - results["failed"] - results["skipped"]
                    
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to parse RSpec test results: {e}")
        
        return results
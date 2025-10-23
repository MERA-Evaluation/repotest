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

DOCKER_NODEJS_DEFAULT_IMAGE = "node:18"


class NodejsDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Node.js repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = DOCKER_NODEJS_DEFAULT_IMAGE,
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
    def _user_npm_cache(self) -> str:
        return os.path.expanduser("~/.npm")

    @cached_property
    def _local_npm_cache(self) -> str:
        return os.path.join(self.cache_folder, ".npm_cache")

    def _setup_container_volumes(self, workdir=None) -> Dict[str, Dict[str, str]]:
        """Configure volume mounts based on cache mode."""
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_npm_cache] = {"bind": "/root/.npm", "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_npm_cache] = {"bind": "/root/.npm", "mode": "rw"}
        elif self.cache_mode == "volume":
            self.create_volume("npm-cache")
            logger.debug("cache_mode=volume")
            volumes["npm-cache"] = {"bind": "/root/.npm", "mode": "rw"}

        return volumes

    def _parse_npm_test_output(self, output: str) -> Dict[str, object]:
        """Parse npm/jest test output."""
        results = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
        
        txt_path = os.path.join(self.cache_folder, "test_results.txt")
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r") as f:
                    content = f.read()
                    
                import re
                passed_match = re.search(r"(\d+)\s+passed", content)
                failed_match = re.search(r"(\d+)\s+failed", content)
                skipped_match = re.search(r"(\d+)\s+skipped", content)
                
                if passed_match:
                    results["passed"] = int(passed_match.group(1))
                if failed_match:
                    results["failed"] = int(failed_match.group(1))
                if skipped_match:
                    results["skipped"] = int(skipped_match.group(1))
                    
            except IOError as e:
                logger.warning(f"Failed to parse npm test results: {e}")
        
        results["total"] = results["passed"] + results["failed"] + results["skipped"]
        return results
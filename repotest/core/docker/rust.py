"""Rust language Docker repository management."""

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

DOCKER_RUST_DEFAULT_IMAGE = "rust:latest"


class RustDockerRepo(AbstractDockerRepo):
    """A class for managing and testing Rust repositories in a Docker container."""

    def __init__(
        self,
        repo: str,
        base_commit: str,
        default_cache_folder: str = DEFAULT_CACHE_FOLDER,
        default_url: str = "http://github.com",
        image_name: str = DOCKER_RUST_DEFAULT_IMAGE,
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
    def _user_cargo_cache(self) -> str:
        return os.path.expanduser("~/.cargo")

    @cached_property
    def _local_cargo_cache(self) -> str:
        return os.path.join(self.cache_folder, ".cargo_cache")

    def _setup_container_volumes(self, workdir=None) -> Dict[str, Dict[str, str]]:
        """Configure volume mounts based on cache mode."""
        volumes = {}
        if workdir:
            volumes[self.cache_folder] = {"bind": workdir, "mode": "rw"}

        if self.cache_mode == "shared":
            volumes[self._user_cargo_cache] = {"bind": "/usr/local/cargo", "mode": "rw"}
        elif self.cache_mode == "local":
            volumes[self._local_cargo_cache] = {"bind": "/usr/local/cargo", "mode": "rw"}
        elif self.cache_mode == "volume":
            self.create_volume("cargo-cache")
            logger.debug("cache_mode=volume")
            volumes["cargo-cache"] = {"bind": "/usr/local/cargo", "mode": "rw"}

        return volumes

    def _parse_cargo_test_output(self, output: str) -> Dict[str, object]:
        """Parse Cargo test output."""
        results = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
        
        txt_path = os.path.join(self.cache_folder, "test_results.txt")
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r") as f:
                    content = f.read()
                    
                passed_match = re.search(r"test result:.*?(\d+)\s+passed", content)
                failed_match = re.search(r"(\d+)\s+failed", content)
                ignored_match = re.search(r"(\d+)\s+ignored", content)
                
                if passed_match:
                    results["passed"] = int(passed_match.group(1))
                if failed_match:
                    results["failed"] = int(failed_match.group(1))
                if ignored_match:
                    results["skipped"] = int(ignored_match.group(1))
                    
            except IOError as e:
                logger.warning(f"Failed to parse Cargo test results: {e}")
        
        results["total"] = results["passed"] + results["failed"] + results["skipped"]
        return results
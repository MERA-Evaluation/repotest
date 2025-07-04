import os
from abc import ABC, abstractmethod

import docker
from docker.errors import DockerException, NotFound, APIError
from repotest.core.base import AbstractRepo
from repotest.core.exceptions import DockerStartContainerFailed, TimeOutException
# from repotest.utils.timeout import  timeout_decorator, TimeOutException
from repotest.constants import DEFAULT_EVAL_TIMEOUT_INT, DEFAULT_BUILD_TIMEOUT_INT, DEFAULT_CACHE_FOLDER, \
                              DOCKER_IMAGE_PREFIX, DOCKER_CONTAINER_PREFIX, DEFAULT_CONTAINER_MEM_LIMIT, \
                              DOCKER_REGISTRY_URI, S3_BUCKET, DEFAULT_COMMIT_TIMEOUT_INT

from git import GitCommandError
from tenacity import retry, stop_after_attempt, wait_chain, wait_fixed

from functools import cached_property
import logging
import concurrent.futures
from typing import List

logger = logging.getLogger("repotest") 

class AbstractDockerRepo(AbstractRepo):
    """
    A class for managing and testing Java repositories in a Docker container.

    Attributes
    ----------
    test_timeout : int
        Maximum time (in seconds) to wait for test execution (default is 60 seconds).
    """
    _TEST_EVAL_TIMEOUT = DEFAULT_EVAL_TIMEOUT_INT
    MEM_LIMIT = DEFAULT_CONTAINER_MEM_LIMIT
    _FALL_WITH_TIMEOUT_EXCEPTION = False

    def __init__(self, 
                 repo: str, 
                 base_commit: str,
                 default_cache_folder: str = DEFAULT_CACHE_FOLDER, 
                 default_url: str = 'http://github.com',
                 image_name: str = "maven:3.9.9-eclipse-temurin-23-alpine",
                 cache_mode: str = "local"
                 ):
        """
        Initializes the Docker repository manager.

        Parameters
        ----------
        repo : str
            The repository name.
        base_commit : str
            The base commit for the repository.
        default_cache_folder : str, optional
            Default folder for cache storage (default is '~/.cache/repo_test/').
        default_url : str, optional
            The URL of the repository (default is 'http://github.com').
        image_name : str, optional
            The Docker image name to use (default is "python:3.10-slim").
        cache_mode : str, optional
            The cache mode to use, must be one of ('download', 'shared', 'local') (default is "local").
        """
        super().__init__(
            repo=repo,
            base_commit=base_commit,
            default_cache_folder=default_cache_folder,
            default_url=default_url
        )

        self.image_name = image_name
        assert cache_mode in ("download", "shared", "local", "volume", "build")
        self.cache_mode = cache_mode
        self.docker_client
    
    def change_mem_limit(self, mem_limit: str) -> None:
        """Change memory limit in container"""
        assert mem_limit.endswith("g") or mem_limit.endswith("G"), "Memory limit must be specified in GB"
        assert int(mem_limit[:-1]) > 0, "Memory limit must be greater than 0"
        self.MEM_LIMIT = mem_limit

    @property
    def default_image_name(self) -> str:
        return DOCKER_IMAGE_PREFIX + self.instance_id
    
    @property
    def default_container_name(self) -> str:
        return DOCKER_CONTAINER_PREFIX + self.instance_id
    
    @cached_property
    def container_name(self):
        return self.default_container_name + "-" + self.run_id
    
    @cached_property
    def docker_client(self):
        #ToDo: In case of strange errors like that:
        # ReadTimeout: UnixHTTPConnectionPool(host='localhost', port=None): Read timed out. (read timeout=60)
        # delete timeout here
        return docker.from_env(timeout = DEFAULT_COMMIT_TIMEOUT_INT)
    
    @cached_property
    def RANDDOM_CONTAINER_CPUSER_CPUS(self):
        #ToDo: handle case 1 repo = 1,2,3 cpu
        #ToDo: handle case task1_cpu != task2_cpu

        import random
        import os
        # Get total available CPU cores
        TOTAL_CPUS = os.cpu_count()  # or manually set (e.g., TOTAL_CPUS = 64)

        # Assign 1 random CPU per container
        DEFAULT_CONTAINER_CPUSET_CPUS = str(random.randint(0, TOTAL_CPUS - 1))
        # Debug this
        logger.debug("DEFAULT_CONTAINER_CPUSET_CPUS id=%s : %s"%(id(self), DEFAULT_CONTAINER_CPUSET_CPUS))
        #print(id(self), "DEFAULT_CONTAINER_CPUSET_CPUS", DEFAULT_CONTAINER_CPUSET_CPUS)
        return DEFAULT_CONTAINER_CPUSET_CPUS
    
    @retry(
        stop=stop_after_attempt(2),  # Retry 2 times
        wait=wait_chain(
            wait_fixed(1),  # First retry after 1s
            wait_fixed(3)   # Second retry after 3s
        )
    )
    def start_container(self, 
                     image_name, 
                     container_name,
                     volumes = {},
                     detach=True,
                     stdin_open=True, # Keep stdin open for interaction
                     tty=True,
                     command="/bin/bash",  # Start a shell session initially
                     remove=True,
                     working_dir=None
                     ):
        try:
            if self.cache_folder not in volumes:
                raise ValueError(f"{self.cache_folder} should be at volumes")

            logger.debug(f"""self.container = self.docker_client.containers.run(image={image_name},
                                                               name={container_name},
                                                               detach={detach},
                                                               stdin_open={stdin_open}, # Keep stdin open for interaction
                                                               tty={tty},
                                                               volumes={volumes},
                                                               working_dir={working_dir},
                                                               command={command},  # Start a shell session initially
                                                               remove={remove},
                                                               mem_limit={self.MEM_LIMIT},  # Limit container memory to 10GB
                                                               environment="PIP_ROOT_USER_ACTION": "ignore",
                                                               cpus={self.RANDDOM_CONTAINER_CPUSER_CPUS}                     
                                                              )""")
            
            logger.info("Start container at workdir: %s", working_dir)
            self.container = self.docker_client.containers.run(image=image_name,
                                                               name=container_name,
                                                               detach=detach,
                                                               stdin_open=stdin_open, # Keep stdin open for interaction
                                                               tty=tty,
                                                               volumes=volumes,
                                                               working_dir=working_dir,
                                                               command=command,  # Start a shell session initially
                                                               remove=remove,
                                                               mem_limit=self.MEM_LIMIT,  # Limit container memory to 10GB
                                                               environment={"PIP_ROOT_USER_ACTION": "ignore",
                                                                             "PYTHON_SAVE_JSON_REPORT": "1",
                                                                             "PYTHONUNBUFFERED": "1"
                                                                           },
                                                               cpuset_cpus=self.RANDDOM_CONTAINER_CPUSER_CPUS
                                                              )
        except APIError as e:
            logger.warning("start_container fail")
            raise DockerStartContainerFailed(f"Failed to start Docker container: {self} {e}")
        except Exception as e:
            logger.critical("Don't forget to add this error to try except")
            logger.critical(e)
            raise e
        return
    
    def delete_image_if_exist(self):
        try:
            # Check if the image exists
            image = self.docker_client.images.get(self.image_name)
            logger.debug(f"Image '{self.image_name}' found. Deleting...")
        
            # Remove the image
            self.docker_client.images.remove(image.id, force=True)
            logger.debug(f"Image '{self.image_name}' deleted successfully.")

        except docker.errors.ImageNotFound:
            # Handle the case where the image does not exist
            logger.info(f"Image '{self.image_name}' does not exist.")

        except docker.errors.APIError as e:
            # Handle any Docker API errors
            logger.critical(f"An error occurred while deleting the image: {e}")
            logger.critical(e, exc_info=True)
            raise e

    def stop_container(self, timeout = 0):
        logger.debug("Stopping container")
        logger.debug(self.container.status)
        try:
            # if self.container.status != "running":
            logger.debug(f"Trying to stop container: {self.container.name} (waiting {timeout} before force stop)")
            self.container.stop(timeout = timeout)
            logger.debug(f"Container stopped: {self.container.name}")
        except NotFound as e:
            logger.info("Container not found %s"%(self.container.name))
            logger.critical(e, exc_info=True)
    
    def _convert_std_from_bytes_to_str(self):
        for key in ['stdout', 'stderr', 'std']:
            if hasattr(self, key):
                if isinstance(getattr(self, key), bytes):
                    s = self._bytes_to_string(getattr(self, key))
                    setattr(self, key, s)
    
    @classmethod
    def _bytes_to_string(cls, b):
        try:
            return b.decode()
        except UnicodeDecodeError:
            return str(b)
        except Exception as e:
            #ToDo change this, when Exception type will be more precise
            raise e
    
    def timeout_exec_run(self, command, timeout):
        """
        Execute a command inside a Docker container with a timeout.
        """
        def _run_command():
            logger.debug(f"Executing command in Docker container: {command}")
            
            _, self.last_stream = self.container.exec_run(command, 
                                                        stream=True, 
                                                        tty=False, 
                                                        stdout=True, 
                                                        stderr=True, 
                                                        demux=True)
            self.return_code = 0
            self.stdout = b''
            self.stderr = b''
            self.std = b''

            for stdout, stderr in self.last_stream:
                if stdout:
                    logger.debug(self._bytes_to_string(stdout))
                    self.stdout += stdout
                    self.std += stdout
                if stderr:
                    logger.warning(self._bytes_to_string(stderr))
                    self.return_code = 1
                    self.stderr += stderr
                    self.std += stderr
            return

        logger.info(f"timeout seconds={timeout}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_command)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError as e:
                self._FALL_WITH_TIMEOUT_EXCEPTION = True
                logger.error(f"Command execution timed out after {timeout} seconds.")
                if hasattr(self, "stop_container"):
                    self.stop_container()
                raise TimeOutException(f"Command execution(docker) timed out after {timeout} seconds.") from e


    # @timeout_decorator()
    # def timeout_exec_run_old(self, command):
    #     """
    #     Execute a command inside a Docker container.
    #     """
    #     logger.debug(f"Executing command in Docker container: {command}")
        
    #     _, self.last_stream = self.container.exec_run(command, 
    #                                                   stream = True, 
    #                                                   tty=False, 
    #                                                   stdout=True, 
    #                                                   stderr=True, 
    #                                                   demux=True
    #                                                  )
    #     self.return_code = 0
    #     self.stdout = b''
    #     self.stderr = b''
    #     self.std = b''

        
    #     for stdout, stderr in self.last_stream:
    #         if stdout:
    #             logger.debug(self._bytes_to_string(stdout))
    #             self.stdout += stdout
    #             self.std += stdout
    #         if stderr:
    #             logger.warning(self._bytes_to_string(stderr))
    #             #ToDo: check that this return_code works
    #             self.return_code = 1
    #             self.stderr += stderr
    #             self.std += stderr
    #     return
    
    
    
    def create_volume(self, volume_name):
        try:
            volume = self.docker_client.volumes.get(volume_name)
            logger.debug(f"Volume '{volume_name}' exists.")
        except docker.errors.NotFound:
            logger.info(f"Volume '{volume_name}' does not exist.")
            volume = self.docker_client.volumes.create(name=volume_name)
            logger.info(f"Volume created: {volume.name}")

    def delete_volume(self, volume_name):
        try:
            volume = self.docker_client.volumes.get(volume_name)
            volume.remove()
            logger.info("Volume volume_name deleted.")
        except docker.errors.NotFound:
            logger.warning("Volume volume_name not found.")

    # def stop_container(self, timeout=0):
    #     try:
    #         if self.container.status != "running":
    #             self.container.stop(timeout = timeout)
    #     except docker.errors.NotFound:
    #         logger.warning(f"{self.container} not found.")
    
    def clean(self):
        try:
            super().clean()
        except GitCommandError:
            logger.error("Fail to clean, using alpine/git to clean it")
            # In case of permission errors, try to clean the repository using a Docker container
            # Execute the Docker command to fix the "dubious ownership" issue and clean the repository
            # docker run --entrypoint sh -v $(pwd):/git --rm alpine/git -c "git config --global --add safe.directory /git && git clean -fd"
            self.docker_client.containers.run(
                "alpine/git", # Image
                "-c 'git config --global --add safe.directory /git && git clean -fd'", # Command to execute
                entrypoint='sh',
                name=f"{DOCKER_CONTAINER_PREFIX}-alpine-git-{self.run_id}",
                volumes={f"{self.cache_folder}": {'bind': '/git', 'mode': 'rw'}}, # Bind mount current directory to /git inside container
                remove=True  # Automatically remove container after it finishes
            )
    
    def hard_clean(self):
        #ToDo: check that this work
        try:
            super().clean()
        except GitCommandError:
            logger.error("Fail to clean, using alpine/git to clean it")
            self.docker_client.containers.run(
                "alpine/git", # Image
                "-c 'git config --global --add safe.directory /git && git clean --hard && git clean -fdx'", # Command to execute
                entrypoint='sh',
                name=f"{DOCKER_CONTAINER_PREFIX}-alpine-git-{self.run_id}",
                volumes={f"{self.cache_folder}": {'bind': '/git', 'mode': 'rw'}}, # Bind mount current directory to /git inside container
                remove=True  # Automatically remove container after it finishes
            )
    
    def save_artifacts(self):
        pass

    def push_image(self, target_tag='latest'):
        # Tag the image
        try:
            source_image = self.default_image_name
            image = self.docker_client.images.get(source_image)
            target_repo = os.path.join(DOCKER_REGISTRY_URI, self.instance_id)
            target_image = f'{target_repo}:{target_tag}'
            image.tag(target_repo, tag=target_tag)
            logger.info(f"Successfully tagged {source_image} as {target_image}")
        except docker.errors.ImageNotFound as e:
            logger.critical(f"Source image {source_image} not found")
            raise e
        except docker.errors.APIError as e:
            logger.critical(f"Error tagging image: {e}")
            raise e
        
        try:
            push_logs = self.docker_client.images.push(
                repository=target_repo,
                tag=target_tag,
                stream=True,
                decode=True
            )
            
            # Print push progress
            for log in push_logs:
                if 'status' in log:
                    logger.info(log['status'])
                if 'error' in log:
                    logger.info(f"Error: {log['error']}")
                    break
                    
            logger.info(f"Successfully pushed {target_image}")
        except docker.errors.APIError as e:
            logger.info(f"Error pushing image: {e}")

    def pull_image(self):
        raise NotImplementedError()

    @abstractmethod
    def build_env(self, command):
        pass
    
    @abstractmethod
    def run_test(self, command):
        pass

    def __del__(self):
        """
        Cleanup the repository cache using an Alpine container.
        """
        logger.debug("docker.base.__del__")
        try:
            logger.debug("Deleting the run folder %s", self.cache_folder)
            super().__del__()
            return
        except Exception as e:
            logger.warning(f"Parent cleanup failed: {e}")
        try:
            logger.debug("Deleting the run folder (using alpine) %s", self.cache_folder)
            client = docker.from_env()
            command = f"rm -rf {self.cache_folder}"

            logger.debug(f"Starting Alpine container to delete: {self.cache_folder}")

            client.containers.run(
                image="alpine",
                command=command,
                name=f"{DOCKER_CONTAINER_PREFIX}-alpine-del-{self.run_id}",
                remove=True,  # Automatically remove the container after execution
                volumes={self.cache_folder: {'bind': self.cache_folder, 'mode': 'rw'}},
            )

            logger.debug(f"Successfully removed repository cache folder: {self.cache_folder}")
        except Exception as e:
            logger.error(f"Failed to clean up with Alpine container: {e}")

    def clean_dirs(self, dir_paths: List[str]) -> bool:
        """
        Cleanup some dir with all subdirs and files using an Alpine container.
        """
        try:
            client = docker.from_env()

            cmds = []
            for path in dir_paths:
                assert os.path.isabs(path)
                assert path.startswith(self.cache_folder)
                cmd = f"rm -rf {path}"
                cmds.append(cmd)

            command = " & ".join(cmds)
            
            paths_txt = ", ".join(dir_paths)
            logger.debug(f"Starting Alpine container to delete: {paths_txt}")

            client.containers.run(
                image="alpine",
                command=command,
                name=f"{DOCKER_CONTAINER_PREFIX}-alpine-clean_dirs-{self.run_id}",
                remove=True,  # Automatically remove the container after execution
                volumes={self.cache_folder: {'bind': self.cache_folder, 'mode': 'rw'}},
            )
            logger.debug(f"Successfully removed dirs: {paths_txt}")
            return True
        except Exception as e:
            logger.error(f"Failed to clean up with Alpine container: {e}")
            return False
import os
import shutil
import docker
from repotest.constants import REPOTEST_MAIN_FOLDER, DOCKER_IMAGE_PREFIX, DOCKER_CONTAINER_PREFIX

def _safe_rmtree(folder):
    try:
        shutil.rmtree(folder)
    except PermissionError:
        raise PermissionError(f"Use `rm -rf {folder}` as a user with sufficient permissions.")
    except FileNotFoundError as e:
        raise e

def clean_runs():
    """Clean the 'runs' folder inside REPOTEST_MAIN_FOLDER."""
    print("clean runs")
    runs_path = os.path.join(REPOTEST_MAIN_FOLDER, "runs")
    _safe_rmtree(runs_path)

def clean_repos():
    """Clean the 'repos' folder inside REPOTEST_MAIN_FOLDER."""
    print("clean repos")
    repos_path = os.path.join(REPOTEST_MAIN_FOLDER, "repos")
    _safe_rmtree(repos_path)

def clean_conda_env():
    """Alias to clean 'repos' as a placeholder for conda env cleanup."""
    print("clean conda env")
    repos_path = os.path.join(REPOTEST_MAIN_FOLDER, "envs")
    _safe_rmtree(repos_path)

def clean_logs():
    """Clean the 'logs' folder inside REPOTEST_MAIN_FOLDER."""
    print("clean logs")
    repos_path = os.path.join(REPOTEST_MAIN_FOLDER, "logs")
    _safe_rmtree(repos_path)


def stop_all_containers():
    """Stop all Docker containers with names starting with DOCKER_CONTAINER_PREFIX."""
    print("stop all containers")
    client = docker.from_env()
    for container in client.containers.list(all=True):
        if container.name.startswith(DOCKER_CONTAINER_PREFIX):
            container.stop(timeout=0) 

def remove_all_containers():
    """Remove all Docker containers with names starting with DOCKER_CONTAINER_PREFIX."""
    print("delete all containers")
    client = docker.from_env()
    for container in client.containers.list(all=True):
        if container.name.startswith(DOCKER_CONTAINER_PREFIX):
            try:
                container.remove(force=True)
            except Exception as e:
                print(f"Failed to remove {container.name}: {e}")

def remove_all_images():
    """Remove all Docker images with names starting with DOCKER_IMAGE_PREFIX."""
    print("delete docker images")
    client = docker.from_env()
    for image in client.images.list():
        for tag in image.tags:
            if tag.startswith(DOCKER_IMAGE_PREFIX):
                try:
                    client.images.remove(image.id, force=True)
                except Exception as e:
                    print(f"Failed to remove image {tag}: {e}")

def clean_docker_volumes(volume_list = ['maven-cache']):
    """Clean specific Docker volumes."""
    print("clean docker volumes")
    client = docker.from_env()
    for volume in client.volumes.list():
        if volume.name in volume_list:
            try:
                volume.remove(force=True)
            except Exception as e:
                print(f"Failed to remove volume {volume.name}: {e}")

def clean_all():
    """Completely clean all repotest-generated data and resources.
    
    This performs a full cleanup of all temporary and persistent artifacts created
    during testing, including test runs, repositories, conda environments,
    log files, and Docker containers/images/volumes.

    Notes
    -----
    The cleanup is performed in the following order:
    1. Log files
    2. Test runs
    3. Repository clones
    4. Conda environments
    5. Docker containers (stopped then removed)
    6. Docker images
    7. Docker volumes
    """
    print("cleaning repotest...")
    for step in [clean_runs, clean_repos, clean_conda_env, clean_logs, stop_all_containers, remove_all_containers, remove_all_images, clean_docker_volumes]:
        try:
            step()
        except Exception as e:
            print(e)
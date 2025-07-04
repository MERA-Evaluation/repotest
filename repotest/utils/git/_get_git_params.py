import os
import subprocess
from tqdm import tqdm
# ToDo: read this from consts
# Define the cache folder path
from repotest.constants import DEFAULT_CACHE_FOLDER


def get_git_commit_hash(folder):
    """
    Retrieve the commit hash of the current HEAD for a Git repository.

    Parameters
    ----------
    folder : str
        Path to the folder containing the Git repository.

    Returns
    -------
    str
        The commit hash of the current HEAD.

    Raises
    ------
    subprocess.CalledProcessError
        If the command fails (e.g., the folder is not a Git repository).
    """
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=folder,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True
    )
    return result.stdout.strip()

def get_commit_url(folder):
    """
    Retrieve the remote URL of the Git repository.

    Parameters
    ----------
    folder : str
        Path to the folder containing the Git repository.

    Returns
    -------
    str
        The URL of the remote origin.

    Raises
    ------
    subprocess.CalledProcessError
        If the command fails (e.g., no remote URL is configured).
    """
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=folder,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True
    )
    return result.stdout.strip()

def detect_java_test_command(folder):
    """
    Detect the command to run Java tests based on the presence of specific files.

    Parameters
    ----------
    folder : str
        Path to the folder to detect the test command.

    Returns
    -------
    str
        The test command to execute.

    Raises
    ------
    ValueError
        If no recognizable test setup is found.
    """
    if os.path.exists(os.path.join(folder, "pom.xml")):
        return "mvn test"
    elif os.path.exists(os.path.join(folder, "java/pom.xml")):
        return "cd java; mvn test"
    else:
        raise ValueError("No 'pom.xml' file found to determine the test command.")

def java_parse_repo_metadata(repo_path, repo_name):
    """
    Parse metadata for a given Java repository.

    Parameters
    ----------
    repo_path : str
        Full path to the repository.
    repo_name : str
        The name of the repository.

    Returns
    -------
    dict
        A dictionary containing the repository metadata:
        - instance_id: A unique identifier for the instance.
        - repo_name: The name of the repository.
        - commit_hash: The current HEAD commit hash.
        - command: The command to run Java tests.
        - url: The remote URL of the repository.

    Raises
    ------
    ValueError
        If test command detection fails.
    """
    commit_hash = get_git_commit_hash(repo_path)
    commit_url = get_commit_url(repo_path)
    instance_id = repo_name.replace('/', '-')
    command = detect_java_test_command(repo_path)
    
    return {
        "instance_id": instance_id,
        "repo_name": repo_name,
        "commit_hash": commit_hash,
        "command": command,
        "_url": commit_url
    }

# Example of ussage
# List of repository names (should be defined or passed as input)
# from datasets import Dataset

# list_repo_name = ['balp/Lift-Kata', 'quiram/course-stream-collectors']
# data = []
# for repo_name in list_repo_name:
#     repo_path = os.path.join(DEFAULT_CACHE_FOLDER, repo_name)
#     data.append(java_parse_repo_metadata(repo_path))


# dataset = Dataset.from_list(data)
# dataset.to_json("/Users/22530318/Documents/git/java-utils/datasets/data_java_utils.jsonl")
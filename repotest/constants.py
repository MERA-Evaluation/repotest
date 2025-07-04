import os
from pathlib import Path
from dotenv import load_dotenv
import logging

# --- Load constants.env ---
ENV_PATH = Path(__file__).parent / "constants.env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    raise FileNotFoundError(ENV_PATH)

def enable_stdout_logs():
    logger = logging.getLogger("repotest")
    if logger.handlers:
        logger.handlers[0].setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.DEBUG)

def disable_stdout_logs():
    logger = logging.getLogger("repotest")
    if logger.handlers:
        logger.handlers[0].setLevel(logging.CRITICAL)
    else:
        logger.setLevel(logging.CRITICAL)

def permanently_change_consts(name: str, value: str):
    """Update an existing key in constants.env and reload constants."""
    if not ENV_PATH.exists():
        raise FileNotFoundError(f"{ENV_PATH} not found.")

    # Read current .env
    with open(ENV_PATH, "r") as f:
        lines = f.readlines()

    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{name}="):
            found = True
            lines[i] = f"{name}={value}\n"
            break

    if not found:
        raise ValueError(f"❌ '{name}' is not defined in {ENV_PATH}")

    # Write updated lines
    with open(ENV_PATH, "w") as f:
        f.writelines(lines)

    # Reload the updated env values
    load_dotenv(dotenv_path=ENV_PATH, override=True)

    # Optional: re-evaluate global constants if needed
    globals()[name] = os.environ[name]
    if name.endswith('_INT'):
        globals()[name] = int(globals()[name])
    
    print(f"✅ Updated {name} to {value}")


# --- From env ---
#ToDo: disable double REPOTEST_CACHE_FOLDER and DEFAULTT_CACHE_FOLDER
DEFAULT_CACHE_FOLDER = os.path.expanduser(os.environ["REPOTEST_CACHE_FOLDER"])
print(f"DEFAULT_CACHE_FOLDER={DEFAULT_CACHE_FOLDER}")
#ToDo: use this folder instead of REPOTEST_CACHE_FOLDER
REPOTEST_MAIN_FOLDER = os.path.expanduser(os.environ["REPOTEST_MAIN_FOLDER"])
REPOTEST_CACHE_FOLDER = os.environ["REPOTEST_CACHE_FOLDER"]
CONDA_ENV_NAME = os.environ["CONDA_ENV_NAME"]
DOCKER_IMAGE_PREFIX = os.environ["DOCKER_IMAGE_PREFIX"]
DOCKER_CONTAINER_PREFIX = os.environ["DOCKER_CONTAINER_PREFIX"]
DOCKER_PYTHON_DEFAULT_IMAGE = os.environ["DOCKER_PYTHON_DEFAULT_IMAGE"]
DOCKER_JAVA_DEFAULT_IMAGE = os.environ["DOCKER_JAVA_DEFAULT_IMAGE"]
DEFAULT_CONTAINER_MEM_LIMIT = os.environ["DEFAULT_CONTAINER_MEM_LIMIT"]
DEFAULT_EVAL_TIMEOUT_INT = int(os.environ["DEFAULT_EVAL_TIMEOUT_INT"])
DEFAULT_BUILD_TIMEOUT_INT = int(os.environ["DEFAULT_BUILD_TIMEOUT_INT"])
DEFAULT_COMMIT_TIMEOUT_INT = int(os.environ["DEFAULT_COMMIT_TIMEOUT_INT"])
# DEFAULT_CONTAINER_CPUSET_CPUS = str(os.environ['DEFAULT_CONTAINER_CPUSET_CPUS'])
OPTIMAL_CPU_NUM = max(int(os.cpu_count() * 0.5), 1)
# Where we push/pull docker images
DOCKER_REGISTRY_URI = os.environ.get("DOCKER_REGISTRY_URI", "")

#Where we save s3 artifacts
S3_BUCKET = os.environ.get("S3_BUCKET", "")

# --- Logging levels ---
LOG_LEVEL_FILE = logging.DEBUG
LOG_LEVEL_CONSOLE = logging.CRITICAL
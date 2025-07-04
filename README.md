# repotest


A library for automating test execution and repository operations.

It simplifies working with Docker and local repositories and provides utilities for managing patches and tests.

Originally built to facilitate LLM generation testing at the repository level, aimed at easing workflows for data scientists.

---

# Installation

If you're running on an ECS GigaCode worker, please run:

```bash
ln -s /data/adam/.cache/repotest ~/.cache/repotest
```

This is necessary due to limited disk space.

1. Install the latest version using pip:

```bash
pip install dist/$(ls dist/repotest-*.whl | sort -V | tail -n 1)
```

This command installs the latest available version of the package.
It's equivalent to `pip install dist/repotest-0.2.6-py3-none-any.whl`, but always picks the latest version.

2. To run the project in debug mode, add the current folder to the Python path:

```python
import sys
sys.path.append("/path/to/repotest")
```

3. Check which modes work on your current machine:

```python
from repotest.scripts import check_perfomance
```

---

# Design

The following diagram shows the architecture of the project and how different components interact:

---

# How to Clean All Caches

```python
from repotest.utils.clean import remove_all_containers, remove_all_images, clean_all, ...
```

---

# Example Usage

The project supports two execution modes: Docker-based and local.

**Using Docker:**

```python
from repotest.core.docker.java import JavaDockerRepo 

repo = JavaDockerRepo(
    repo="Osiris-Team/SPPU",
    base_commit="1a86a84e3c2dd7446b4778db8bb5dbaf44944f1c",
    image_name="maven:3.9.9-eclipse-temurin-23-alpine"
)

repo.clean()  # Reset the repo folder to the base commit state
# repo.build_env("", timeout=60*5)  # Set up the environment
# repo.apply_patch(patch)  # Apply a patch to the repo
repo.run_test("mvn test", timeout=60*5)  # Run tests with a 5-min timeout
```

**Using Local Filesystem:**

```python
from repotest.core.local.java import JavaLocalRepo

repo = JavaLocalRepo(
    repo="Osiris-Team/SPPU",
    base_commit="1a86a84e3c2dd7446b4778db8bb5dbaf44944f1c",
)

repo.clean()  # Reset the repo folder to the base commit state
# repo.build_env("", timeout=60*5)
# repo.apply_patch(patch)
repo.run_test("mvn test", timeout=60*5)
```

The interface for `*Repo` classes is the same across modes.

The only difference is that `JavaDockerRepo` allows specifying an image and cache volumes.
By default, Maven cache is stored in a Docker volume.

---

# Creating Git Patches for Java Projects

The following code generates a git patch from changes in the repository:

```python
from repotest.utils.git.git_diff_wrapper import GitDiffWrapper

changer = GitDiffWrapper(
    repo=task['repo_name'], 
    base_commit=task['base_commit']
)

changer.change_test(
    fn_test=task['test_file'], 
    str_test=task['output'], 
    str_source=task['source_code']
)

changer.fix_pom_file()
patch = changer.git_diff()
```

---

## Logs

All logs are saved to: `repotest/logs/%Y-%m-%d.log`
Only `critical` logs are printed to stdout by default.

To increase verbosity and print logs to stdout:

```python
from repotest.logger import change_console_logger_level
from logging import DEBUG

change_console_logger_level(DEBUG)
```

---

# Build the Package from Source

To build the package from source:

```bash
python -m build
```

---

# Run Tests

Tests follow the same file structure as the main library.
To run them (takes \~1–2 minutes):

```bash
pytest tests
```

---

# Dataset Overview

All datasets used for testing the library are stored in `../datasets/*.json`.
Example of how to load one:

```python
from datasets import load_dataset
ds = load_dataset('json', data_files="../datasets/java_from_1_2k_from_parser.jsonl")
```

---

# Enable/Disable Stdout Logs

By default, logs are stored in `~/.cache/repotest/logs/{date}.log`.

To toggle stdout logging:

```python
from repotest.constants import enable_stdout_logs, disable_stdout_logs

enable_stdout_logs()
disable_stdout_logs()
```

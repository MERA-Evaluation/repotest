# repotest

A library for automating test execution and repository operations for training and evaluating code LLMs.

This repository provides a complete pipeline for building evaluation datasets for code LLMs by collecting real repositories, extracting test patches, and validating model-generated code against real tests. It supports Docker-based isolated execution for 10+ programming languages with different build systems.

---

## Pipeline Overview

The repotest framework implements a complete pipeline for training and evaluating code LLMs:

1. **Repository Collection** - Search and collect repositories from GitHub with specific criteria
2. **Issue-PR Mapping** - Map issues to pull requests that resolve them
3. **Metadata Extraction** - Extract repository metadata and filter by quality criteria
4. **Patch Extraction** - Extract git diffs and separate test/non-test changes
5. **Repository Building** - Build repository environments with proper dependencies
6. **End-to-End Execution** - Validate patches in isolated environments

---

## Supported Languages

The framework supports Docker-based execution for 10+ programming languages with their respective build systems:

| Language | Build System | Docker Image | Test Framework |
|----------|--------------|--------------|----------------|
| Python | pip, setup.py | python:3.11-slim | pytest |
| Java | Maven, Gradle | maven:3.9.9-eclipse-temurin-23-alpine | JUnit/Maven |
| JavaScript | npm, yarn | node:22 | Jest/Mocha |
| TypeScript | npm, yarn | node:22 | Jest/Mocha |
| Go | go mod | golang:1.22 | go test |
| C++ | CMake, Make | gcc:11 | CTest |
| Ruby | Bundler | ruby:3.1 | Minitest/RSpec |
| PHP | Composer | php:8.2-cli | PHPUnit |
| Rust | Cargo | rust:1.70 | cargo test |
| Kotlin | Gradle | gradle:8.0-jdk17 | JUnit |
| Scala | SBT | sbtscala/scala-sbt | ScalaTest |

Each language implements specific build and test execution logic while maintaining a consistent interface.

---

## Installation

1. Install the latest version using pip:

```bash
pip install repositorytest
```

2. Install Docker for containerized execution (recommended)

3. Set up required environment variables in `repotest/constants.env`:

```bash
REPOTEST_MAIN_FOLDER=~/.cache/repotest
REPOTEST_CACHE_FOLDER=~/.cache/repotest/repos
DOCKER_PYTHON_DEFAULT_IMAGE=python:3.11.11-slim-bookworm
DOCKER_JAVA_DEFAULT_IMAGE=openjdk:17-slim
DEFAULT_EVAL_TIMEOUT_INT=80
DEFAULT_BUILD_TIMEOUT_INT=320
DEFAULT_CONTAINER_MEM_LIMIT='10g'
```

---

## Pipeline Components

### 1. Repository Collection (`collect/`)

Collect repositories from GitHub with specific criteria:

```bash
python collect/step1_collect_repos.py \
  --output_file data/python_repos.jsonl \
  --language python \
  --start_date 2020-01-01 \
  --end_date 2024-12-31 \
  --stars_min 100 \
  --license_list "mit,apache-2.0,bsd-3-clause"
```

### 2. Issue-PR Mapping

Map issues to pull requests that resolve them:

```bash
python collect/step2_pr_issue_mapping.py \
  --input_file data/python_repos.jsonl \
  --output_file data/python_repos_mapped.jsonl
```

### 3. Metadata Extraction

Extract and filter repository metadata:

```bash
python collect/step3_metadata_extraction_and_filtering.py \
  --input_file data/python_repos_mapped.jsonl \
  --output_file data/python_filtered.jsonl
```

### 4. Patch Extraction

Extract git diffs and separate test/non-test changes:

```bash
python collect/step4_extract_patches.py \
  --input_file data/python_filtered.jsonl \
  --output_file data/python_patches.jsonl
```

### 5. Repository Building

The framework automatically builds repository environments with proper dependencies when needed.

### 6. End-to-End Execution

Validate patches in isolated Docker environments:

```python
from repotest.manager.liveswebench_task_manager import LiveSWEBenchTaskManager

# Load tasks
import pandas as pd
task_list = list(pd.read_json("data/python_patches.jsonl", lines=True).T.to_dict().values())

# Evaluate with Docker
manager = LiveSWEBenchTaskManager(
    mode="docker",
    n_jobs=4,  # Parallel execution
    column_patch="patch_model"  # Column containing model-generated patch
)

manager.inplace_build_and_eval(task_list)

# Save results
import json
with open("results.jsonl", "w") as f:
    for task in task_list:
        f.write(json.dumps(task) + "\n")
```

---

## CLI Usage

Run evaluations directly from the command line:

```bash
python -m repotest.cli.liveswebench \
  --fn_input data/tasks.jsonl \
  --fn_output results.jsonl \
  --column_patch patch_model \
  --mode docker \
  --n_jobs 4
```

---

## Core Repository Classes

The framework provides consistent interfaces for different execution modes and languages:

### Docker-based Execution (Recommended)

```python
from repotest.core.docker.python import PythonDockerRepo

repo = PythonDockerRepo(
    repo="someuser/somerepo",
    base_commit="abc123def456",
    image_name="python:3.11-slim"
)

# Build environment
repo.build_env("pip install -e .; pip install pytest pytest-json-report")

# Apply patch and run tests
repo.clean()
repo.apply_patch(patch_content)
result = repo.run_test("pytest --json-report --json-report-file=report.json")
```

### Local Execution

```python
from repotest.core.local.python import PythonLocalRepo

repo = PythonLocalRepo(
    repo="someuser/somerepo",
    base_commit="abc123def456"
)

repo.clean()
repo.apply_patch(patch_content)
result = repo.run_test("pytest")
```

---

## Cache Management

The framework uses intelligent caching to speed up repeated evaluations:

```python
from repotest.utils.clean import remove_all_containers, remove_all_images, clean_all

# Clean Docker resources
remove_all_containers()
remove_all_images()

# Clean repository cache
clean_all()
```

---

## Build the Package from Source

To build the package from source:

```bash
python -m build
```

---

## Run Tests

Integration tests validate the complete pipeline:

```bash
# Run light integration test
pytest tests/integration/test_realcode_evaluation.py::test_realcode_evaluation_light -v

# Run all integration tests
pytest tests/integration/ -v
```

---

## Dataset Format

Tasks are stored in JSONL format with the following structure:

```json
{
  "instance_id": "unique_task_id",
  "repo": "owner/repo_name",
  "base_commit": "commit_hash",
  "test_patch": "git_diff_for_test_files",
  "patch": "git_diff_for_source_files",
  "PASS_TO_PASS": ["test_name_1", "test_name_2"],
  "FAIL_TO_PASS": ["test_name_3"],
  "command_test_small": "pytest test_file.py",
  "image_name": "python:3.11-slim",
  "timeout_build": 300,
  "timeout_test": 60
}
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

## TODO: Major Improvements

Top 10 improvements to simplify code, enhance OOP design, and fix naming inconsistencies:

1. **Fix naming inconsistencies across classes and files**
   - `LiveSWEBenchTaskManager` class name vs "RealCode" references in documentation
   - `REQUIRED_COLUMND` typo in task manager (should be `REQUIRED_COLUMNS`)
   - Inconsistent parameter names: `image_name_from` in `__call__` method vs `image_name` in constructor
   - Misleading class docstrings (e.g., JavaScriptDockerRepo documented as "Python repositories")

2. **Improve OOP design and abstraction**
   - Remove `__call__` method from PythonDockerRepo with "ToDo: remove this is not good abstraction" comment
   - Consolidate duplicate code in `_setup_container_volumes` method across language implementations
   - Create a unified interface for test result parsing instead of language-specific implementations
   - Extract common timeout handling logic into a reusable component

3. **Refactor cache management**
   - Standardize cache directory handling across all language implementations
   - Simplify volume management with a consistent approach
   - Remove redundant cache checking methods (`_image_exists`, `was_build`)

4. **Clean up language-specific implementations**
   - Fix JavaScriptDockerRepo inheriting from Python-specific base class names
   - Standardize constructor parameters across all language implementations
   - Remove language-specific hacks and create proper abstractions

5. **Simplify patch application and test execution**
   - Unify patch application logic across all repository classes
   - Standardize test command execution and result parsing
   - Remove duplicate code for handling test reports

6. **Improve error handling and logging**
   - Replace print statements with proper logging throughout the codebase
   - Standardize exception handling across all components
   - Remove critical log messages that should be exceptions

7. **Refactor repository cleaning methods**
   - Consolidate `clean()`, `hard_clean()`, and `clean_dirs()` methods
   - Remove duplicate cleanup logic using Alpine containers
   - Standardize repository reset behavior

8. **Optimize parallel execution**
   - Improve ThreadPoolExecutor usage in task managers
   - Simplify job scheduling and result collection
   - Remove redundant timeout scaling logic

9. **Fix file and directory structure**
   - Rename `collect/step4_extract_patches.py` filename which doesn't match its docstring ("pipeline/steps/step4_patch_extraction.py")
   - Organize parser classes into consistent directory structure
   - Remove commented-out code and TODO comments that have been there for a long time

10. **Simplify configuration management**
    - Consolidate environment variable handling
    - Remove duplicate constant definitions
    - Standardize timeout and memory limit configurations

---

## Test Summary

Summary of all tests in the repository with estimated latency scores:

| Filename | Num Tests | Latency Score (0-10) | Description |
|---------|-----------|---------------------|-------------|
| tests/core/test_greedy.py | 4 | 2 | Basic repository functionality tests |
| tests/core/test_timeout.py | 4 | 2 | Timeout handling tests |
| tests/core/test_realcode_python_task_manager.py | 2 | 3 | Task manager functionality tests |
| tests/core/docker/test_python_docker_repo.py | 1 | 3 | Python Docker repository tests |
| tests/core/docker/test_java_docker_repo.py | 1 | 3 | Java Docker repository tests |
| tests/core/docker/test_javascript_docker_repo.py | 1 | 3 | JavaScript Docker repository tests |
| tests/core/docker/test_typescript_docker_repo.py | 1 | 3 | TypeScript Docker repository tests |
| tests/core/docker/test_golang_docker_repo.py | 1 | 3 | Go Docker repository tests |
| tests/core/docker/test_rust_docker_repo.py | 1 | 3 | Rust Docker repository tests |
| tests/core/docker/test_cpp_docker_repo.py | 1 | 3 | C++ Docker repository tests |
| tests/core/docker/test_scala_docker_repo.py | 1 | 3 | Scala Docker repository tests |
| tests/core/docker/test_kotlin_docker_repo.py | 1 | 3 | Kotlin Docker repository tests |
| tests/core/docker/test_php_docker_repo.py | 1 | 3 | PHP Docker repository tests |
| tests/core/docker/test_ruby_docker_repo.py | 1 | 3 | Ruby Docker repository tests |
| tests/core/local/test_java_local_repo.py | 1 | 2 | Java local repository tests |
| tests/integration/test_realcode_evaluation.py | 3 | 8 | RealCode evaluation integration tests |
| tests/integration/test_java_testgen_evaluation.py | 2 | 8 | Java test generation integration tests |
| tests/integration/test_metrics_validation.py | 15 | 1 | Metrics processing unit tests |
| tests/integration/test_java_testgen_validation.py | 7 | 1 | Java testgen validation unit tests |
| tests/integration/test_task_manager_java_testgen.py | 3 | 5 | Task manager Java testgen tests |

---

## TODO Tests

Files that need additional test coverage:

| File to Cover | Number of Necessary Tests | Description |
|---------------|---------------------------|-------------|
| repotest/core/docker/base.py | 5 | Base Docker repository class with complex container management |
| repotest/core/docker/javascript.py | 3 | JavaScript-specific Docker implementation needs more test cases |
| repotest/core/docker/typescript.py | 3 | TypeScript-specific Docker implementation needs more test cases |
| repotest/core/docker/golang.py | 3 | Go-specific Docker implementation needs more test cases |
| repotest/core/docker/rust.py | 3 | Rust-specific Docker implementation needs more test cases |
| repotest/core/docker/cpp.py | 3 | C++-specific Docker implementation needs more test cases |
| repotest/core/docker/scala.py | 3 | Scala-specific Docker implementation needs more test cases |
| repotest/core/docker/kotlin.py | 3 | Kotlin-specific Docker implementation needs more test cases |
| repotest/core/docker/php.py | 3 | PHP-specific Docker implementation needs more test cases |
| repotest/core/docker/ruby.py | 3 | Ruby-specific Docker implementation needs more test cases |
| repotest/manager/liveswebench_task_manager.py | 5 | Main task manager with complex parallel execution logic |
| repotest/manager/realcode_python_task_manager.py | 4 | RealCode Python task manager with stub generation |
| repotest/manager/java_testgen_task_manager.py | 4 | Java test generation task manager |
| collect/step1_collect_repos.py | 3 | Repository collection with GitHub API integration |
| collect/step2_pr_issue_mapping.py | 3 | PR-issue mapping with GraphQL queries |
| collect/step3_metadata_extraction_and_filtering.py | 3 | Metadata extraction and filtering logic |
| collect/step4_extract_patches.py | 4 | Patch extraction with complex git operations |
| collect/step5_build_repo.py | 3 | Repository building logic |
| collect/step6_e2e_execution.py | 3 | End-to-end execution pipeline |
| repotest/utils/git/git_diff_wrapper.py | 4 | Git diff manipulation utilities |
| repotest/utils/java/pom_file_fixer.py | 2 | Maven POM file fixing utilities |
| repotest/utils/java/java_test_fixer.py | 2 | Java test file fixing utilities |
| repotest/parsers/python/pytest_stdout.py | 3 | Pytest output parsing |
| repotest/parsers/java/maven_stdout.py | 3 | Maven output parsing |
| repotest/parsers/java/surefire_report.py | 3 | Surefire XML report parsing |
| repotest/scripts/build_image.py | 2 | Docker image building script |
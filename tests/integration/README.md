# Integration Tests for RealCode Evaluation

This directory contains integration tests for the `TaskManagerRealcode` evaluation pipeline. These tests validate the complete evaluation workflow from data loading to metrics calculation.

## File Structure

- **`test_realcode_evaluation.py`** - Main integration tests for RealCode evaluation pipeline
- **`test_metrics_validation.py`** - Unit tests for RealCode metrics calculation functions  
- **`test_java_testgen_evaluation.py`** - Integration tests for Java test generation pipeline
- **`test_java_testgen_validation.py`** - Unit tests for Java testgen metrics calculation functions
- **`test_task_manager_java_testgen.py`** - Integration tests for TaskManagerJavaTestGen with parallel execution
- **`conftest.py`** - Pytest configuration and fixtures
- **`run_tests.py`** - Convenient script for running tests with different parameters
- **`README.md`** - This documentation file
- **`data/`** - Test data directory (excluded from git)
  - **`samples_qwen2.5_coder_fixed_code.jsonl`** - Cleaned RealCode test dataset (filtered_resps removed)
  - **`samples_java_testgen.jsonl`** - Cleaned Java testgen dataset (filtered_resps removed)
- **`.gitignore`** - Excludes large data files and outputs from version control
- **`task_list.json`** - Sample task data for testing (legacy)
- **`task_list_old.json`** - Old sample task data (legacy)

## Test Structure

### Available Tests

#### RealCode Evaluation Tests

1. **`test_realcode_evaluation_light()`** - Light integration test
   - Uses first 100 tasks from the dataset
   - Runs in Docker mode with single-threaded execution
   - Suitable for CI/CD and quick validation

2. **`test_realcode_evaluation_full()`** - Full integration test  
   - Uses complete dataset (850 samples)
   - Runs in Docker mode with parallel execution (4 jobs)
   - Takes significant time but provides comprehensive validation

3. **`test_realcode_evaluation_local_mode()`** - Local mode test
   - Uses only 5 tasks for quick validation
   - Runs in local mode without Docker requirements
   - Useful for environments without Docker

#### Java Test Generation Tests

4. **`test_java_testgen_evaluation_light()`** - Light Java testgen test
   - Uses first 10 tasks from the Java testgen dataset
   - Validates pass@1 and compile@1 metrics
   - Runtime: ~2 minutes for 10 samples

5. **`test_java_testgen_evaluation_full()`** - Full Java testgen test
   - Uses complete Java testgen dataset (227 samples)
   - Comprehensive validation of Java test generation pipeline
   - Takes significant time to complete

#### TaskManagerJavaTestGen Tests

6. **`test_task_manager_java_testgen_sequential()`** - Sequential execution test
   - Uses first 5 tasks from the Java testgen dataset
   - Tests TaskManagerJavaTestGen with sequential execution (n_jobs=1)
   - Runtime: ~1 minute, validates basic functionality

7. **`test_task_manager_java_testgen_parallel()`** - Parallel execution test
   - Uses first 8 tasks from the Java testgen dataset
   - Tests TaskManagerJavaTestGen with parallel execution (n_jobs=3)
   - Runtime: ~35 seconds, validates thread-safety and performance

8. **`test_task_manager_comparison_sequential_vs_parallel()`** - Comparison test
   - Runs 6 tasks sequentially then 6 tasks in parallel
   - Validates that sequential and parallel execution produce identical results
   - Runtime: ~1.5 minutes, ensures no race conditions or thread conflicts

## Running Tests

### Prerequisites

1. **Test data file setup**: The test data file needs to be prepared before running tests.
   
   If the file doesn't exist, copy and clean the original data:
   ```bash
   cd tests/integration
   mkdir -p data
   python3 -c "
   import json
   import pandas as pd
   
   # Copy and clean the original file (adjust path as needed)
   df = pd.read_json('/data/zpasha/projects/MERA_CODE/utils/samples_qwen2.5_coder_fixed_code.jsonl', lines=True)
   if 'filtered_resps' in df.columns:
       df = df.drop('filtered_resps', axis=1)
   df.to_json('data/samples_qwen2.5_coder_fixed_code.jsonl', orient='records', lines=True)
   print('Test data file prepared successfully')
   "
   ```

2. For Docker tests, ensure Docker is running and accessible

3. Install required dependencies:
   ```bash
   pip install pytest pandas tqdm
   ```

### Running Individual Tests

#### RealCode Tests
```bash
# Run light test (recommended for development)
pytest tests/integration/test_realcode_evaluation.py::test_realcode_evaluation_light -v

# Run local mode test (no Docker required)
pytest tests/integration/test_realcode_evaluation.py::test_realcode_evaluation_local_mode -v

# Run full test (warning: takes significant time)
pytest tests/integration/test_realcode_evaluation.py::test_realcode_evaluation_full -v
```

#### Java Test Generation Tests
```bash
# Run Java testgen light test (recommended for development)
pytest tests/integration/test_java_testgen_evaluation.py::test_java_testgen_evaluation_light -v

# Run Java testgen full test (warning: takes significant time)
pytest tests/integration/test_java_testgen_evaluation.py::test_java_testgen_evaluation_full -v
```

#### TaskManagerJavaTestGen Tests
```bash
# Run TaskManager sequential test
pytest tests/integration/test_task_manager_java_testgen.py::test_task_manager_java_testgen_sequential -v

# Run TaskManager parallel test  
pytest tests/integration/test_task_manager_java_testgen.py::test_task_manager_java_testgen_parallel -v

# Run TaskManager sequential vs parallel comparison
pytest tests/integration/test_task_manager_java_testgen.py::test_task_manager_comparison_sequential_vs_parallel -v
```

### Running by Markers

```bash
# Run all integration tests
pytest -m integration tests/integration/ -v

# Skip slow tests (excludes full evaluation)
pytest -m "integration and not slow" tests/integration/ -v

# Run only slow tests
pytest -m "slow" tests/integration/ -v
```

### Running All Integration Tests

```bash
# Run all tests in integration directory
pytest tests/integration/ -v

# Run with output capture disabled to see progress bars
pytest tests/integration/ -v -s
```

### Using the Test Runner Script

For convenience, use the `run_tests.py` script:

```bash
# Quick start - run light test (default)
cd tests/integration
python run_tests.py

# Run specific test types
python run_tests.py --light           # 100 samples
python run_tests.py --local           # 5 samples, no Docker
python run_tests.py --unit            # Unit tests only
python run_tests.py --full            # All samples (takes hours!)

# Run Java testgen tests
python run_tests.py --java-light      # Java testgen light test (10 samples)
python run_tests.py --java-full       # Java testgen full test (227 samples)
python run_tests.py --java-unit       # Java testgen unit tests

# Run TaskManagerJavaTestGen tests
python run_tests.py --task-manager-light        # Sequential + parallel tests
python run_tests.py --task-manager-comparison   # Sequential vs parallel comparison

# Run with verbose output and progress bars
python run_tests.py --light --verbose --no-capture

# Run all tests except slow ones
python run_tests.py --markers "integration and not slow"
```

## Test Outputs

Each test creates an output directory with evaluation results:

### RealCode Test Outputs
- **`task_list.jsonl`** - Complete task results with evaluation outcomes
- **`metrics_summary.csv`** - Aggregated metrics in CSV format

Output directories:
- Light test: `outputs/eval_qwen2.5_coder_light_test/`
- Full test: `outputs/eval_qwen2.5_coder_full_test/`  
- Local test: `outputs/eval_qwen2.5_coder_local_test/`

### Java Test Generation Outputs
- **`java_testgen_results.json`** - Complete task results with pass@1 and compile@1 metrics
- **`java_testgen_metrics.csv`** - Detailed results in CSV format

Output directories:
- Light test: `outputs/eval_java_testgen_light_test/`
- Full test: `outputs/eval_java_testgen_full_test/`

## Metrics Validation

### RealCode Metrics

The RealCode tests validate the following metrics are calculated correctly:

- **`pass@1`** - Success rate for generated code
- **`pass_oracle@1`** - Success rate for ground truth (oracle) code
- **`pass_stub_pass@1`** - Success rate for `pass` stub
- **`pass_stub_empty_str@1`** - Success rate for `return ""` stub
- **`pass_dry_run@1`** - Success rate for dry run tests
- **`execution_success`** - Overall execution success rate
- **`num_samples`** - Number of samples processed

### Java Test Generation Metrics

The Java testgen tests validate the following metrics:

- **`pass@1`** - Success rate for generated Java test code (tests pass)
- **`compile@1`** - Compilation rate for generated Java test code
- **`num_samples`** - Number of samples processed
- **Metric consistency validation** - Ensures computed metrics match original dataset metrics

### Metric Calculation

The `process_results()` function converts internal metric names to standardized format:

```python
column_replace_dict = {
    "pass_gen": "pass@1",
    "pass_gt": "pass_oracle@1", 
    "pass_return_pass": "pass_stub_pass@1",
    "pass_return_empty_str": "pass_stub_empty_str@1",
    "pass_dry_run": "pass_dry_run@1",
    "status": "execution_success"
}
```

## Expected Behavior

### Successful Test Run

1. Tasks are prepared with proper stub code generation
2. Docker/local environments are built successfully
3. Tests are executed for each code variant (gt, gen, stubs)
4. Metrics are calculated and validated
5. Results are saved to output files
6. All assertions pass

### Common Issues

1. **Missing input file** - Test will be skipped with appropriate message
2. **Docker unavailable** - Use local mode tests instead
3. **Build failures** - Check Docker environment and image availability
4. **Timeout issues** - Consider reducing dataset size or increasing timeout values

## Performance Considerations

- **Light test**: ~5-10 minutes (100 tasks)
- **Full test**: 1-3 hours depending on dataset size and parallelization
- **Local test**: ~1-2 minutes (5 tasks)

The tests use `tqdm` progress bars to show evaluation progress when run with `-s` flag.

## Troubleshooting

### Test Skipping
If tests are being skipped, check:
1. Input file path exists and is accessible
2. Required dependencies are installed
3. Docker is running (for Docker mode tests)

### Assertion Failures
Common assertion failures indicate:
1. Metric calculation issues - check `process_results()` function
2. Task preparation problems - verify input data format
3. Evaluation pipeline errors - check `TaskManagerRealcode` logs

### Performance Issues
If tests are running slowly:
1. Use light test for development
2. Increase `n_jobs` parameter for parallel execution
3. Consider reducing dataset size for debugging

## TaskManagerJavaTestGen Overview

The `TaskManagerJavaTestGen` class is a simplified, purpose-built manager for Java test generation evaluation:

### Key Features
- **Simplified Interface**: Only handles evaluation, not building (unlike TaskManagerRealcode)
- **Pre-extracted Code**: Expects `generated_code` field already cleaned and ready to use
- **Thread-Safe**: Uses `cache_mode='volume'` to ensure no file conflicts between parallel threads
- **Parallel Execution**: Supports configurable parallel execution with proper isolation
- **Clean Error Handling**: Uses logger instead of prints, proper exception handling

### Usage Example
```python
from repotest.manager.java_testgen_task_manager import TaskManagerJavaTestGen

# Create manager
manager = TaskManagerJavaTestGen(
    mode='docker',  # or 'local'
    n_jobs=3,       # parallel workers
    timeout=300     # test timeout
)

# Prepare tasks with pre-extracted code
tasks = [
    {
        'doc_id': 'task_1',
        'repo': 'some/repo',
        'base_commit': 'abc123',
        'image_name': 'java_env:latest',
        'test_command': 'mvn test',
        'fn_test': 'src/test/java/TestClass.java',
        'source_code': '...',
        'generated_code': 'public void testMethod() { ... }'  # Pre-extracted!
    }
]

# Run evaluation
manager.eval_task_list(tasks)

# Results stored in-place in tasks
for task in tasks:
    print(f"Task {task['doc_id']}: pass@1={task['pass@1']}, compile@1={task['compile@1']}")
```

### Thread Safety Validation
The tests specifically validate:
1. **No Race Conditions**: Sequential and parallel produce identical results
2. **File Isolation**: Each thread works with isolated cache directories
3. **Metric Consistency**: Results perfectly match original data metrics 
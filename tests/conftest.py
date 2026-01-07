# conftest.py
import pytest
import os
import datetime
import logging
import time
import json

# Logger setup
logger = logging.getLogger("pytest_results")
start_time = time.time()

def pytest_addoption(parser):
    parser.addoption("--slow", action="store_true", default=False, help="Run slow tests")

def pytest_configure(config):
    """Set up single log file per test session"""
    logs_dir = os.path.join("tests", "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_file = os.path.join(logs_dir, datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + ".log")
    config.option.log_file = log_file
    config.option.log_cli_level = config.option.log_cli_level or "INFO"
    config.option.log_file_level = config.option.log_file_level or "INFO"
    
    # Remove any existing handlers to avoid conflicts
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    handler = logging.FileHandler(log_file)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False  # Prevent propagation to root logger

def pytest_runtest_logreport(report):
    """Log test report as JSON"""
    logger.info(f"TEST REPORT: {json.dumps({'nodeid': report.nodeid, 'when': report.when, 'outcome': report.outcome})}")

def pytest_sessionfinish(session, exitstatus):
    """Log session finish with detailed statistics like pytest"""
    duration = time.time() - start_time
    
    # Get statistics from session (using getattr for safety)
    failed = getattr(session, 'testsfailed', 0) or 0
    collected = getattr(session, 'testscollected', 0) or 0
    
    # Simple approach using what we know is available
    stats_str = f"{collected} collected, {failed} failed"
    
    # Format duration simply
    duration_display = f"{duration:.2f}s"
    
    # Log the summary in pytest-like format
    logger.info("=" * 40 + " short test summary info " + "=" * 40)
    # Note: Individual failure details would require more complex implementation
    logger.info("=" * 25 + f" {stats_str} in {duration_display} " + "=" * 26)
    
    # Clean up
    for handler in logger.handlers:
        handler.close()
    logger.handlers.clear()

# conftest.py
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--slow", 
        action="store_true", 
        default=False, 
        help="Run slow tests with all cache modes"
    )

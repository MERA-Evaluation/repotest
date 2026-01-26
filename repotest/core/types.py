from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Dict, Literal


class CacheMode(str, Enum):
    DOWNLOAD = "download"
    SHARED = "shared"
    LOCAL = "local"
    VOLUME = "volume"

class TestsStatus(str, Enum):
    Ok = 'Ok'
    Fail = "Fail"
    Unk = "Unknown"

class _TemperaryDataClassDict(dict):
    """Imitates dataclass dict behaviour as before
    dict is a parent to make json.dumps easy
    """
    # ToDo remove this when debug finish
    def __getitem__(self, key):
        """Allow attribute-style access."""
        if hasattr(self, key):
            return getattr(self, key)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

    def __str__(self):
        return json.dumps(self)
    
    def __post_init__(self):
        """
        Called automatically by the @dataclass decorator after __init__.
        Populates the dict storage so json.dumps can see the fields.
        """
        for field in fields(self):
            value = getattr(self, field.name)
            # Standard JSON encoder doesn't handle Enums; we must extract the value
            if isinstance(value, Enum):
                value = value.value
            self[field.name] = value

@dataclass
class OutputSummary(_TemperaryDataClassDict):
    """Represents a summary of test results."""
    status: TestsStatus
    passed: int
    failed: int
    total: int
    error: int
    collected: int
    _from: Literal['stdout', 'report.json', 'report.yaml']

@dataclass
class OutputRepo(_TemperaryDataClassDict):
    """Represents the output of tests."""
    stdout: str
    stderr: str
    std: str
    returncode: int
    report: Any
    parser: Dict[str, Any]
    summary: OutputSummary
    time: float
    run_id: str

@dataclass
class OutputTests(OutputRepo):
    """Represents the output of tests."""


@dataclass
class OutputBuildEnv(OutputRepo):
    """Represents the output of the build_env method."""
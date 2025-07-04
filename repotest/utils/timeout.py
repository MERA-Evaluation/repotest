import time
import concurrent.futures
from repotest.constants import DEFAULT_EVAL_TIMEOUT_INT

import logging
logger = logging.getLogger("repotest") 

#ToDo: Move this to docker base
# class TimeOutException(Exception):
#     """Custom exception to raise when a function exceeds the timeout."""
#     pass

def timeout_decorator(default_timeout: int = DEFAULT_EVAL_TIMEOUT_INT):
    """Decorator to add timeout functionality to functions."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Get param timeout cls, if it exist, else get default_timeout
            self = args[0] if args else (kwargs['self'] if 'self' in kwargs else None)
            if self:
                timeout = getattr(self, '_TEST_EVAL_TIMEOUT', default_timeout)
            else:
                timeout = default_timeout
            
            logger.info("timeout seconds=%d"%timeout)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    logger.error(f"Function '{func.__name__}' timed out after {timeout} seconds.")
                    if self and hasattr(self, "stop_container"):
                        getattr(self, "stop_container")()
                    raise TimeOutException(f"Function '{func.__name__}' timed out after {timeout} seconds.")
        return wrapper
    return decorator


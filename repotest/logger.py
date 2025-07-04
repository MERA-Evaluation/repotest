import logging
import os
from datetime import datetime
from repotest.constants import LOG_LEVEL_FILE, LOG_LEVEL_CONSOLE, REPOTEST_MAIN_FOLDER

# Determine logger name dynamically from the package path
LOGGER_NAME = __name__.split('.')[0]  # Gets 'repotest'

# Logging directory
LOG_DIR = os.path.join(REPOTEST_MAIN_FOLDER, "logs")
os.makedirs(LOG_DIR, exist_ok=True)  # Ensure the logs directory exists

# Log file path with today's date
log_filename = datetime.now().strftime("%Y-%m-%d.log")
log_filepath = os.path.join(LOG_DIR, log_filename)

# Logging format
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Create logger instance
logger = logging.getLogger(LOGGER_NAME)
logger.setLevel(logging.DEBUG)  # Set the highest level

# Ensure we don't add duplicate handlers
if not logger.hasHandlers():
    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL_CONSOLE)
    console_handler.setFormatter(formatter)

    # File handler
    file_handler = logging.FileHandler(log_filepath, mode="a")
    file_handler.setLevel(LOG_LEVEL_FILE)
    file_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

logger.info("Logger initialized: %s", log_filepath)
logger.info("LOG_LEVEL_FILE=%s"%LOG_LEVEL_FILE)
logger.info("LOG_LEVEL_CONSOLE=%s"%LOG_LEVEL_CONSOLE)
# Function to change console log level
def change_console_logger_level(level: int) -> None:
    """
    Change the logging level for the console handler dynamically at runtime.

    Parameters
    ----------
    level : int
        The new logging level (e.g., logging.DEBUG, logging.INFO).
    """
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setLevel(level)
            logger.info("Console log level changed to: %s", logging.getLevelName(level))
            break

# Function to change file log level
def change_file_logger_level(level: int) -> None:
    """
    Change the logging level for the file handler dynamically at runtime.

    Parameters
    ----------
    level : int
        The new logging level (e.g., logging.DEBUG, logging.INFO).
    """
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            handler.setLevel(level)
            logger.info("File log level changed to: %s", logging.getLevelName(level))
            break
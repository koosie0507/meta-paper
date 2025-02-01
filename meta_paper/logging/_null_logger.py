import logging
from logging import Logger


def null_logger() -> Logger:
    logger = logging.getLogger()
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger

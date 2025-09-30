import time
import logging
from contextlib import contextmanager

log = logging.getLogger(__name__)

@contextmanager
def timed(operation: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        log.info(f"{operation} took {elapsed:.3f}s")
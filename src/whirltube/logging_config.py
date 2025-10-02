import logging
import sys
from .util import xdg_cache_dir


def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))

    # File handler (always at DEBUG level)
    log_file = xdg_cache_dir() / "whirltube.log"
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s:%(lineno)d: %(message)s'
    ))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)

    console.setLevel(level)

    logging.info(f"Logging to {log_file}")
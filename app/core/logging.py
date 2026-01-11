from __future__ import annotations

import logging
import sys


def setup_logging() -> None:
    """Basic structured-ish logging for the demo backend."""
    root = logging.getLogger()
    if root.handlers:
        return  # prevent duplicate handlers (e.g., in reload)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)

    root.setLevel(logging.INFO)
    root.addHandler(handler)

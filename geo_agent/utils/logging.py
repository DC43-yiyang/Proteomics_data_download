import logging
import sys


def setup_logging(verbose: bool = False):
    """Configure structured logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    formatter = logging.Formatter(
        "[%(name)s] %(message)s"
    )
    handler.setFormatter(formatter)

    root = logging.getLogger("geo_agent")
    root.setLevel(level)
    root.addHandler(handler)

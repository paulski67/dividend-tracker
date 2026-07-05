import logging

from pathlib import Path

from logging.handlers import (
    TimedRotatingFileHandler
)


def setup_logger(
    backup_count=60
):

    Path("logs").mkdir(
        exist_ok=True
    )

    handler = TimedRotatingFileHandler(
        "logs/pipeline.log",
        when="midnight",
        interval=1,
        backupCount=backup_count
    )

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(message)s"
        ),
        handlers=[
            handler,
            logging.StreamHandler()
        ],
        force=True
    )
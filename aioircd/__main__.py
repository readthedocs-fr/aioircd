import logging
import os
import sys
import trio

import aioircd
from aioircd.config import config as cfg
from aioircd.server import Server

logger = logging.getLogger(__name__)


# Color the [LEVEL] part of messages, need new terminal on Windows
# https://github.com/odoo/odoo/blob/13.0/odoo/netsvc.py#L57-L100
class ColoredFormatter(logging.Formatter):
    colors = {
        logging.DEBUG: (34, 49),  # blue
        aioircd.IO: (37, 49),  # white
        logging.INFO: (32, 49),  # green
        logging.WARNING: (33, 49),  # yellow
        logging.ERROR: (31, 49),  # red
        aioircd.SECURITY: (31, 49),  # red
        logging.CRITICAL: (37, 41),  # white fg, red bg
    }
    def format(self, record):
        fg, bg = type(self).colors.get(record.levelno, (32, 49))
        record.levelname = f'\033[1;{fg}m\033[1;{bg}m{record.levelname}\033[0m'
        return super().format(record)

def main():
    stderr = logging.StreamHandler()
    stderr.formatter = (
        ColoredFormatter('%(asctime)s [%(levelname)s] %(message)s')
        if hasattr(sys.stderr, 'fileno') and os.isatty(sys.stderr.fileno()) else
        logging.Formatter('[%(levelname)s] %(message)s')
    )
    root_logger = logging.getLogger('')
    root_logger.handlers.clear()
    root_logger.addHandler(stderr)

    server = Server(cfg.HOST, cfg.ADDR, cfg.PORT, cfg.PASS)
    try:
        trio.run(server.serve)
    except Exception:
        logger.critical("Dead", exc_info=True)
    finally:
        logging.shutdown()

main()

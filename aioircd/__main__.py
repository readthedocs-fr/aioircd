import argparse
import logging
import os
import sys
import textwrap
import trio
from socket import gethostname, gethostbyname

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

# Dummy argparse, used only for --help and --version
parser = argparse.ArgumentParser(
    prog=aioircd.__name__,
    usage=f"{sys.executable} -m {aioircd.__name__}",
    description="single-server minimalist IRC",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=textwrap.dedent(f"""\
        environment variables:
          HOST           public domain name (default: {gethostname()})
          ADDR           ip address to bind (default: {gethostbyname(cfg.HOST)})
          PORT           port to bind (default: 6667)
          PASS           server password (default: )
          TIMEOUT        kick inactive users after x seconds (default: 60)
          PING_TIMEOUT   PING inactive users x seconds before timeout (default: 5)
          LOGLEVEL       logging verbosity (default: WARNING)
    """)
)
parser.add_argument(
    '-V', '--version',
    action='version',
    version=f'{aioircd.__name__} {aioircd.__version__}',
)
parser.parse_args()

main()

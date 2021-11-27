import contextvars
import logging
import pkg_resources

__version__ = pkg_resources.require('aioircd')[0].version

from aioircd.config import config as cfg
logger = logging.getLogger(__package__)
IO = logging.INFO - 5
SECURITY = logging.ERROR + 5
logging.addLevelName(IO, 'IO')
logging.addLevelName(SECURITY, 'SECURITY')
logger.setLevel(cfg.LOGLEVEL)
servlocal = contextvars.ContextVar('servlocal')
MAXLINELEN = 512

import aioircd.channel
import aioircd.exceptions
import aioircd.server
import aioircd.states
import aioircd.user

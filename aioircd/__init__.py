import contextvars
import logging
import pkg_resources

__version__ = pkg_resources.require('aioircd')[0].version

import aioircd.config
logger = logging.getLogger(__package__)
IO = logging.INFO - 5
SECURITY = logging.ERROR + 5
logging.addLevelName(IO, 'IO')
logging.addLevelName(SECURITY, 'SECURITY')
logger.setLevel(aioircd.config.loglevel)
servlocal = contextvars.ContextVar('servlocal')
MAXLINELEN = 512

import aioircd.channel
import aioircd.exceptions
import aioircd.server
import aioircd.states
import aioircd.user

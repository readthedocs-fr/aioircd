import logging
import trio
from functools import partial
from typing import Union, List

import aioircd


logger = logging.getLogger(__name__)


class Channel:
    def __init__(self, name):
        self._name = name
        self.users = set()

    def __str__(self):
        return self._name

    @property
    def name(self):
        return self._name

    async def send(self, messages: Union[str, List[str]], skipusers=[]):
        """ Send many messages to each user subcribed in this channel. """
        if isinstance(messages, str):
            messages = [messages]

        async with trio.open_nursery() as self._nursery:
            for message in messages:
                logger.log(aioircd.IO, "send to %s: %s", self, message)
            for user in self.users:
                if user in skipusers:
                    continue
                self._nursery.start_soon(partial(
                    user.send,
                    messages,
                    log=logger.isEnabledFor(logging.DEBUG)
                ))

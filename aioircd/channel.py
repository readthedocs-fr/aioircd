import logging
import trio
from functools import partial
from typing import Union, List, Set

import aioircd


logger = logging.getLogger(__name__)


class Channel:
    """
    The Channel class represents a chat room.

    Attributes:
        name: str
            the channel name.
        users: Set[User]
            a set of user who is subscribe to the channel.
    """

    def __init__(self, name: str) -> None:
        """
        Parameters:
            name: str
                the channel name.
        """
        self._name = name
        self.users = set()

    def __str__(self) -> str:
        """
        We represents the channel object by his name.

        Return: str
            the name of the channel.
        """
        return self._name

    @property
    def name(self):
        """
        Getter for private attributes channel name.

        Returns: str 
            the name of the channel.
        """
        return self._name

    def _log_messages(self, messages: List[str]) -> None:
        """
        Log all messages sent to a client.
        
        Parameters: List[str]
            A list of messages send to the client.
        """
        for message in messages:
            logger.log(aioircd.IO, "send to %s: %s", self, message)

    async def send(self, messages: Union[str, List[str]], skipusers: Set["aioircd.user.User"] = set()) -> None:
        """"
        Send many messages to each user subscribed to this channel.
        
        Parameters:
            messages: Union[str, List[str]]
                Messages to send to the users.
            skipusers: Set[User]
                A set of users to skip sending messages to.
        """
        if isinstance(messages, str):
            messages = [messages]

        async with trio.open_nursery() as self._nursery:
            self._log_messages(messages)
            for user in self.users.difference(skipusers):
                self._nursery.start_soon(partial(
                    user.send,
                    messages,
                    log=logger.isEnabledFor(logging.DEBUG)
                ))

import ipaddress
import logging
import re
import trio
import uuid
from typing import Union, List

import aioircd
from aioircd.config import config as cfg
from aioircd.exceptions import IRCException, Disconnect
from aioircd.states import PasswordState, ConnectedState, QuitState


logger = logging.getLogger(__name__)

message_re = re.compile(r"""
    (?P<command>[A-Z]+)
    (?P<middle>(?:\ [^\ :]+)*)
    (?:\ :(?P<trailing>.+))?
""", re.VERBOSE)

# Nicknames that users should not use
_unsafe_nicks = {
    # RFC
    'anonymous',
    # anope services
    'ChanServ',
    'NickServ',
    'OperServ',
    'MemoServ',
    'HostServ',
    'BotServ',
}

# Networks allowed to use the above unsafe nicks
_safenets = [
    ipaddress.ip_network('::1/128'),
    ipaddress.ip_network('127.0.0.0/8'),
]


class User:
    def __init__(self, stream, nursery):
        servlocal = aioircd.servlocal.get()
        self.stream = stream
        self._nursery = nursery
        self._nick = None
        self._addr = stream.socket.getpeername()
        self.state = None
        self.state = (PasswordState if servlocal.pwd else ConnectedState)(self)
        self.channels = set()
        self._ping_timer = trio.CancelScope()  # dummy

    def __str__(self):
        if self.nick:
            return self.nick

        ip, port, *_ = self._addr
        if ':' in ip:
            return f'[{ip}]:{port}'
        return f'{ip}:{port}'

    @property
    def nick(self):
        return self._nick

    @nick.setter
    def nick(self, nick):
        servlocal = aioircd.servlocal.get()
        servlocal.users[nick] = servlocal.users.pop(self._nick, self)
        self._nick = nick

    def can_use_nick(self, nick):
        """ Whether this user is allowed to use ``nick``. """
        if nick not in _unsafe_nicks:
            return True

        ip = ipaddress.ip_address(self._addr[0])
        return any(ip in net for net in _safenets)

    async def ping_forever(self):
        """
        If the user did not send any message for some time, send him a
        PING message that he should answer ASAP with a PONG message. If
        he fails to answer (maybe because the network failed) he'll be
        automatically disconnected, see :meth:`serve`.
        """
        while True:
            with trio.move_on_after(cfg.TIMEOUT - cfg.PING_TIMEOUT) as self._ping_timer:
                await trio.sleep_forever()
            await self.send('PING', log=logger.isEnabledFor(logging.DEBUG))

    async def serve(self):
        """
        Read for messages on the user socket, parse them and dispatch
        each message to the current's user state.
        """
        buffer = b""
        while type(self.state) is not QuitState:

            # Read the socket in a buffer, wait at most TIMEOUT seconds
            self._ping_timer.deadline = trio.current_time() + (cfg.TIMEOUT - cfg.PING_TIMEOUT)
            with trio.move_on_after(cfg.TIMEOUT) as cs:
                try:
                    chunk = await self.stream.receive_some(aioircd.MAXLINELEN)
                except Exception as exc:
                    raise Disconnect("Network failure") from exc
            if cs.cancelled_caught:
                raise Disconnect("Timeout")
            elif not chunk:
                raise Disconnect("End of transmission")

            # Split the buffer into as many IRC messages as possible,
            # ensure each message has a length of maximum MAXLINELEN
            *messages, buffer = (buffer + chunk).split(b'\r\n')
            if any(len(m) > aioircd.MAXLINELEN - 2 for m in messages + [buffer]):
                raise Disconnect("Payload too long")

            for message in (m for m in messages if m):
                # IO-log all messages, except PING/PONG that are only
                # log in DEBUG
                if not (message.startswith(b'PING') or message.startswith(b'PONG')
                   ) or logger.isEnabledFor(logging.DEBUG):
                    logger.log(aioircd.IO, "recv from %s: %s", self, message)

                # Parse the message
                try:
                    if not (match := message_re.match(message.decode())):
                        raise SyntaxError(f"Couldn't parse {line}")
                except UnicodeDecodeError as exc:
                    raise Disconnect("Gibberish") from exc
                except SyntaxError as exc:
                    raise Disconnect("Parsing error") from exc

                # Re-construct the arguments
                args = [match.group('command')]
                if middle := match.group('middle'):
                    args.extend(middle.split())
                if trailing := match.group('trailing'):
                    args.append(trailing)

                # Execute the command
                try:
                    await self.state.dispatch(*args)
                except IRCException as exc:
                    logger.warning("Command %s sent by %s failed, code: %s",
                        args[0], self, exc.code)
                    await self.send(exc.args[0])

    async def terminate(self, kick_msg="Connection terminated by host"):
        """
        Terminate the connection with this user by closing the
        underlying socket and cancelling the user's nursery effectively
        cancelling all user's related tasks.
        """
        logger.info("Terminate connection of %s", self)
        if type(self.state) != QuitState:
            await self.state.QUIT(f":{kick_msg}".split(' '), kick=True)
        with trio.move_on_after(cfg.PING_TIMEOUT) as cs:
            await self.stream.send_eof()
        await self.stream.aclose()
        self._nursery.cancel_scope.cancel()

    async def send(self, messages: Union[str, List[str]], log=True, skipusers=None):
        """ Send many messages to the user. """
        if isinstance(messages, str):
            messages = [messages]

        if log:
            for msg in messages:
                logger.log(aioircd.IO, "send to %s: %s", self, msg)
        await self.stream.send_all(b"".join(f"{msg}\r\n".encode() for msg in messages))

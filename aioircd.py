#!/usr/bin/env python3

import argparse
import asyncio
import functools
import logging
import os
import re
import textwrap
import warnings
from abc import ABCMeta, abstractmethod

nick_re = re.compile(r"[a-zA-Z][a-zA-Z0-9\-_]{0,8}")
chann_re = re.compile(r"#[a-zA-Z0-9\-_]{1,49}")

logger = logging.getLogger(__name__)

def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--host', type=str, default='::1')
    cli.add_argument('--port', type=int, default=6667)
    cli.add_argument('-v', '--verbose', action='count', default=0)
    cli.add_argument('-s', '--silent', action='count', default=0)
    options = cli.parse_args()

    logging.MSG = logging.INFO + 1
    logging.addLevelName(logging.MSG, 'MSG')
    logging.msg = functools.partial(logging.log, logging.MSG)
    logger.msg = functools.partial(logger.log, logging.MSG)

    class ColoredFormatter(logging.Formatter):
        def format(self, record):
            fg, bg = {
                logging.DEBUG: (34, 49),
                logging.INFO: (32, 49),
                logging.MSG: (37, 49),
                logging.WARNING: (33, 49),
                logging.ERROR: (31, 49),
                logging.CRITICAL: (37, 41),
            }.get(record.levelno, (32, 49))
            record.levelname = f"\033[1;{fg}m\033[1;{bg}m{record.levelname}\033[0m"
            return super().format(record)


    verbosity = 10 * max(0, min(3 - options.verbose + options.silent, 5))
    stdout = logging.StreamHandler()
    stdout.formatter = (ColoredFormatter if os.name != 'nt' else logging.Formatter)(
        "%(asctime)s [%(levelname)s] <%(funcName)s> %(message)s"
    )
    logging.root.handlers.clear()
    logging.root.addHandler(stdout)
    logging.root.setLevel(verbosity)
    if verbosity == 0:
        logging.captureWarnings(True)
        warnings.filterwarnings('default')

    server = Server(options.host, options.port)
    try:
        asyncio.run(server.serve())
    except Exception:
        logger.critical("Fatal error in event loop !", exc_info=True)
    except KeyboardInterrupt:
        print("Press ctrl-c again to force exit")
        try:
            asyncio.run(server.quit())
        except KeyboardInterrupt:
            raise SystemExit(1)


class Server:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.local = ServerLocal()
        self._serv = None

    async def serve(self):
        self._serv = await asyncio.start_server(self.handle, self.host, self.port)
        logger.info("Listening on %s port %i", self.host, self.port)
        async with self._serv:
            await self._serv.serve_forever()

    async def quit(self):
        logger.info("Terminating all connections...")
        self._serv.close()
        for client in self._serv.sockets:
            client.write_eof()
        for client in self._serv.sockets:
            await client.wait_closed()
        await self._serv.wait_closed()
        raise SystemExit(0)

    async def handle(self, reader, writer):
        peeraddr = writer.get_extra_info('peername')[0]
        logger.info("New connection from %s", peeraddr)
        user = User(self.local, reader, writer)
        try:
            await user.serve()
        except Exception:
            logger.exception("Fatal error in client loop !")
        finally:
            writer.close()
            await writer.wait_closed()
        self.local.users.pop(user.nick, None)
        logger.info("Connection with %s closed", peeraddr)


class ServerLocal:
    def __init__(self):
        self.users = {}
        self.channels = {}


class Channel:
    def __init__(self, name, local):
        self.local = local
        self._name = None
        self.name = name
        self.users = []

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, name):
        self.local.channels[name] = self.local.channels.pop(self._name, self)
        self._name = name

    async def send_all(self, msg):
        for user in self.users:
            user.writer.write(f"{msg}\r\n".encode())
        await asyncio.wait([user.writer.drain() for user in self.users])

    async def send_all_except(self, msg, skip_user):
        for user in self.users:
            if user is skip_user:
                continue
            if user.nick == skip_user:
                continue
            user.writer.write(f"{msg}\r\n".encode())
        await asyncio.wait([user.writer.drain() for user in self.users])


class User:
    def __init__(self, local, reader, writer):
        self.local = local
        self.reader = reader
        self.writer = writer
        self.state = UserConnectedState(self)
        self._nick = None

    @property
    def nick(self):
        return self._nick

    @nick.setter
    def nick(self, nick):
        self.local.users[nick] = self.local.users.pop(self._nick, self)
        self._nick = nick

    def __str__(self):
        if self.nick:
            return self.nick
        return self.writer.get_extra_info('peername')[0]

    async def serve(self):
        buffer = b""
        while True:
            try:
                chunk = await self.reader.read(1024)
            except ConnectionResetError:
                break
            if not chunk:
                break

            buffer += chunk
            *lines, buffer = buffer.split(b'\r\n')

            if len(buffer) > 1024:
                raise MemoryError("Message exceed 1024 bytes")

            for line in lines:
                logger.msg("%s < %s", self, line)
                cmd, *args = line.decode().split()
                func = getattr(self.state, cmd, None)
                if getattr(func, 'command', False):
                    try:
                        await func(args)
                    except IRCException as exc:
                        logger.warning("%s sent an invalid command: %s", self, exc.args[0])
                        await self.send(exc.args[0])
                else:
                    logger.warning("%s sent an unknown command: %s", self, cmd)

        self.writer.write_eof()
        await self.writer.drain()

    async def send(self, msg):
        self.writer.write(f"{msg}\r\n".encode())
        await self.writer.drain()


def command(func):
    func.command = True
    return func

class UserMetaState(metaclass=ABCMeta):
    def __init__(self, user):
        object.__setattr__(self, "_user", user)

    def __getattr__(self, attr):
        return getattr(self._user, attr)

    def __setattr__(self, attr, value):
        if hasattr(self._user, attr):
            return setattr(self._user, attr, value)
        super().__setattr__(attr, value)

    @command
    @abstractmethod
    async def PONG(self, args):
        pass

    @command
    @abstractmethod
    async def NICK(self, args):
        pass

    @command
    @abstractmethod
    async def JOIN(self, args):
        pass

    @command
    @abstractmethod
    async def PRIVMSG(self, args):
        pass


class UserConnectedState(UserMetaState):
    """
    TCP connection established but user not registered yet
    """

    @command
    async def PONG(self, args):
        pass

    @command
    async def NICK(self, args):
        if not args:
            raise ErrNoNicknameGiven()
        nick = args[0]
        if nick in self.local.users:
            raise ErrNicknameInUse(nick)
        if not nick_re.match(nick):
            raise ErrErroneusNickname(nick)
        self.nick = nick
        self.state = UserRegisteredState(self._user)

    @command
    async def JOIN(self, args):
        # illegal

        raise ErrNoLogin()

    @command
    async def PRIVMSG(self, args):
        # illegal

        raise ErrNoLogin()


class UserRegisteredState(UserMetaState):
    """
    User connected and registered
    """

    @command
    async def PONG(self, args):
        pass

    @command
    async def NICK(self, args):
        if not args:
            raise ErrNoNicknameGiven()
        nick = args[0]
        if nick in self.local.users:
            raise ErrNicknameInUse(nick)
        if not nick_re.match(nick):
            raise ErrErroneusNickname(nick)
        self.nick = nick

    @command
    async def JOIN(self, args):
        if not args:
            raise ErrNeedMoreParams("JOIN")
        for channel in args:
            if not chann_re.match(channel):
                await self.send(ErrNoSuchChannel.format(channel))

            chann = self.local.channels.get(channel)
            if not chann:
                chann = Channel(channel, self.local)
            chann.users.append(self._user)

            await chann.send_all(f":{self.nick} JOIN {channel}")

            nicks = " ".join(user.nick for user in chann.users)
            prefix = f": 353 {self.nick} = {channel} :"
            maxwidth = 1024 - len(prefix) - 2  # -2 is \r\n
            for line in textwrap.wrap(nicks, width=maxwidth):
                await self.send(prefix + line)
            await self.send(f": 366 {self.nick} {channel} :End of /NAMES list.")

    @command
    async def PRIVMSG(self, args):
        if not args or args[0] == "":
            raise ErrNoRecipient("PRIVMSG")

        user = args[0]
        msg = " ".join(args[1:])
        if not msg or not msg.startswith(":") or len(msg) < 2:
            raise ErrNoTextToSend()

        if user.startswith("#"):
            chann = self.local.channels.get(user)
            if not chann:
                raise ErrNoSuchChannel(user)
            await chann.send_all_except(f":{self.nick} PRIVMSG {user} {msg}", self._user)
        else:
            receiver = self.local.users.get(user)
            if not receiver:
                raise ErrErroneusNickname(user)
            await receiver.send(f":{self.nick} PRIVMSG {user} {msg}")


class IRCException(Exception):
    def __init__(self, *args):
        super().__init__(type(self).format(*args))

    @classmethod
    def format(cls, *args):
        return "{code} {error}".format(
            code=cls.code,
            error=cls.msg % args,
        )


class ErrNoNicknameGiven(IRCException):
    msg = ":No nickname given"
    code = "431"

class ErrErroneusNickname(IRCException):
    msg = "%s :Erroneous nickname"
    code = "432"

class ErrNicknameInUse(IRCException):
    msg = "%s :Nickname is already in use"
    code = "433"

class ErrNoLogin(IRCException):
    mdg = ":User not logged in"
    code = "444"

class ErrNeedMoreParams(IRCException):
    msg = "%s :Not enough parameters"
    code = "461"

class ErrNoSuchChannel(IRCException):
    msg = "%s :No such channel"
    code = "403"

class ErrNoRecipient(IRCException):
    msg = ":No recipient given (%s)"
    code = "411"

class ErrNoTextToSend(IRCException):
    msg = ":No text to send"
    code = "412"

class ErrUnknownCommand(IRCException):
    msg = "%s :Unknown command"
    code = "421"

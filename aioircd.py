#!/usr/bin/env python3

import argparse
import asyncio
import functools
import logging
import re
import warnings
import textwrap
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

    verbosity = 10 * max(0, min(3 - options.verbose + options.silent, 5))
    stdout = logging.StreamHandler()
    stdout.formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] <%(funcName)s> %(message)s"
    )
    logging.root.handlers.clear()
    logging.root.addHandler(stdout)
    logging.root.setLevel(verbosity)
    logging.addLevelName(logging.INFO, 'MSG')
    logging.msg = functools.partial(logging.log, 'MSG')
    logger.msg = functools.partial(logger.log, 'MSG')

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
    def __init__(self, name):
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
        await asyncio.gather([user.writer.drain() for user in self.users])


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
        while chunk := await self.reader.read(1024):
            buffer += chunk
            *lines, buffer = buffer.split(b'\r\n')

            if len(buffer) > 1024:
                raise MemoryError("Message exceed 1024 bytes")

            for line in lines:
                cmd, *args = line.decode().split()
                func = getattr(self.state, cmd, None)
                if getattr(func, 'command', False):
                    logger.msg("%s < %s %s", self, line.decode())
                    try:
                        await func(*args)
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
        self._user = user

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
        self.state = UserRegisteredState(self._client)

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
                chann = Channel(channel)
            chann.users.append(self._user)

            nicks = " ".join(user.nick for user in chann.users)
            maxwidth = 1024 - len("353  :\r\n") - len(channel)

            for line in textwrap.wrap(nicks, width=maxwidth):
                await self.send(f"353 {channel} :{line}")

            await self.send(f"366 {channel} :End of NAMES list")

            await chann.send_all(f":{self.nick} JOIN {channel}")

    @command
    async def PRIVMSG(self, args):
        msg = args.split(":",1)
        if msg[0] in [""," "]:
            raise ErrNoRecipient("PRIVMSG")
        if len(msg)<2 or msg[1] in [""," "]:
            raise ErrNoTextToSend()
        user,message = msg[2:]
        if user.startswith("#"):
            chann = self.local.channels.get(user)
            if chann == None:
                raise ErrNoSuchChannel(user)
            await chann.send_all(f": {self.nick} PRIVMSG {user} :{message}")
        else:
            receiver = self.local.users.get(user)
            if receiver == None:
                raise ErrErroneusNickname(user)
            await receiver.send(f": {self.nick} PRIVMSG {user} :{message}")
        await self.send(f"301 {self.nick} :{message}")


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

#!/usr/bin/env python3

""" A minimalist asynchronous IRC server """

import argparse
import asyncio
import logging
import re
import signal
import textwrap
import warnings
from abc import ABCMeta, abstractmethod

nick_re = re.compile(r"[a-zA-Z][a-zA-Z0-9\-_]{0,8}")
chann_re = re.compile(r"#[a-zA-Z0-9\-_]{1,49}")
unsafe_nicks = [
    # RFC
    'anonymous',
    # anope services
    'ChanServ',
    'NickServ',
    'OperServ',
    'MemoServ',
    'HostServ',
    'BotServ',
]
safe_addrs = [
    '::1',
    '127.0.0.1',  # I know it should be a /8 but flem
]

IOLevel = logging.INFO + 1
logging.addLevelName(IOLevel, 'IO')
logger = logging.getLogger(__name__)

def main():
    """
    Application entrypoint, extract configuration from argparse,
    configure logging and run the server loop.
    """

    cli = argparse.ArgumentParser()
    cli.add_argument('--host', type=str, default='::1')
    cli.add_argument('--port', type=int, default=6667)
    cli.add_argument('-v', '--verbose', action='count', default=0)
    cli.add_argument('-s', '--silent', action='count', default=0)
    options = cli.parse_args()

    # Color the [LEVEL] part of messages, need new terminal on Windows
    # https://github.com/odoo/odoo/blob/13.0/odoo/netsvc.py#L57-L100
    class ColoredFormatter(logging.Formatter):
        colors = {
            10: (34, 49), 20: (32, 49), 21: (37, 49),
            30: (33, 49), 40: (31, 49), 50: (37, 41),
        }
        def format(self, record):
            fg, bg = type(self).colors.get(record.levelno, (32, 49))
            record.levelname = f"\033[1;{fg}m\033[1;{bg}m{record.levelname}\033[0m"
            return super().format(record)

    # Reset logging to ONLY log messages on stdout
    stdout = logging.StreamHandler()
    stdout.formatter = ColoredFormatter(
        "%(asctime)s [%(levelname)s] <%(funcName)s> %(message)s"
    )
    logging.root.handlers.clear()
    logging.root.addHandler(stdout)

    # Set the verbosity, enables python level warnings on -vvv
    verbosity = 10 * max(0, min(3 - options.verbose + options.silent, 5))
    logging.root.setLevel(verbosity)
    if verbosity == 0:
        logging.captureWarnings(True)
        warnings.filterwarnings('default')

    # Start the server on foreground, gracefully quit on the first SIGTERM/SIGINT
    asyncio.set_event_loop(loop := asyncio.new_event_loop())
    sigterm = asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, sigterm.set)

    server = Server(options.host, options.port)
    loop.create_task(server.serve())
    try:
        loop.run_until_complete(sigterm.wait())
    except Exception:
        logger.critical("Fatal error in server loop !", exc_info=True)
    except KeyboardInterrupt:
        pass
    loop.run_until_complete(server.shutdown())
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()
    logging.shutdown()


class Server:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.local = ServerLocal()
        self._serv = None

    async def serve(self):
        """ Start listening for new connections """
        self._serv = await asyncio.start_server(self.handle, self.host, self.port)
        logger.info("Listening on %s port %i", self.host, self.port)

    async def shutdown(self):
        logger.info("Terminating all connections...")
        self._serv.close()
        coros = [self._serv.wait_closed()]
        for user in self.local.users.values():
            user.writer.write_eof()
            coros.append(user.writer.wait_closed())
        await asyncio.wait(coros)

    async def handle(self, reader, writer):
        """ Create a new User and serve him until he disconnects or we kick him """
        peeraddr = writer.get_extra_info('peername')[0]
        logger.info("New connection from %s", peeraddr)
        user = User(self.local, reader, writer)
        try:
            await user.serve()
        except Exception:
            logger.exception("Error in client loop !")
        self.local.users.pop(user.nick, None)
        writer.close()
        await writer.wait_closed()
        logger.info("Connection with %s closed", peeraddr)


class ServerLocal:
    """ Storage shared among all server's entities """
    def __init__(self):
        self.users = {}
        self.channels = {}


class Channel:
    count = 0

    def __init__(self, name, local):
        self.local = local
        self._name = name
        self.users = set()
        self.gid = type(self).count
        type(self).count += 1

    def __hash__(self):
        return self.gid

    @property
    def name(self):
        return self._name

    def __str__(self):
        return self.name

    async def send(self, msg, skip=None):
        logger.log(IOLevel, "%s > %s", self, msg)
        send_coros = [
            user.send(msg, log=False)
            for user in self.users
            if skip is None or user not in skip
        ]
        if send_coros:
            await asyncio.wait(send_coros)


class User:
    count = 0

    def __init__(self, local, reader, writer):
        self.local = local
        self.reader = reader
        self.writer = writer
        self.state = UserConnectedState(self)
        self._nick = None
        self.channels = set()
        self.uid = type(self).count
        type(self).count += 1

    def __hash__(self):
        return self.uid

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

    async def read_lines(self):
        """
        Read messages until (i) the user send a QUIT command or (ii) the
        user close his side of the connection (FIN sent) or (iii) the
        connection is reset.
        """
        buffer = b""
        while type(self.state) != StateQuit:
            try:
                chunk = await self.reader.read(1024)
            except ConnectionResetError:
                await self.state.QUIT(":Connection reset by peer".split())
                return  # Force disconnection
            if not chunk:
                await self.state.QUIT(":EOF received".split())
                break  # Graceful disconnection

            # imagine two messages of 768 bytes are sent together, read(1024)
            # only read the first one and the 256 first bytes of the second,
            # the first ends up in lines, the second in buffer. Next call to
            # read(1024) will complete the second message.
            buffer += chunk
            *lines, buffer = buffer.split(b'\r\n')
            if any(len(line) > 1022 for line in lines + [buffer]):
                # one IRC message cannot exceed 1024 bytes (\r\n included)
                raise MemoryError("Message exceed 1024 bytes")

            for line in lines:
                yield line.decode()

        # gracefull disconnection
        self.writer.write_eof()
        await self.writer.drain()

    async def serve(self):
        """ Listen for new messages and process them """
        async for line in self.read_lines():
            logger.log(IOLevel, "%s < %s", self, line)
            cmd, *args = line.split()
            func = getattr(self.state, cmd, None)
            if getattr(func, 'command', False):
                try:
                    await func(args)
                except IRCException as exc:
                    logger.warning("%s sent an invalid command.", self)
                    await self.send(exc.args[0])
            else:
                logger.warning("%s sent an unknown command: %s", self, cmd)

    def send(self, msg: str, log=True):
        """ Send a message to the user """
        if log:
            logger.log(IOLevel, "%s > %s", self, msg)
        self.writer.write(f"{msg}\r\n".encode())
        return self.writer.drain()  # coroutine


def command(func):
    """ Denote the function can be triggered by an IRC message """
    func.command = True
    return func


class UserState():
    """
    IRC State Machine, user starts Connected then Registed then Quit,
    commands have different meaning in every of those states.
    """

    def __init__(self, user):
        logger.debug("state of user %s changed: %s -> %s", user, user.state, self)
        self.user = user

    @command
    async def PONG(self, args):
        pass

    @command
    async def PASS(self, args):
        logger.debug("pass called by %s while in wrong state.", self.user)

    @command
    async def NICK(self, args):
        logger.debug("nick called by %s while in wrong state.", self.user)

    @command
    async def JOIN(self, args):
        logger.debug("join called by %s while in wrong state.", self.user)

    @command
    async def PRIVMSG(self, args):
        logger.debug("privmsg called by %s while in wrong state.", self.user)

    @command
    async def QUIT(self, args):
        msg = " ".join(args) if args else ":Disconnected"
        for channel in self.user.channels:
            channel.users.remove(self.user)
            await channel.send(f":{self.user.nick} QUIT {msg}")
            if not channel.users:
                self.user.local.channels.pop(channel.name)
        self.user.channels.clear()
        self.user.state = StateQuit(self.user)

    def __str__(self):
        return type(self).__name__[4:-5]


class StateConnected(UserState):
    """
    The user is just connected, he must register via the NICK command
    first before going on.
    """

    @command
    async def PONG(self, args):
        pass

    @command
    async def NICK(self, args):
        if not args:
            raise ErrNoNicknameGiven()
        nick = args[0]
        if nick in self.user.local.users:
            raise ErrNicknameInUse(nick)
        if not nick_re.match(nick):
            raise ErrErroneusNickname(nick)
        if nick in unsafe_nicks and self.user.ip not in safe_addrs:
            raise ErrErroneusNickname(nick)

        self.user.nick = nick
        self.user.state = StateRegistered(self.user)

    @command
    async def PRIVMSG(self, args):
        raise ErrNoLogin()


class StateRegistered(UserState):
    """
    The user sent the NICK command, he is fully registered to the server
    and may use any command.
    """

    @command
    async def PONG(self, args):
        pass

    @command
    async def NICK(self, args):
        if not args:
            raise ErrNoNicknameGiven()
        nick = args[0]
        if nick in self.user.local.users:
            raise ErrNicknameInUse(nick)
        if not nick_re.match(nick):
            raise ErrErroneusNickname(nick)
        self.user.nick = nick

    @command
    async def JOIN(self, args):
        if not args:
            raise ErrNeedMoreParams("JOIN")
        for channel in args:
            if not chann_re.match(channel):
                await self.user.send(ErrNoSuchChannel.format(channel))

            # Find or create the channel, add the user in it
            chann = self.user.local.channels.get(channel)
            if not chann:
                chann = Channel(channel, self.user.local)
                self.user.local.channels[chann.name] = chann
            chann.users.add(self.user)
            self.user.channels.add(chann)

            # Send JOIN response to all
            await chann.send(f":{self.user.nick} JOIN {channel}")

            # Send NAMES list to joiner
            nicks = " ".join(user.nick for user in chann.users)
            prefix = f": 353 {self.user.nick} = {channel} :"
            maxwidth = 1024 - len(prefix) - 2  # -2 is \r\n
            for line in textwrap.wrap(nicks, width=maxwidth):
                await self.user.send(prefix + line)
            await self.user.send(f": 366 {self.user.nick} {channel} :End of /NAMES list.")

    @command
    async def PRIVMSG(self, args):
        if not args or args[0] == "":
            raise ErrNoRecipient("PRIVMSG")

        dest = args[0]
        msg = " ".join(args[1:])
        if not msg or not msg.startswith(":") or len(msg) < 2:
            raise ErrNoTextToSend()

        if dest.startswith("#"):
            # Relai channel message to all
            chann = self.user.local.channels.get(dest)
            if not chann:
                raise ErrNoSuchChannel(dest)
            await chann.send(f":{self.user.nick} PRIVMSG {dest} {msg}", skip={self.user})
        else:
            # Relai private message to user
            receiver = self.user.local.users.get(dest)
            if not receiver:
                raise ErrErroneusNickname(dest)
            await receiver.send(f":{self.user.nick} PRIVMSG {dest} {msg}")


class StateQuit(UserState):
    """ The user sent the QUIT command, no more message should be processed """


class IRCException(Exception):
    """
    Abstract IRC exception

    They are excepted by serve() and forwarded to the user.
    """
    def __init__(self, *args):
        super().__init__(type(self).format(*args))

    @classmethod
    def format(cls, *args):
        return ": {code} {error}".format(
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
    msg = ":User not logged in"
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


if __name__ == "__main__":
    main()

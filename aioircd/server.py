import dataclasses
import logging
import signal
import trio

import aioircd
from aioircd.exceptions import Disconnect
from aioircd.user import User


logger = logging.getLogger(__name__)


class Server:
    def __init__(self, addr, port, pwd):
        self.addr = addr
        self.port = port
        self.pwd = pwd

    async def handle(self, stream):
        servlocal = aioircd.servlocal.get()
        async with trio.open_nursery() as nursery:
            user = User(stream, nursery)
            logger.info("Connection with %s established.", user)
            nursery.start_soon(user.ping_forever)
            try:
                await user.serve()
            except Disconnect as exc:
                logger.warning("Protocol violation while serving %s, %s.", user, repr(exc.__cause__ or exc))
                await user.terminate(exc.args[0] if exc.args else "Protocol violation")
            except Exception:
                logger.exception("Error while serving %s.", user)
                await user.terminate("Internal host error")
            else:
                await user.terminate()

        logger.info("Connection with %s closed.", user)

    async def _onterm(self):
        with trio.open_signal_receiver(signal.SIGTERM, signal.SIGINT) as signal_aiter:
            async for _ in signal_aiter:
                if self._nursery.cancel_scope.cancel_called:
                    raise KeyboardInterrupt()
                self._nursery.cancel_scope.cancel()

    async def serve(self):
        aioircd.servlocal.set(ServLocal(self.addr, self.pwd, {}, {}))
        async with trio.open_nursery() as self._nursery:
            self._nursery.start_soon(self._onterm)
            logger.info("Listening on %s port %s.", self.addr, self.port)
            await trio.serve_tcp(self.handle, self.port, host=self.addr)


@dataclasses.dataclass(eq=False)
class ServLocal:
    host: str
    pwd: str  # password, "pass" is a reserved keyword
    users: dict
    channels: dict

    def __repr__(self):
        return (
            f'{self.__name__}('
            f'host: {self.host!r}, '
            f'pass: {"yes" if self.pwd else "no"}, '
            f'users: {len(self.users)}, '
            f'channels: {len(self.channels)})'
        )

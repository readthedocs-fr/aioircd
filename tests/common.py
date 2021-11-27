#!venv/bin/python3

import inspect
import itertools
import functools
import unittest

import trio
import trio.testing

import aioircd
from aioircd.config import config as cfg
from aioircd.server import Server, ServLocal
from aioircd.states import ConnectedState, RegisteredState


_latin_alpha = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
def _unique_id_gen(alphabet=_latin_alpha, base_length=1):
    for r in itertools.count(base_length):
        for comb in itertools.combinations_with_replacement(alphabet, r):
            yield ''.join(comb)
newid = functools.partial(next, _unique_id_gen())


RealUser = aioircd.user.User
DEFAULT_CONFIG = {
    'HOST': 'ip6-localhost',
    'ADDR': '::1',
    'PORT': 6667,
    'PASS': '',
    'LOGLEVEL': 'ERROR',
    'TIMEOUT': 5,
    'PING_TIMEOUT': 2,
}


_users = []
class FakeUser(aioircd.user.User):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._test_stream = None
        _users.append(self)

    async def usend(self, messages):
        """ Send many messages from the user to the server. """
        if isinstance(messages, str):
            messages = [messages]
        await self._test_stream.send_all(b"".join(f"{msg}\r\n".encode() for msg in messages))

    async def urecv(self):
        """ Receive as many bytes as possible from the server during .1 seconds """
        buffer = b""
        with trio.move_on_after(.1):
            while chunk := await self._test_stream.receive_some():
                buffer += chunk
        return buffer.decode()

    async def waitforstate(self, state):
        return await waitfor(lambda: type(self.state) is state)


async def waitfor(predicate, timeout=.1, sleep=.01):
    """ Wait at most ``timeout`` secs for ``predicate()`` be be truthy. """
    with trio.move_on_after(timeout):
        while not predicate():
            await trio.sleep(sleep)
        return True
    return False


class AsyncTestCase(unittest.TestCase):
    def __init_subclass__(cls, /, *args, **kwargs):
        for fname, corofunc in inspect.getmembers(cls, inspect.iscoroutinefunction):
            if not fname.startswith('atest_'):
                continue

            @functools.partial(setattr, cls, fname[1:])
            @functools.wraps(corofunc)
            def test_x(self, corofunc=corofunc):
                @trio.run
                async def atest_x():
                    async with trio.open_nursery() as nursery:
                        await corofunc(self, nursery)
                        nursery.cancel_scope.cancel()

        super().__init_subclass__(*args, **kwargs)


class TestIRC(unittest.TestCase):
    config = {}

    @classmethod
    def setUpClass(cls):
        aioircd.user.User = aioircd.server.User = FakeUser
        cfg.__dict__.update(dict(DEFAULT_CONFIG, **cls.config))
        cls._server = Server(cfg.HOST, cfg.ADDR, cfg.PORT, cfg.PASS)
        cls._servlocal = ServLocal(cfg.HOST, cfg.PASS, {}, {})

    @classmethod
    def tearDownClass(cls):
        aioircd.user.User = aioircd.server.User = RealUser

    def setUp(self):
        self._users = _users
        self._users.clear()

    def tearDown(self):
        for user in self._users:
            trio.run(user._test_stream.aclose)

    async def start_server(self, nursery):
        aioircd.servlocal.set(self._servlocal)
        self._listeners = await nursery.start(functools.partial(
            trio.serve_tcp, self._server.handle, 0, host=self._server.addr))

    async def connect_user(self):
        user_count = len(_users)
        stream = await trio.testing.open_stream_to_socket_listener(self._listeners[0])
        await waitfor(lambda: len(_users) == user_count + 1)
        user = self._users[user_count]
        user._test_stream = stream
        return user

    async def register(self, user, nickname, username=None, realname=None):
        if username is None:
            username = f'john-doe-{newid()}'
        if realname is None:
            realname = f'John Doe'

        messages = [f"NICK {nickname}", "USER {username} 0 * :{realname}"]
        if cfg.PASS:
            messages.insert(0, f"PASS {cfg.PASS}")

        await user.usend(messages)
        await user.urecv()  # consume MOTD
        self.assertTrue(await user.waitforstate(RegisteredState))


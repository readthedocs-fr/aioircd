import unittest
import collections
import aioircd
import asyncio
import logging

class AsyncStreamMock:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.enqueued = collections.deque()
        self.sentinel = b""

    def all_messages(self):
        return self.queue._queue + self.enqueued

    def write(self, s):
        self.enqueued.append(s)

    def write_eof(self):
        self.enqueued.append(self.sentinel)

    async def drain(self):
        while self.enqueued:
            await self.queue.put(self.enqueued.popleft())

    async def read(self, n=0):
        return await asyncio.wait_for(self.queue.get(), 1)

    def close(self):
        self.queue.put_nowait(self.sentinel)

    async def wait_closed(self):
        async def _wait_closed():
            while not self.is_closed():
                await asyncio.sleep(0)
        await asyncio.wait_for(_wait_closed(), 1)
        self.queue.get_nowait()

    def is_closed(self):
        return not self.queue.empty() and self.queue._queue[0] == self.sentinel

    def get_extra_info(self, *args):
        return ("127.0.0.1", 0)


class TestIRC(unittest.IsolatedAsyncioTestCase):
    async def wait(self, func):
        async def _wait():
            while True:
                if result := func():
                    return result
                await asyncio.sleep(0)
        return await asyncio.wait_for(_wait(), 1)


    async def test_nick_join_privmsg_quit(self):
        print()
        server = aioircd.Server(host=None, port=None, pwd=None)

        joe_read = AsyncStreamMock()
        joe_write = AsyncStreamMock()
        joe_task = asyncio.create_task(
            server.handle(joe_write, joe_read)
        )

        leo_read = AsyncStreamMock()
        leo_write = AsyncStreamMock()
        leo_task = asyncio.create_task(
            server.handle(leo_write, leo_read)
        )

        zoe_read = AsyncStreamMock()
        zoe_write = AsyncStreamMock()
        zoe_task = asyncio.create_task(
            server.handle(zoe_write, zoe_read)
        )

        self.assertFalse(server.local.users, "No user should be registered yet")
        self.assertFalse(server.local.channels, "There should be no channel yet.")

        # Nick
        joe_write.write(b'NICK Joe\r\n')
        await joe_write.drain()
        joe = await self.wait(lambda: server.local.users.get('Joe'))
        self.assertIsInstance(joe.state, aioircd.StateRegistered, "Joe should be registered")
        self.assertEqual(await joe_read.read(), b": 001 Welcome Joe !\r\n")
        self.assertEqual(await joe_read.read(), b": 002 Your host is me\r\n")
        self.assertEqual(await joe_read.read(), b": 003 The server was created at some point\r\n")
        self.assertEqual(await joe_read.read(), f": 004 {aioircd.__name__} {aioircd.__version__}  \r\n".encode())

        leo_write.write(b'NICK Leo\r\n')
        await leo_write.drain()
        leo = await self.wait(lambda: server.local.users.get('Leo'))
        self.assertIsInstance(leo.state, aioircd.StateRegistered, "Leo should be registered")
        self.assertEqual(len(leo_read.all_messages()), 4)
        for _ in range(4):
            await leo_read.read()

        self.assertEqual(set(server.local.users), {'Joe', 'Leo'}, "There should be two registered users.")
        self.assertFalse(server.local.channels, "There should be no channel yet.")

        # Join
        joe_write.write(b'JOIN #aioircd\r\n')
        await joe_write.drain()
        self.assertEqual(await joe_read.read(), b':Joe JOIN #aioircd\r\n', "JOIN response sent")
        self.assertEqual(await joe_read.read(), b': 353 Joe = #aioircd :Joe\r\n', "353 response sent")
        self.assertEqual(await joe_read.read(), b': 366 Joe #aioircd :End of /NAMES list.\r\n', "366 response sent")
        self.assertFalse(joe_read.all_messages(), "There shoud be no more JOIN response")
        self.assertEqual(set(server.local.channels), {"#aioircd"}, "There should be one channel.")
        self.assertEqual({user.nick for user in server.local.channels['#aioircd'].users}, {'Joe'}, "There should be one user in the channel.")

        leo_write.write(b'JOIN #aioircd\r\n')
        await leo_write.drain()
        self.assertEqual(await leo_read.read(), b':Leo JOIN #aioircd\r\n', "JOIN response sent")
        self.assertEqual(await leo_read.read(), b': 353 Leo = #aioircd :Joe Leo\r\n', "353 response sent")
        self.assertEqual(await leo_read.read(), b': 366 Leo #aioircd :End of /NAMES list.\r\n', "366 response sent")
        self.assertFalse(leo_read.all_messages(), "There shoud be no more JOIN response")

        self.assertEqual(await joe_read.read(), b':Leo JOIN #aioircd\r\n', "JOIN relayed to Joe")
        self.assertFalse(joe_read.all_messages(), "The JOIN relayed message is only one message")

        self.assertEqual(set(server.local.channels), {"#aioircd"}, "There should be one channel.")
        self.assertEqual({user.nick for user in server.local.channels['#aioircd'].users}, {'Joe', 'Leo'}, "There should be two users in the channel.")

        # Privmsg
        joe_write.write(b'PRIVMSG #aioircd :Hello Leo !\r\n')
        await joe_write.drain()
        self.assertEqual(await leo_read.read(), b':Joe PRIVMSG #aioircd :Hello Leo !\r\n', "PRIVMSG relayed to Leo")
        self.assertFalse(joe_read.all_messages(), "The message is not sent back to Joe")

        # Connect Zoe, she is pretty quick to send all the commands
        zoe_write.write(
            b'NICK Zoe\r\n'
            b'JOIN #python\r\n'
            b'PRIVMSG #python :Where is everyone ?\r\n'
            b'JOIN #aioircd\r\n'
            b'PRIVMSG #aioircd :Hello boys :p\r\n'
            b'PRIVMSG Leo :What\'s up ?\r\n'
        )
        await zoe_write.drain()
        zoe = await self.wait(lambda: server.local.users.get('Zoe'))
        self.assertEqual(await zoe_read.read(), b": 001 Welcome Zoe !\r\n")
        self.assertEqual(await zoe_read.read(), b": 002 Your host is me\r\n")
        self.assertEqual(await zoe_read.read(), b": 003 The server was created at some point\r\n")
        self.assertEqual(await zoe_read.read(), f": 004 {aioircd.__name__} {aioircd.__version__}  \r\n".encode())
        self.assertEqual(await zoe_read.read(), b':Zoe JOIN #python\r\n', "JOIN response sent")
        self.assertEqual(await zoe_read.read(), b': 353 Zoe = #python :Zoe\r\n', "353 response sent")
        self.assertEqual(await zoe_read.read(), b': 366 Zoe #python :End of /NAMES list.\r\n', "366 response sent")
        self.assertEqual(await zoe_read.read(), b':Zoe JOIN #aioircd\r\n', "JOIN response sent")
        self.assertEqual(await zoe_read.read(), b': 353 Zoe = #aioircd :Joe Leo Zoe\r\n', "353 response sent")
        self.assertEqual(await zoe_read.read(), b': 366 Zoe #aioircd :End of /NAMES list.\r\n', "366 response sent")
        self.assertFalse(zoe_read.all_messages(), "There should be no more message")

        # Ensure the two others got the various messages
        self.assertEqual(await joe_read.read(), b':Zoe JOIN #aioircd\r\n', "JOIN relayed to Joe")
        self.assertEqual(await joe_read.read(), b':Zoe PRIVMSG #aioircd :Hello boys :p\r\n', "channel message relayed to Joe")
        self.assertFalse(joe_read.all_messages(), "There should be no more message")

        self.assertEqual(await leo_read.read(), b':Zoe JOIN #aioircd\r\n', "JOIN relayed to Leo")
        self.assertEqual(await leo_read.read(), b':Zoe PRIVMSG #aioircd :Hello boys :p\r\n', "channel message relayed to Leo")
        self.assertEqual(await leo_read.read(), b':Zoe PRIVMSG Leo :What\'s up ?\r\n', "private message relayed to Leo")
        self.assertFalse(leo_read.all_messages(), "There should be no more message")

        self.assertEqual(set(server.local.users), {'Joe', 'Leo', 'Zoe'}, "There should be two registered users.")
        self.assertEqual(set(server.local.channels), {'#aioircd', '#python'}, "There should be two channels.")

        zoe_write.write(b'QUIT :Bye\r\n')
        zoe_write.write_eof()
        await zoe_write.drain()
        await zoe_read.wait_closed()
        await asyncio.wait_for(zoe_task, 1)
        self.assertIsInstance(zoe.state, aioircd.StateQuit, "Zoe quit")

        self.assertEqual(set(server.local.users), {'Joe', 'Leo'}, "There should be two registered users.")
        self.assertEqual(set(server.local.channels), {'#aioircd'}, "There should be one channel.")

        self.assertEqual(await joe_read.read(), b':Zoe QUIT :Bye\r\n', "QUIT relayed to Joe")
        self.assertEqual(await leo_read.read(), b':Zoe QUIT :Bye\r\n', "QUIT relayed to Leo")

        # Close both connexion
        joe_write.write_eof()
        await joe_write.drain()
        await joe_read.wait_closed()
        await asyncio.wait_for(joe_task, 1)

        leo_write.write_eof()
        await leo_write.drain()
        await leo_read.read()  # Consume the QUIT relayed message
        await leo_read.wait_closed()
        await asyncio.wait_for(leo_task, 1)

        self.assertFalse(server.local.users, "There should be two registered users.")
        self.assertFalse(server.local.channels, "There should be one channel.")


if __name__ == '__main__':
    logging.basicConfig(level="INFO")
    unittest.main()

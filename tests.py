#!venv/bin/python3

import os
import random
import unittest
import trio
import contextlib
import textwrap
from functools import partial
from operator import attrgetter
from trio.testing import open_stream_to_socket_listener


os.environ['HOST'] = 'ip6-localhost'
os.environ['ADDR'] = '::1'
os.environ['PORT'] = '6667'
os.environ['PASS'] = 'youwillneverguess'
os.environ['LOGLEVEL'] = 'DEBUG'

import aioircd
from aioircd.config import *
from aioircd.server import Server, ServLocal
from aioircd.states import *
from aioircd.channel import Channel

users = []
class FakeUser(aioircd.user.User):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        users.append(self)
aioircd.user.User = aioircd.server.User = FakeUser


async def waitfor(predicate):
    """ Wait for at most .1 secconds for ``predicate()`` be be truthy. """
    with trio.move_on_after(.1):
        while not predicate():
            await trio.sleep(.01)
        return True
    return False


async def consome_sock(sock):
    """ Receive as many bytes as possible from ``sock`` during .1 seconds """
    buffer = b""
    with trio.move_on_after(.1):
        while chunk := await sock.receive_some():
            buffer += chunk
    return buffer


class TestProtocol(unittest.TestCase):
 def test_bigfattest(self):
  @trio.run
  async def run():
   async with trio.open_nursery() as nursery:

    # Create and stack a background IRC server
    server = Server(HOST, ADDR, PORT, PASS)
    servlocal = ServLocal(HOST, server.pwd, {}, {})
    aioircd.servlocal.set(servlocal)
    listeners = await nursery.start(partial(trio.serve_tcp, server.handle, 0, host='::1'))

    # Connect Bob
    bob_sock = await open_stream_to_socket_listener(listeners[0])
    self.assertTrue(await waitfor(lambda: len(users) == 1))
    bob = users[0]
    self.assertEqual(type(bob.state), PasswordState)

    # Bob sends CAP
    await bob_sock.send_all(b'CAP LS 302\r\n')
    self.assertRegex(await consome_sock(bob_sock), br":ip6-localhost 400 \[::1\]:\d+ - :Command CAP is unknown\.\r\n")
    self.assertEqual(type(bob.state), PasswordState)

    # Bob sends PASS
    await bob_sock.send_all(b"PASS youwillneverguess\r\n")
    self.assertEqual(await consome_sock(bob_sock), b"", "The PASS command does not reply")
    self.assertEqual(type(bob.state), ConnectedState)

    # Bob sends NICK and USER
    await bob_sock.send_all(b"NICK bob\r\n")
    self.assertEqual(await consome_sock(bob_sock), b"", "Only NICK without USER does not reply")
    await bob_sock.send_all(b"USER bob 0 * :Bob\r\n")
    self.assertEqual(await consome_sock(bob_sock), textwrap.dedent(f"""\
        :ip6-localhost 001 bob :Welcome to the Internet Relay Network bob\r
        :ip6-localhost 002 bob :Your host is ip6-localhost, running version {aioircd.__version__}\r
        :ip6-localhost 003 bob :The server was created someday\r
        :ip6-localhost 004 bob aioircd {aioircd.__version__}  \r
        :ip6-localhost 005 bob AWAYLEN=0 CASEMAPPING=ascii CHANLIMIT=#:,&: CHANMODES= CHANNELLEN=50 CHANTYPES=& ELIST= :are supported by this server\r
        :ip6-localhost 005 bob HOSTLEN=63 KICKLEN=0 MAXLIST= MAXTARGETS=12MODES=0 NICKLEN=15 STATUSMSG= TOPICLEN=0 USERLEN=1 :are supported by this server\r
        :ip6-localhost 422 bob :MOTD File is missing\r
        """).encode())
    self.assertEqual(type(bob.state), RegisteredState)

    # Bob sends PING
    token = random.randint(1000, 9999)
    await bob_sock.send_all(f"PING {token}\r\n".encode())
    self.assertEqual(await consome_sock(bob_sock), f":ip6-localhost PONG ip6-localhost {token}\r\n".encode())

    # Connect Eve, she sends PASS+NICK+USER and consumes the motd
    eve_sock = await open_stream_to_socket_listener(listeners[0])
    await eve_sock.send_all(textwrap.dedent("""\
        PASS youwillneverguess\r
        NICK eve\r
        USER eve 0 * :Eve\r
        """).encode())
    await consome_sock(eve_sock)
    eve = users[1]
    self.assertEqual(type(eve.state), RegisteredState)

    # Connect Liz, she sends PASS+NICK+USER and consumes the motd
    liz_sock = await open_stream_to_socket_listener(listeners[0])
    await liz_sock.send_all(textwrap.dedent("""\
        PASS youwillneverguess\r
        NICK liz\r
        USER liz 0 * :Liz\r
        """).encode())
    await consome_sock(liz_sock)
    liz = users[2]
    self.assertEqual(type(liz.state), RegisteredState)

    # Bob sends JOIN
    self.assertFalse(bob.channels)
    self.assertNotIn('#readthedocs', servlocal.channels)
    await bob_sock.send_all(b"JOIN #readthedocs\r\n")
    self.assertEqual(await consome_sock(bob_sock), textwrap.dedent("""\
        :bob JOIN #readthedocs\r
        :ip6-localhost 353 bob = #readthedocs :bob\r
        :ip6-localhost 366 bob #readthedocs :End of /NAMES list.\r
        """).encode())
    self.assertIn('#readthedocs', servlocal.channels)
    rtdchan = servlocal.channels['#readthedocs']
    self.assertIn(rtdchan, bob.channels)
    self.assertIn(bob, rtdchan.users)

    # Eve JOIN readthedocs
    await eve_sock.send_all(b"JOIN #readthedocs\r\n")
    self.assertEqual(await consome_sock(eve_sock), textwrap.dedent("""\
        :eve JOIN #readthedocs\r
        :ip6-localhost 353 eve = #readthedocs :bob eve\r
        :ip6-localhost 366 eve #readthedocs :End of /NAMES list.\r
        """).encode())
    self.assertEqual(await consome_sock(bob_sock), b":eve JOIN #readthedocs\r\n")
    self.assertIn(rtdchan, eve.channels)
    self.assertIn(eve, rtdchan.users)

    # Liz LIST all channels
    await liz_sock.send_all(b"LIST\r\n")
    self.assertEqual(await consome_sock(liz_sock), textwrap.dedent("""\
        :ip6-localhost 321 liz Channel :Users Name\r
        :ip6-localhost 322 liz #readthedocs 2 :\r
        :ip6-localhost 323 liz :End of /LIST\r
        """).encode())

    # Liz JOIN readthedocs too
    await liz_sock.send_all(b"JOIN #readthedocs\r\n")
    await consome_sock(bob_sock)
    await consome_sock(eve_sock)
    self.assertEqual(await consome_sock(liz_sock), textwrap.dedent("""\
        :liz JOIN #readthedocs\r
        :ip6-localhost 353 liz = #readthedocs :bob eve liz\r
        :ip6-localhost 366 liz #readthedocs :End of /NAMES list.\r
        """).encode())
    self.assertIn(rtdchan, liz.channels)
    self.assertIn(liz, rtdchan.users)

    # Eve greeting the chat
    await eve_sock.send_all(b"PRIVMSG #readthedocs :Hi all!\r\n")
    self.assertEqual(await consome_sock(eve_sock), b"")
    self.assertEqual(await consome_sock(liz_sock), b":eve PRIVMSG #readthedocs :Hi all!\r\n")
    self.assertEqual(await consome_sock(bob_sock), b":eve PRIVMSG #readthedocs :Hi all!\r\n")

    # Eve PART from readthedocs
    await eve_sock.send_all(b"PART #readthedocs :I'm taking a break\r\n")
    self.assertTrue(await waitfor(lambda: rtdchan not in eve.channels))
    self.assertEqual(await consome_sock(eve_sock), b"")
    self.assertEqual(await consome_sock(liz_sock), b":eve PART #readthedocs :I'm taking a break\r\n")
    self.assertEqual(await consome_sock(bob_sock), b":eve PART #readthedocs :I'm taking a break\r\n")
    self.assertNotIn(rtdchan, eve.channels)
    self.assertNotIn(eve, rtdchan.users)

    # Liz send message to Eve
    await liz_sock.send_all(b"PRIVMSG eve :Hi, how are you ?\r\n")
    self.assertEqual(await consome_sock(bob_sock), b"")
    self.assertEqual(await consome_sock(liz_sock), b"")
    self.assertEqual(await consome_sock(eve_sock), b":liz PRIVMSG eve :Hi, how are you ?\r\n")

    # Bob check users in the channel
    await bob_sock.send_all(b"NAMES #readthedocs\r\n")
    self.assertEqual(await consome_sock(bob_sock), textwrap.dedent("""\
        :ip6-localhost 353 bob = #readthedocs :bob liz\r
        :ip6-localhost 366 bob #readthedocs :End of /NAMES list.\r
        """).encode())

    # Bob QUIT the server, he need to sleep
    await bob_sock.send_all(b"QUIT :Bye\r\n")

    self.assertEqual(await consome_sock(eve_sock), b"")  # she has no channel in common with bob
    self.assertEqual(await consome_sock(liz_sock), b":bob QUIT :Quit: Bye\r\n")
    self.assertTrue(await waitfor(lambda: type(bob.state) == QuitState))
    self.assertNotIn(rtdchan, bob.channels)
    self.assertNotIn(bob, rtdchan.users)

    # Liz QUIT the server too, but we don't know why
    await liz_sock.send_all(b"QUIT\r\n")
    self.assertTrue(await waitfor(lambda: type(liz.state) == QuitState))
    self.assertNotIn(rtdchan, liz.channels)
    self.assertNotIn(liz, rtdchan.users)
    self.assertNotIn(rtdchan, servlocal.channels)

    # Eve QUIT the server
    await eve_sock.send_all(b"QUIT\r\n")
    self.assertTrue(await waitfor(lambda: type(eve.state) == QuitState))

    # Stop the server
    nursery.cancel_scope.cancel()

if __name__ == '__main__':
    import logging
    logging.basicConfig(level="DEBUG")
    unittest.main()

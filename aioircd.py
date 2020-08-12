#!/usr/bin/env python3

import argparse
import asyncio
import logging
import warnings

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
        user = User(reader, writer)
        try:
            await user.serve()
        except Exception:
            logger.exception("Fatal error in client loop !")
        finally:
            writer.close()
            await writer.wait_closed()
        logger.info("Connection with %s closed", peeraddr)


class User:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def serve(self):
        buffer = b""
        while chunk := await self.reader.read(1024):
            buffer += chunk
            *lines, buffer = buffer.split(b'\r\n')

            if len(buffer) > 1024:
                raise MemoryError("Message exceed 1024 bytes")

            for line in lines:
                msg = parse(line)


        self.writer.write_eof()
        await self.writer.drain()


def parse(line: bytes):
    """ tokeniser + parser """
    return line

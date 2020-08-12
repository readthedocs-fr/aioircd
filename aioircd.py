#!/usr/bin/env python3

import argparse
import asyncio
import logging
import pathlib
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
            "%(asctime)s [%(levelname)s] <%(funcName)s> %(message)s")
    logging.root.handlers.clear()
    logging.root.addHandler(stdout)
    logging.root.setLevel(verbosity)
    if verbosity == 0:
        logging.captureWarnings(True)
        warnings.filterwarnings('default')

    try:
        asyncio.run(serve(options.host, options.port))
    except Exception:
        logger.critical("Fatal error in event loop !", exc_info=True)
    except KeyboardInterrupt:
        raise SystemExit(1)


async def serve(host, port):
    server = await asyncio.start_server(handler, host, port)
    logger.info("Listening on %s port %i", *server.sockets[0].getsockname()[:2])
    async with server:
        await server.serve_forever()


async def handler(reader, writer):
    logger.info("New connection from %s", writer.get_extra_info('peername')[0])
    writer.close()
    await writer.wait_closed()
    logger.info("Connection with %s closed", writer.get_extra_info('peername')[0])

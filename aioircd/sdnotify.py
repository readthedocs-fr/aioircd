import socket
import os

def notify(payload: bytes):
    if _sdsocket:
        _sdsocket.sendall(payload)


def ready():
    notify(b"READY=1")


def reloading():
    notify(b"RELOADING=1")


def stopping():
    notify(b"STOPPING=1")


def status(line: str):
    notify(b"STATUS=" + line.encode())


# Setup
_sdsocket = None
_notify_socket = os.getenv('NOTIFY_SOCKET', '')
if _notify_socket:
    if _notify_socket.startswith('@'):
        _notify_socket = f'\0{_notify_socket[1:]}'
    _sdsocket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    _sdsocket.connect(_notify_socket)

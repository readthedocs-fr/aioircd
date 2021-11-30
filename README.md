aioircd
=======

A minimalist python asynchronous IRC server built on top of
[Trio](https://github.com/python-trio/trio).

### Installation and Usage

Download and install the latest stable version using pip.
Windows users might replace `python3` by `py`.

    python3 -m pip install aioircd

Then run the server:

    HOST=0.0.0.0 LOGLEVEL=INFO python3 -m aioircd

The configuration is done via environment variables, see `--help`:

    optional arguments:
      -h, --help     show this help message and exit
      -V, --version  show program's version number and exit

    environment variables:
      HOST           public domain name (default: julien-UX410UAR)
      ADDR           ip address to bind (default: 127.0.1.1)
      PORT           port to bind (default: 6667)
      PASS           server password (default: )
      TIMEOUT        kick inactive users after x seconds (default: 60)
      PING_TIMEOUT   PING inactive users x seconds before timeout (default: 5)
      LOGLEVEL       logging verbosity (default: WARNING)

### Scope

We try to both keep only implement the most important commands and to
make sure all modern IRC clients are working. If you are having
troubles using aioircd with your client feel free to open an issue.

Stuff we don't plan to support: server connections, user modes, channel
modes.

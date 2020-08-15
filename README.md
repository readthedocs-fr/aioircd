aioircd
=======

A minimalist asynchronous IRC server

### Installation

Download and install the latest stable version using pip.
Windows users might replace `python3` by `py`.

	python3 -m pip install -i https://pypi.drlazor.be aioircd

Then simply run the `aioircd` command with the optionnal argument
listed bellow.

	usage: aioircd [--host HOST] [--port PORT] [-v] [-s]

	optional arguments:
	  --host HOST (default: ::1)
	  --port PORT (default: 6667)
	  -v, --verbose
	  -s, --silent

The server by default only logs `WARNING` level messages and above. You
can increase the verbosity by repeating the `-v` option.

### Specification

This minimalist IRC server was developped using the RFCs [2810], [2811],
[2812], and [2813].

It implements the `NICK`, `JOIN`, `PRIVMSG`, and `QUIT` commands.


[2810]: https://tools.ietf.org/html/rfc2810
[2811]: https://tools.ietf.org/html/rfc2811
[2812]: https://tools.ietf.org/html/rfc2812
[2813]: https://tools.ietf.org/html/rfc2813

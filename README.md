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
	  --pwd PASS (default: None)
	  -v, --verbose
	  -s, --silent

The server by default only logs `WARNING` level messages and above. You
can increase the verbosity by repeating the `-v` option.
.

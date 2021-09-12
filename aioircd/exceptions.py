__ALL__ = [
    'Disconnect', 'IRCException', 'ErrNoSuchChannel', 'ErrNoRecipient',
    'ErrNoTextToSend', 'ErrUnknownCommand', 'ErrNoNicknameGiven',
    'ErrErroneusNickname', 'ErrNicknameInUse', 'ErrNotOnChannel',
    'ErrNoLogin', 'ErrNeedMoreParams', 'ErrAlreadyRegistred',
]

import aioircd

class Disconnect(Exception):
    pass

class IRCException(Exception):
    """
    Abstract IRC exception

    They are excepted by dispatch() and forwarded to the user.
    """
    def __init__(self, *args):
        super().__init__(type(self).format(*args))

    @classmethod
    def format(cls, *args):
        return ":{host} {code} {error}".format(
            host=aioircd.servlocal.get().host,
            code=cls.code,
            error=cls.msg.format(*args),
        )

class ErrUnknownError(IRCException):
    # <user> <command> :<info>
    msg = "{} {} :{}"
    code = 400

class ErrNoSuchNick(IRCException):
    msg = "{} :No such nick/channel"
    code = 401

class ErrNoSuchChannel(IRCException):
    msg = "{} :No such channel"
    code = 403

class ErrNoRecipient(IRCException):
    msg = ":No recipient given ({})"
    code = 411

class ErrNoTextToSend(IRCException):
    msg = ":No text to send"
    code = 412

class ErrUnknownCommand(IRCException):
    msg = "{} :Unknown command"
    code = 421

class ErrNoNicknameGiven(IRCException):
    msg = ":No nickname given"
    code = 431

class ErrErroneusNickname(IRCException):
    msg = "{} :Erroneous nickname"
    code = 432

class ErrNicknameInUse(IRCException):
    msg = "{} :Nickname is already in use"
    code = 433

class ErrNotOnChannel(IRCException):
    msg = "{} :You're not on that channel"
    code = 442

class ErrNoLogin(IRCException):
    msg = ":User not logged in"
    code = 444

class ErrNeedMoreParams(IRCException):
    msg = "{} :Not enough parameters"
    code = 461

class ErrAlreadyRegistred(IRCException):
    msg = ":Unauthorized command (already registered)"
    code = 462

class ErrPasswdMismatch(IRCException):
    msg = ":Password incorrect"
    code = 464

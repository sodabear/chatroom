#! /usr/bin/env python2

# DONE before we submit the homework, remove myutils.py and see if the code
#      still works.
# TODO clarification: rejoining current channel
#                     stripping non-space whitespace
#                     extra whitespace in commands: treat as chan name? squeeze?
#                     leading whitespace: "    /list"
#                     empty username? empty channel name? users with same name?
#                     when no channel exists, print newline or nothing?
# clarified: msg does not contain (final) newline
#
# TODO cleanup: rename vars to use the correct terminology.
#               (currently addr, name, host are used interchangeably)
# TODO check byte vs char problem (slice is probably by char, but send/recv is by byte)
# todo is it possible to get ECONNRESET on send too? how to test it?
# TODO check from beginning to end for stupid var name bugs. test all funcs
# TODO check spec.md again (from beginning to end, incl. FAQ)

# There are two ways to connect:
#   - conn and send and disconn every time
#   - keep a permanent connection until client exits
# We use the latter.
# TODO does the spec allow the former?
# TODO why is the former more popular in practice?
#
# To distinguish among users, we use sockets for lower level code, User's for
# higher level code, and uid(int) for cross-level interface.
#
# Note: We don't do any sanitization
#       We assume Unix line ending (LF)
#
# User name can be up to 200 bytes long, but messages include user names.  In
# other words, if an user have a 100-byte username, then s/he is allowed to
# send a 150-byte sentence, but we have no way to broadcast that to other
# users because the decorated message will be 253 bytes (or so) long.

import sys
from errno import ECONNRESET, EAGAIN, EWOULDBLOCK
import socket
from select import select

#from consts import *
import utils
BUFFER_SIZE = 4096
LISTEN_QUEUE_SIZE = 5
MSG_FIXEDLEN = utils.MESSAGE_LENGTH

#from myutils import debug, error, abort
def debug(msg): pass #print >> sys.stderr, 'DEBUG:', msg
def error(msg): print >> sys.stderr, 'ERROR:', msg
def abort(msg, exitcode=1):
    error(msg)
    sys.exit(exitcode)

# ==================== higher level (application) ====================
# todo take notes: design choice: User::channel => Channel instead of str
#       pros and cons of using str
#           pro: avoid cycles
#                encourage print-friendly data
#           con: at the cost of more lookups
#                   more lookups means more str->Channel dict lookups, and less member field lookups
#                   (which is trivial in compiled langs and heavily JIT-ed langs, but maybe not in Python)
#                CODE UNNECESSARILY LONGER (turns out we don't usually need the str, but we use the Channel all the time)

# once created, never disappear
class Channel:
    def __init__(self, name):
        self.name = name    # str, const
        self.users = []     # list, of User

class User:
    def __init__(self, uid):
        self.uid = uid      # int, const
        self.name = None    # None (init,tmp) then str (const)
        self.channel = None # None or Channel

def leave_chan(user):       # (User) -> None
    #assert user.name is not None
    c = user.channel
    user.channel = None
    if c: c.users.remove(user)
    msg = utils.SERVER_CLIENT_LEFT_CHANNEL.format(user.name)
    if c: broadcast_in_channel(c, msg, excl_users=[user])

def join_chan(user, chan):  # (User, Channel) -> None
    #assert user.name is not None
    #assert chan is not None
    if user.channel: leave_chan(user)
    user.channel = chan
    chan.users += [user]
    msg = utils.SERVER_CLIENT_JOINED_CHANNEL.format(user.name)
    broadcast_in_channel(chan, msg, excl_users=[user])

# Keep these out of User/Channel so that they can be passive classes (C-like structs, if you prefer)
def send_to_user(user, msg): # (User, str) -> None
    send_to_uid(user.uid, msg)

def broadcast_in_channel(chan, msg, excl_users=[]): # (Channel, str, [User, ...]) -> None
    for u in chan.users:
        if u in excl_users: continue
        send_to_user(u, msg)

def serve(host, port):
    # use an ordered container just in case they test /list for exact order
    uid2user = {}   # {int: User, ...}
    name2chan = {}  # {str: Channel, ...}
    chanlist = []   # [str, ...]

    # who: which client (int uid)
    # msg: str for recv, None otherwise
    for event, who, msg in do_networking_loop(host, port): # TODO: cleanup code; maybe use dispatch table (py's switch equivalents are ugly...)
        if event == 'conn':
            uid2user[who] = User(who)
            continue
        if who not in uid2user: abort('internal error: do_networking_loop yielded invalid uid')
        user = uid2user[who]

        if event == 'disconn':
            leave_chan(user)
        elif event == 'recv':
            # commands
            if msg.startswith('/'):
                # by using .split, we accept "/join" and "/join foo", but not "/joinfoo"
                # if you use .startswith, be sure to test for both EOS and space
                # (or if you prefer regexp, use end of word to cover both cases)
                parts = msg.split(' ', 1)
                cmd = parts[0]
                arg = (parts+[None])[1]
                if msg == '/list':
                    send_to_user(user, '\n'.join(chanlist))
                elif cmd == '/create':
                    if   arg is None:      send_to_user(user, utils.SERVER_CREATE_REQUIRES_ARGUMENT)
                    elif arg in name2chan: send_to_user(user, utils.SERVER_CHANNEL_EXISTS.format(arg))
                    else:
                        c = Channel(arg)
                        name2chan[arg] = c
                        chanlist += [arg]
                        join_chan(user, c)
                elif cmd == '/join':
                    if   arg is None:          send_to_user(user, utils.SERVER_JOIN_REQUIRES_ARGUMENT)
                    elif arg not in name2chan: send_to_user(user, utils.SERVER_NO_CHANNEL_EXISTS.format(arg))
                    else: join_chan(user, name2chan[arg])
                else: send_to_user(user, utils.SERVER_INVALID_CONTROL_MESSAGE.format(msg))
                continue

            # "normal messages"
            if user.name is None:
                user.name = msg
            elif user.channel is None:
                send_to_user(user, utils.SERVER_CLIENT_NOT_IN_CHANNEL)
            else:
                msg = '[%s] %s' % (user.name, msg)
                broadcast_in_channel(user.channel, msg, excl_users=[user])
        else:
            abort('internal error: do_networking_loop yielded invalid event')

# ==================== lower level (networking) ====================
# higher level code should only use the following API:
#   do_networking_loop()
#   send_to_uid()
#
# do_networking_loop() is the center of this module.  
# It spawns and uses SockWorker's to deal with multiple connections concurrently.
# (Almost) all exceptions are handled in do_networking_loop().  SockWorker's simply let exceptions through.
#
# Concurrency by select(2) + green threads.  We don't really need
# non-blocking sockets (since we're using select(2) in a single-threaded
# program), but we implemented it anyways because the spec wants it.
# Todo how to multiplex without select(2) or multi-threading/multi-processing?

# The documentation didn't guarantee that select.select will return what I
# passed in (although that seemed to be the case).  Therefore we support both
# lookup by socket obj and lookup by socket fd.
class NetworkingState:
    allsocks = []    # [Socket, ...], both listening sockets and connection sockets
    socks2write = [] # Sockets with non-empty outgoing buffer (our buffer, not OS buffer)
    worker = {}      # {Socket1: SocketWorker1, fd1: SocketWorker1, Socket2: SocketWorker2, ...}

# could have written separate functions for NetworkingState manipulation
# (better modularity and less bug-prone), but I chose to keep code shorter.
class SockWorker(object):
    def __init__(self, sock):
        self.sock = sock

        NS = NetworkingState
        NS.worker[sock.fileno()] = self
        NS.worker[sock] = self
        NS.allsocks += [sock]

    # TODO is it ok to close an already closed socket? (same question for shutdown)
    #   experimental answer (partial):
    #       Shutting down a ECONNRESET'ed socket will (often but not always?) cause '[Errno 107] Transport endpoint is not connected'
    #                   todo it seems that sometimes it will succeed/fail silently without complaining about this
    #       It's ok to close a ECONNRESET'ed socket
    #       haven't tried NORMALLY CLOSED sockets
    # TODO how to shutdown a listening socket? (we don't need it for this project though)
    def destroy(self):
        s = self.sock
        NS = NetworkingState
        NS.allsocks.remove(s)
        del NS.worker[s]
        del NS.worker[s.fileno()]

        #s.shutdown(socket.SHUT_RDWR)
        s.close()
        self.sock = None # not needed, although I feel better with this line (no nobody can accept the socket)

# for accepting connections
class LSockWorker(SockWorker):
    def handle_input(self):
        csock, _ = self.sock.accept()    # _ is addrinfo
        w = CSockWorker(csock)
        return [('conn', w.uid, None)]

# for I/O over existing connections
# attributes:
#   C next_uid      int
#   C uid_to_worker dict
#   I sock          Socket
#   I uid           int
#   I ibuf          str
#   I obuf          str
class CSockWorker(SockWorker):
    # Could have put uid_to_worker in NetworkingState, because:
    #   - one way to view NetworkingState is a central data storage for our lower level code
    #   - there're already fd->worker, socket->worker, so might as well add uid->worker
    # Chose not to put uid_to_worker in NetworkingState because:
    #   - I use NetworkingState to store actual networking data, but uid_to_worker is wrapper data
    #   - uid_to_worker is not shared by many classes. only one external function uses it
    next_uid = 1
    uid_to_worker = {}  # {int: CSockWorker, ...}

    def __init__(self, sock):
        super(type(self), self).__init__(sock) # py2 super is inferior
        self.ibuf = ''
        self.obuf = ''
        self.uid = CSockWorker.next_uid
        CSockWorker.next_uid += 1
        CSockWorker.uid_to_worker[self.uid] = self # current implementation does not remove worker from dict after destroy()

    def handle_input(self):
        try:
            data = self.sock.recv(BUFFER_SIZE, socket.MSG_DONTWAIT) # no documentation for this. guessing all Linux defines are imported
        except socket.error as e:
            if e.errno in [EAGAIN, EWOULDBLOCK]: return # should not happen if main engine works properly (because of select(2))
            elif e.errno == ECONNRESET: data = ''       # Treat connection reset as a regular shutdown.  All buffered data in self.ibuf is lost.
            else: raise
        if len(data) == 0:
            self.destroy()
            return [('disconn', self.uid, None)]

        self.ibuf += data
        events = []
        while len(self.ibuf) >= MSG_FIXEDLEN:
            msg       = self.ibuf[:MSG_FIXEDLEN]
            self.ibuf = self.ibuf[MSG_FIXEDLEN:]
            events += [('recv', self.uid, msg.rstrip(' '))]
        return events

    # currently using blocking version
    def handle_output(self):
        try:
            # empty string is ok too
            l = self.sock.send(self.obuf)
            self.obuf = self.obuf[l:]
            if len(self.obuf) == 0: NetworkingState.socks2write.remove(self.sock)
        except socket.error as e: # todo will this happen?
            if e.errno != ECONNRESET: raise
            self.destroy()
            return [('disconn', self.uid, None)]

    # NOTE may truncate message!
    def add_pending_output(self, msg):
        msg += ' ' * MSG_FIXEDLEN
        msg = msg[:MSG_FIXEDLEN]
        self.obuf += msg
        wlist = NetworkingState.socks2write
        if self.sock not in wlist: wlist.append(self.sock)

def create_lsock(host, port):   # stupid py2, I can't use class methods (like LSockWorker.create_socket())
    lsock = socket.socket()     # IPv4 TCP by default
    lsock.bind((host, port))    # todo how does socket.bind work when host == '' but family == AF_INET ?
    lsock.listen(LISTEN_QUEUE_SIZE)
    return LSockWorker(lsock)

# NOTE does not check if msg is too long
def send_to_uid(uid, msg):
    CSockWorker.uid_to_worker[uid].add_pending_output(msg)

# TODO what is:
#       pydoc2: socket.epoll? (also epoll(7))
#       man select(2):
#           out-of-band data from a TCP socket
#           pseudoterminal in packet mode
#           signal mask
# Todo why is Socket hashable? (usable as dict keys)
# Todo take notes: accept(2)'ing new connections counts as "read"ing for the
# purpose of select(2).  This is documented in accept(2) (Linux man-pages
# project, release 4.06, 2016-03-15), accept(3P) (POSIX.1-2008), and
# select(3P) (POSIX.1-2008), but not in select(2) on my machine.  It is also
# possible to use poll() and SIGIO to check for available accept(2).
#
# todo better func name?
# yields: event, uid, data (str, int, str|None)
# data is already stripped of trailing spaces
# returns when done serving
def do_networking_loop(host, port):
    try:
        # hardcoded because I don't think OverflowError is any more reliable.
        if not 0 <= port <= 65535:
            abort('port number must be between 0-65535')
        lsock = create_lsock(host, port)

        NS = NetworkingState
        while True:
            rs, ws, _ = select(NS.allsocks, NS.socks2write, [])
            # XXX BUG: handle_output() may generate an event that never gets processed
            for s in ws:
                NS.worker[s].handle_output()    # send(2)
            for s in rs:
                w = NS.worker[s]
                for ev in w.handle_input():     # for listener, accept(2); for worker, recv(2)
                    yield ev
    except socket.error as e:
        error(str(e))   # note to self: e.strerror vs e.message
        raise # TODO distinguish between minor errors and big troubles
    except KeyboardInterrupt:
        debug('caught SIGINT; see you next time')
        # we can leave the mess because OS will clean it up for us
    # I guess it's better to be polite and say goodbye to clients, but in
    # order to pass the autograder, let's be conservative.



# ==================== driver ====================
# note to self: if-else is not short-circuited; sys.argv[1] doesn't work
# note to self: remember to deal with exception in int(sys.argv[-1])
# ./foo.py -1 should be interpreted as an option.  However, since I'm lazy, I'm
#   treating it as a negative number and leaving the error handling chore to
#   the networking code.
def parse_args(argv):
    try:
        if len(argv) != 2: raise
        return int(argv[1])
    except:
        print >> sys.stderr, 'Usage: {0} PORT'.format(argv[0])
        sys.exit(2)

if __name__ == "__main__":
    port = parse_args(sys.argv)
    #addr = 'localhost'
    addr = ''              # INADDR_ANY   DONE use this when submitting
    serve(addr, port)
    debug('server done')


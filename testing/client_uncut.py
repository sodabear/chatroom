#! /usr/bin/env python2

# DONE before we submit the homework, remove myutils.py and see if the code
#      still works.
#
# TODO cleanup: rename vars to use the correct terminology.
#               (currently addr, name, host are used interchangeably)
# TODO check byte vs char problem (slice is probably by char, but send/recv is by byte)

#
# Although we can handle some commands locally, we choose to send everything
# to server.
# (e.g. we can't check if we are /join'ing a non-existing channel, but we can
# check for a /join without argument)
# pro:
#   - compatible with servers using different set of commands
#   - simpler code
#   - less redundant code
# con:
#   - more traffic
#   - client is dumb: not able to understand what's going on
#
# For more notes and stuffs, see server.py
#

import sys
from errno import ECONNRESET, EAGAIN, EWOULDBLOCK
import socket
from select import select

#from consts import *
import utils
BUFFER_SIZE = 4096
MSG_FIXEDLEN = utils.MESSAGE_LENGTH

#from myutils import debug, error, abort
def debug(msg): pass #print >> sys.stderr, 'DEBUG:', msg
def error(msg): print >> sys.stderr, 'ERROR:', msg
def abort(msg, exitcode=1):
    error(msg)
    sys.exit(exitcode)




# ==================== spaghetti ====================
# remaining recv_buf will be discarded
class ClientExit(Exception):
    def __init__(self, need_cleanup=True):
        self.need_cleanup = need_cleanup

username = None
server_host = None
server_port = None
recv_buf = ''
send_buf = ''

# only func that differs from standard client
# allow more than one 200-byte chunks to be sent at once
def send_buf_addmsg(msg):
    global send_buf
    while len(msg)>200:
        send_buf += msg[:200]
        msg = msg[200:]
    send_buf += (msg + ' '*MSG_FIXEDLEN)[:MSG_FIXEDLEN]

def net_init_conn(host, port):
    try:
        if not 0 <= port <= 65535:
            abort('port number must be between 0-65535')
        sock = socket.socket() # IPv4 TCP by default
        sock.connect((host, port))
        return sock
    except socket.error as e:
        # todo distinguish between different errors
        print utils.CLIENT_CANNOT_CONNECT.format(host, port)
        raise ClientExit(False)

def net_close_conn(sock, need_cleanup=True):
    if not sock: return
    if need_cleanup:
        sock.sendall(send_buf)  # we don't care about errors at this point
        sock.shutdown(socket.SHUT_RDWR)
    sock.close()

def net_recv(sock):
    global recv_buf
    try:
        data = sock.recv(BUFFER_SIZE, socket.MSG_DONTWAIT)
    except socket.error as e:
        if e.errno in [EAGAIN, EWOULDBLOCK]: return
        elif e.errno == ECONNRESET: data = ''       # Treat connection reset as a regular shutdown.  All buffered data in recv_buf is lost.
        else: raise
    if not data:
        print utils.CLIENT_SERVER_DISCONNECTED.format(server_host, server_port)
        raise ClientExit(False)
    recv_buf += data

def net_send(sock):
    global send_buf
    try:
        l = sock.send(send_buf)
        send_buf = send_buf[l:]
    except socket.error as e:
        if e.errno == ECONNRESET: # todo will this happen? (I think it could happen but don't know how to test it)
            print utils.CLIENT_SERVER_DISCONNECTED.format(server_host, server_port)
            raise ClientExit(False)
        if e.errno not in [EAGAIN, EWOULDBLOCK]: # todo: when EAGAIN, is it guaranteed that we wrote nothing into the buffer?
            raise

def erase_prompt():
    sys.stdout.write(utils.CLIENT_WIPE_ME + '\r')

def redraw_prompt():
    sys.stdout.write(utils.CLIENT_MESSAGE_PREFIX)
    sys.stdout.flush()  # note to self: XXX!!!!

def ui_init():
    redraw_prompt()

def ui_print():
    global recv_buf
    l = MSG_FIXEDLEN
    erase_prompt()
    while len(recv_buf) >= l:
        msg      = recv_buf[:l].rstrip(' ')
        recv_buf = recv_buf[l:]
        sys.stdout.write(msg + '\n')
    redraw_prompt()

# TODO how to guarantee non-blocking reads? (I'm currently assuming canonical mode)
# (SIGINT is handled by main_loop)
def ui_read():
    s = sys.stdin.readline()
    if not s: # EOF
        sys.stdout.write('\n')
        raise ClientExit
    redraw_prompt()
    if   s[-2:] in '\r\n': s = s[:-2]
    elif s[-1:] in '\r\n': s = s[:-1]
    send_buf_addmsg(s)

# todo better func name?
# returns when exiting (upon user request or upon server shutdown)
def main_loop():
    sock = None
    try:
        sock = net_init_conn(server_host, server_port)
        send_buf_addmsg(username)
        ui_init()

        while True:
            ws = [sock] if send_buf else []
            rs, ws, _ = select([sys.stdin, sock], ws, [])
            for s in ws: net_send(s)
            for s in rs:
                if s in [sock, sock.fileno()]:
                    net_recv(s)
                    ui_print()
                else:
                    ui_read()
    except socket.error as e:
        error(str(e))
        raise # TODO distinguish between minor errors and big troubles
    except KeyboardInterrupt:
        debug('caught SIGINT; see you next time')
        net_close_conn(sock, True)
    except ClientExit as e:
        net_close_conn(sock, e.need_cleanup)


# ==================== driver ====================
# note to self: if-else is not short-circuited; sys.argv[1] doesn't work
# note to self: remember to deal with exception in int(sys.argv[-1])
# ./foo.py -1 should be interpreted as an option.  However, since I'm lazy, I'm
#   treating it as a negative number and leaving the error handling chore to
#   the networking code.
def parse_args(argv):
    global username, server_host, server_port
    try:
        if len(argv) != 4: raise
        username, server_host, server_port = argv[1], argv[2], int(argv[3])
    except:
        print >> sys.stderr, 'Usage: {0} USERNAME SERVER_ADDR SERVER_PORT'.format(argv[0])
        sys.exit(2)

if __name__ == "__main__":
    parse_args(sys.argv)
    main_loop()
    debug('client done')


"""Native Codex app-server goal operations; slash commands are not ordinary prompts."""
import base64
import json
import os
from pathlib import Path
import re
import select
import socket
import struct


def rpc(method, params, *, resume_thread=False, first_turn=None, on_message=None, after_result=None):
    if os.name == 'nt':
        raise ValueError('Native Codex controls require Linux and a compatible app-server')
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(20)
    try:
        home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser()
        sock.connect(str(home / 'app-server-control' / 'app-server-control.sock'))
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f'GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                      f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        # Read one byte at a time so no first RPC frame is consumed with the handshake.
        headers = b''
        while not headers.endswith(b'\r\n\r\n') and len(headers) < 16384:
            part = sock.recv(1)
            if not part:
                raise ValueError('Codex app-server closed the handshake')
            headers += part
        if not headers.startswith(b'HTTP/1.1 101 '):
            raise ValueError('Codex app-server rejected the connection')

        def send(obj):
            data = json.dumps(obj, ensure_ascii=False).encode()
            length = len(data)
            mask = os.urandom(4)
            size = bytes([0x80 | length]) if length < 126 else (b'\xfe' + struct.pack('!H', length) if length < 65536 else b'\xff' + struct.pack('!Q', length))
            sock.sendall(b'\x81' + size + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(data)))

        def read_exact(size):
            chunks = bytearray()
            while len(chunks) < size:
                part = sock.recv(size - len(chunks))
                if not part:
                    raise ValueError('Codex app-server closed the connection')
                chunks.extend(part)
            return bytes(chunks)

        def receive(timeout=None):
            while True:
                if timeout is not None and not select.select([sock], [], [], timeout)[0]:
                    return None
                first, second = read_exact(2)
                length = second & 127
                if length == 126:
                    length = struct.unpack('!H', read_exact(2))[0]
                elif length == 127:
                    length = struct.unpack('!Q', read_exact(8))[0]
                if length > 10_000_000 or second & 128:
                    raise ValueError('Invalid Codex app-server frame')
                data = read_exact(length)
                if first & 15 == 8:
                    raise ValueError('Codex app-server closed the connection')
                if first & 15 != 1:
                    continue
                response = json.loads(data)
                if on_message is not None:
                    on_message(response)
                return response

        def wait_for(request_id):
            while True:
                response = receive()
                if response.get('id') != request_id or 'method' in response:
                    continue
                if 'error' in response:
                    raise ValueError(str(response['error'].get('message', 'Codex app-server rejected the request')))
                return response.get('result', {})

        capabilities = {'experimentalApi': True} if params.get('historyMode') or on_message is not None else None
        send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'quotacanvas', 'version': '0.0.1'}, 'capabilities': capabilities}})
        wait_for(1)
        send({'jsonrpc': '2.0', 'method': 'initialized'})
        if resume_thread:
            send({'jsonrpc': '2.0', 'id': 2, 'method': 'thread/resume',
                  'params': {'threadId': params['threadId'], 'excludeTurns': True}})
            wait_for(2)
        request_id = 3 if resume_thread else 2
        send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
        result = wait_for(request_id)
        if first_turn is not None:
            thread_id = (result.get('thread') or {}).get('id')
            if not thread_id:
                raise ValueError('Codex did not return a new conversation ID')
            send({'jsonrpc': '2.0', 'id': request_id + 1, 'method': 'turn/start',
                  'params': {**first_turn, 'threadId': thread_id}})
            result['turn'] = wait_for(request_id + 1).get('turn')
        if after_result is not None:
            return after_result(result, send, receive)
        return result
    except OSError as error:
        raise ValueError('Codex app-server unavailable: ' + type(error).__name__) from None
    finally:
        sock.close()


def goal_command(thread_id, command):
    if not isinstance(thread_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', thread_id):
        raise ValueError('Invalid conversation ID')
    if not isinstance(command, str):
        raise ValueError('Invalid command')
    command = command.strip()
    params = {'threadId': thread_id}
    if command == '/goal':
        return rpc('thread/goal/get', params)
    if command == '/goal clear':
        return rpc('thread/goal/clear', {**params, 'origin': 'user'})
    if command in ('/goal pause', '/goal resume'):
        if command.endswith('pause'):
            return rpc('thread/goal/set', {**params, 'origin': 'user', 'status': 'paused'})
        return rpc('thread/goal/set', {**params, 'origin': 'user', 'status': 'active'}, resume_thread=True)
    if command.startswith('/goal ') and command[6:].strip():
        return rpc('thread/goal/set', {**params, 'origin': 'user', 'objective': command[6:].strip(), 'status': 'active'}, resume_thread=True)
    raise ValueError('Unsupported slash command')


def execute_command(thread_id, command):
    if not isinstance(thread_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', thread_id):
        raise ValueError('Invalid conversation ID')
    if not isinstance(command, str) or len(command) > 40000:
        raise ValueError('Invalid command')
    parts = command.strip().split(None, 1)
    name, argument = (parts[0] if parts else ''), (parts[1].strip() if len(parts) > 1 else '')
    params = {'threadId': thread_id}
    if name == '/goal':
        return goal_command(thread_id, command.strip())
    if name == '/rename':
        if not argument or len(argument) > 200:
            raise ValueError('Use /rename followed by a name of 1–200 characters')
        return rpc('thread/name/set', {**params, 'name': argument})
    if argument:
        raise ValueError('This command does not accept arguments')
    if name == '/status':
        return rpc('thread/read', {**params, 'includeTurns': False})
    if name == '/compact':
        return rpc('thread/compact/start', params, resume_thread=True)
    if name == '/fork':
        return rpc('thread/fork', {**params, 'excludeTurns': True})
    if name == '/usage':
        return rpc('account/rateLimits/read', {})
    if name == '/mcp':
        return rpc('mcpServerStatus/list', {'limit': 100})
    if name in ('/stop', '/interrupt'):
        turns = rpc('thread/turns/list', {**params, 'limit': 1, 'sortDirection': 'desc', 'itemsView': 'notLoaded'}).get('data', [])
        if not turns or turns[0].get('status') != 'inProgress':
            return {'interrupted': False, 'message': 'No active turn'}
        rpc('turn/interrupt', {**params, 'turnId': turns[0]['id']})
        return {'interrupted': True, 'turn_id': turns[0]['id']}
    raise ValueError('Unsupported slash command; open the command menu for supported commands')


def create_conversation(cwd, prompt, model=None, effort=None):
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise ValueError('Choose an existing absolute project directory')
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 40000:
        raise ValueError('A first message of 1–40000 characters is required')
    if prompt.lstrip().startswith('/'):
        raise ValueError('Start a conversation with a message; use slash commands after creation')
    # The local reader and collector consume JSONL rollouts. Newer app-servers
    # default to paginated history, so explicitly retain this compatible format.
    params = {'cwd': cwd, 'ephemeral': False, 'historyMode': 'legacy'}
    turn = {'input': [{'type': 'text', 'text': prompt, 'text_elements': []}]}
    if model:
        if not isinstance(model, str) or len(model) > 120:
            raise ValueError('Invalid model')
        params['model'] = model
    if effort:
        if effort not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
            raise ValueError('Invalid reasoning effort')
        turn['effort'] = effort
    return rpc('thread/start', params, first_turn=turn)

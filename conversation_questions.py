"""Read and answer native user-input requests on an already running Codex thread."""
import re
import time

import codex_commands


def _validate_answers(request, answers):
    questions = request['params']['questions']
    if not isinstance(answers, dict) or set(answers) != {question['id'] for question in questions}:
        raise ValueError('Answer every question in this request')
    for question in questions:
        answer = answers[question['id']]
        values = answer.get('answers') if isinstance(answer, dict) else None
        if (not isinstance(values, list) or not 1 <= len(values) <= 20
                or any(not isinstance(value, str) or not value.strip() or len(value) > 40000 for value in values)):
            raise ValueError('Each answer must contain non-empty text')
        options = question.get('options') or []
        if options and not question.get('isOther') and any(value not in {option['label'] for option in options} for value in values):
            raise ValueError('Choose an available answer')
    return {'answers': {key: {'answers': value['answers']} for key, value in answers.items()}}


def _questions(thread_id, response=None):
    if not isinstance(thread_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', thread_id):
        raise ValueError('Invalid conversation ID')
    pending = {}

    def observe(message):
        params = message.get('params') or {}
        if params.get('threadId') != thread_id:
            return
        if message.get('method') == 'item/tool/requestUserInput' and type(message.get('id')) in (int, str):
            pending[(type(message['id']), message['id'])] = message
        elif message.get('method') == 'serverRequest/resolved':
            request_id = params.get('requestId')
            pending.pop((type(request_id), request_id), None)

    def replay(result, send, receive):
        # Reading history must not cold-resume an idle thread or start a turn.
        if ((result.get('thread') or {}).get('status') or {}).get('type') != 'active':
            if response is not None:
                raise ValueError('This question is no longer pending; refresh the conversation')
            return {'requests': []}
        send({'jsonrpc': '2.0', 'id': 'questions:resume', 'method': 'thread/resume',
              'params': {'threadId': thread_id, 'excludeTurns': True}})
        while True:
            message = receive()
            if not message:
                raise ValueError('Codex did not return the running conversation')
            if message.get('id') == 'questions:resume' and 'method' not in message:
                if 'error' in message:
                    raise ValueError(message['error'].get('message', 'Could not read pending questions'))
                break
        # Resume replays server requests after its response. A bounded quiet
        # window also accepts fresh questions; later ones appear on refresh.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and receive(timeout=0.25) is not None:
            pass
        if response is None:
            return {'requests': [
                {'request_id': message['id'], 'thread_id': thread_id,
                 'turn_id': message['params']['turnId'], 'item_id': message['params']['itemId'],
                 'questions': message['params']['questions'], 'is_blocking': message['params'].get('isBlocking', True)}
                for message in pending.values()
            ]}
        request_id, answers = response
        request = pending.get((type(request_id), request_id))
        if request is None:
            raise ValueError('This question is no longer pending; refresh the conversation')
        result = _validate_answers(request, answers)
        send({'jsonrpc': '2.0', 'id': request_id, 'result': result})
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            message = receive(timeout=0.5)
            if message is None:
                continue
            params = message.get('params') or {}
            if (message.get('method') == 'serverRequest/resolved' and params.get('threadId') == thread_id
                    and type(params.get('requestId')) is type(request_id) and params.get('requestId') == request_id):
                return {'answered': True, 'request_id': request_id}
        raise ValueError('Answer sent, but Codex has not confirmed resolution; refresh before retrying')

    return codex_commands.rpc('thread/read', {'threadId': thread_id, 'includeTurns': False},
                              on_message=observe, after_result=replay)


def pending_questions(thread_id):
    return _questions(thread_id)


def respond_to_question(thread_id, request_id, answers):
    if type(request_id) not in (int, str) or (isinstance(request_id, str) and not 1 <= len(request_id) <= 200):
        raise ValueError('Invalid question request ID')
    if not isinstance(answers, dict):
        raise ValueError('Invalid answers')
    return _questions(thread_id, (request_id, answers))

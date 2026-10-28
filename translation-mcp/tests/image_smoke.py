"""Exercise the shipped server on loopback inside a network-isolated container."""
import asyncio
import errno
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import httpx2 as httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from translation_mcp.models import Policy


async def protocol(token):
    url = 'http://127.0.0.1:8000/mcp'
    async with httpx.AsyncClient(trust_env=False, timeout=10) as http:
        assert (await http.post(url)).status_code == 401
        http.headers.update({'Authorization': 'Bearer ' + token})
        async with Client(streamable_http_client(url, http_client=http), mode='legacy') as client:
            tools = (await client.list_tools()).tools
            assert {t.name for t in tools} == {'list_translation_models', 'translate_batch', 'validate_translation', 'review_batch'}
            request = {'segments': [{'id': 'a', 'text': 'Hello {name}'}], 'translations': [{'id': 'a', 'text': '你好 {name}'}]}
            result = await client.call_tool('validate_translation', {'request': request})
            assert not result.is_error and result.structured_content['valid']
            request['translations'][0]['text'] = '你好'
            result = await client.call_tool('validate_translation', {'request': request})
            assert not result.structured_content['valid']
            # Inference gateway is deliberately unreachable; errors must be safe.
            result = await client.call_tool('list_translation_models')
            assert result.structured_content == {'status': 'error', 'error': 'upstream_connection_error'}


def main():
    assert os.getuid() == 65532
    try:
        Path('/app/must-be-read-only').write_text('test')
    except OSError as error:
        assert error.errno in (errno.EROFS, errno.EACCES)
    else:
        raise AssertionError('Container root is writable')
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        token = secrets.token_urlsafe(48)
        (root / 'policy.json').write_text(Policy().model_dump_json())
        (root / 'mcp-token').write_text(token)
        (root / 'gateway-key').write_text('dummy-gateway-key-for-offline-test')
        env = {**os.environ, 'TRANSLATION_POLICY': str(root / 'policy.json'), 'MCP_TOKEN_FILE': str(root / 'mcp-token'),
               'MAGPIE_KEY_FILE': str(root / 'gateway-key'), 'TRANSLATION_DB': str(root / 'data/requests.sqlite'),
               'MAGPIE_BASE_URL': 'http://127.0.0.1:1/v1'}
        process = subprocess.Popen(['python', '-m', 'translation_mcp.server'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                assert process.poll() is None, 'Server exited before readiness'
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=1) as response:
                        assert json.load(response)['status'] == 'ok'
                    break
                except urllib.error.URLError:
                    time.sleep(0.1)
            else:
                raise AssertionError('Server readiness timed out')
            asyncio.run(protocol(token))
            assert (root / 'data/requests.sqlite').stat().st_mode & 0o777 == 0o600
        finally:
            process.terminate()
            try:
                _, logs = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise AssertionError('Server did not stop cleanly') from None
        # Uvicorn re-raises the received signal after completing shutdown.
        assert process.returncode in (0, -signal.SIGTERM), process.returncode
        assert not (root / 'data/requests.sqlite-wal').exists()
        assert b'Traceback' not in logs
        assert token.encode() not in logs and b'dummy-gateway-key' not in logs
        print('Image smoke test passed: non-root, read-only, health, auth, MCP tools, local validation, clean shutdown')


if __name__ == '__main__':
    main()

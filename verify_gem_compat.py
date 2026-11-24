#!/usr/bin/env python3
# Public evaluation only; rights reserved to the extent owned or controlled.
# Existing grants and lawful exceptions preserved. See RIGHTS.md.
"""Public, standard-library-only, pre-purchase gem-platform environment check.

Optional network probes send a synthetic prompt to BOTH configured model IDs.
No secrets or proprietary product source are included in this script.
"""
import argparse
import json
import os
import shutil
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def python_check():
    version = '.'.join(map(str, sys.version_info[:3]))
    return sys.version_info >= (3, 11), 'Python ' + version + ' (requires 3.11+)'


def openssl_check():
    executable = shutil.which('openssl')
    if not executable:
        return False, 'openssl executable not found on PATH'
    try:
        with tempfile.TemporaryDirectory() as folder:
            key = str(Path(folder) / 'test-key.pem')
            public = str(Path(folder) / 'test-public.pem')
            message = str(Path(folder) / 'message.txt')
            signature = str(Path(folder) / 'signature.bin')
            Path(message).write_bytes(b'gem-platform public Ed25519 compatibility probe')
            commands = [
                [executable, 'genpkey', '-algorithm', 'Ed25519', '-out', key],
                [executable, 'pkey', '-in', key, '-pubout', '-out', public],
                [executable, 'pkeyutl', '-sign', '-inkey', key, '-rawin', '-in', message, '-out', signature],
                [executable, 'pkeyutl', '-verify', '-pubin', '-inkey', public, '-rawin', '-in', message, '-sigfile', signature],
            ]
            for command in commands:
                result = subprocess.run(command, capture_output=True, timeout=10, check=False)
                if result.returncode:
                    return False, 'OpenSSL Ed25519 sign/verify probe failed'
        return True, 'OpenSSL Ed25519 keygen/sign/verify passed'
    except (OSError, subprocess.TimeoutExpired):
        return False, 'OpenSSL executable unavailable or timed out'


def sqlite_check():
    try:
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'gem-compat.sqlite3')
            with sqlite3.connect(path, timeout=3) as db:
                db.execute('CREATE TABLE probe (value TEXT NOT NULL)')
                db.execute('INSERT INTO probe VALUES (?)', ('ok',))
                value = db.execute('SELECT value FROM probe').fetchone()[0]
            if value != 'ok':
                return False, 'SQLite write/read returned unexpected value'
        return True, 'SQLite temporary database create/write/read passed'
    except (OSError, sqlite3.Error) as exc:
        return False, 'SQLite writable storage probe failed: ' + type(exc).__name__


def validate_url(base):
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False, 'invalid GEM_MODEL_BASE_URL'
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        return False, 'non-loopback inference endpoints require HTTPS'
    if parsed.path not in ('', '/', '/v1', '/v1/'):
        return False, 'expected endpoint root or /v1 path'
    return True, base.rstrip('/') + '/chat/completions'


def model_check(url, model, api_key):
    payload = json.dumps({'model': model, 'messages': [{'role': 'user', 'content': 'Reply with OK. This is a compatibility probe.'}], 'stream': False}).encode()
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    request = urllib.request.Request(url, data=payload, headers=headers, method='POST')
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPHandler(), urllib.request.HTTPSHandler())
        with opener.open(request, timeout=12) as response:
            data = json.load(response)
        output = data['choices'][0]['message']['content']
        if not isinstance(output, str):
            return False, 'response content is not a string'
        return True, 'HTTP 2xx with compatible chat completion response'
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, IndexError, TypeError, ssl.SSLError) as exc:
        if isinstance(exc, urllib.error.HTTPError):
            return False, 'HTTP status ' + str(exc.code)
        return False, 'connection/response failed (' + type(exc).__name__ + ')'


def main():
    parser = argparse.ArgumentParser(description='Public pre-purchase gem-platform compatibility probe')
    parser.add_argument('--live', action='store_true', help='Send a synthetic prompt to both configured models (may incur inference charges)')
    args = parser.parse_args()
    results = [('Python 3.11+', *python_check()), ('OpenSSL Ed25519', *openssl_check()), ('SQLite writable storage', *sqlite_check())]
    base = os.getenv('GEM_MODEL_BASE_URL', '').strip()
    fast = os.getenv('GEM_MODEL_FAST', '').strip()
    safe = os.getenv('GEM_MODEL_SAFE', '').strip()
    if args.live:
        if not (base and fast and safe):
            results.append(('Live model connectivity', False, 'set GEM_MODEL_BASE_URL, GEM_MODEL_FAST, GEM_MODEL_SAFE'))
        else:
            valid, url = validate_url(base)
            if not valid:
                results.append(('Live model connectivity', False, url))
            else:
                for label, model in (('FAST model connectivity', fast), ('SAFE model connectivity', safe)):
                    results.append((label, *model_check(url, model, os.getenv('GEM_MODEL_API_KEY', ''))))
    else:
        results.append(('Live model connectivity', None, 'SKIPPED (optional; use --live to test both configured models)'))
    print('gem-platform PRE-PURCHASE READINESS REPORT')
    print('=' * 48)
    for label, passed, detail in results:
        print('[{}] {} — {}'.format('PASS' if passed is True else 'FAIL' if passed is False else 'SKIP', label, detail))
    success = all(passed is not False for _, passed, _ in results)
    print('RESULT: ' + ('PASS (tested checks only)' if success else 'FAIL'))
    print('NOTE: This is a prerequisite check, not a guarantee of 100% application compatibility, model quality, or production readiness.')
    print('NOTE: --live sends a synthetic prompt to configured endpoints and may incur provider charges.')
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

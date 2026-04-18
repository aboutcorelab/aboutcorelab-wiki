#!/usr/bin/env python3
"""Wiki local server — bridges web UI to claude CLI for /query and /file-answer."""
import http.server
import json
import os
import subprocess
import urllib.parse
import threading

PORT = 3333
WIKI_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SITE_DIR = os.path.dirname(os.path.abspath(__file__))

class WikiHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SITE_DIR, **kwargs)

    def do_POST(self):
        if self.path == '/api/query':
            self.handle_query()
        elif self.path == '/api/file-answer':
            self.handle_file_answer()
        elif self.path == '/api/rebuild':
            self.handle_rebuild()
        else:
            self.send_error(404)

    def handle_query(self):
        body = self._read_body()
        question = body.get('question', '').strip()
        if not question:
            self._json_response({'error': '질문을 입력해주세요.'}, 400)
            return

        self._json_response({'status': 'started', 'question': question})

    def handle_file_answer(self):
        body = self._read_body()
        self._json_response({'status': 'started'})

    def handle_rebuild(self):
        """Rebuild site data.js"""
        try:
            build_script = os.path.join(SITE_DIR, 'build.py')
            result = subprocess.run(
                ['python3', build_script],
                capture_output=True, text=True, timeout=30,
                cwd=WIKI_ROOT
            )
            self._json_response({
                'status': 'ok',
                'output': result.stdout.strip()
            })
        except Exception as e:
            self._json_response({'error': str(e)}, 500)

    def do_GET(self):
        if self.path.startswith('/api/query-stream'):
            self.handle_query_stream()
        else:
            super().do_GET()

    def handle_query_stream(self):
        """SSE endpoint: runs claude -p and streams output."""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        question = params.get('q', [''])[0].strip()
        if not question:
            self.send_error(400, 'Missing q parameter')
            return

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        # Send start event
        self._sse_send('status', '질의를 처리하고 있습니다...')

        try:
            # Build the prompt for claude -p
            prompt = f"""위키에서 다음 질문에 대한 답변을 작성해주세요.

질문: {question}

지침:
1. wiki/index.md를 읽어 관련 페이지를 식별하세요
2. 관련 페이지들을 읽고 정보를 수집하세요
3. 답변을 한국어로 작성하세요
4. 위키 페이지를 인용할 때 [[page-id|제목]] 형식의 위키링크를 사용하세요
5. 신뢰도를 높음/중간/낮음으로 평가하세요
6. 후속 질문을 제안하세요

마크다운 형식으로 답변해주세요."""

            result = subprocess.run(
                ['claude', '-p', prompt],
                capture_output=True, text=True,
                timeout=120,
                cwd=WIKI_ROOT
            )

            if result.returncode == 0 and result.stdout.strip():
                self._sse_send('result', result.stdout.strip())
            else:
                error_msg = result.stderr.strip() if result.stderr else '응답을 받지 못했습니다.'
                self._sse_send('error', error_msg)

        except subprocess.TimeoutExpired:
            self._sse_send('error', '요청 시간이 초과되었습니다 (120초).')
        except Exception as e:
            self._sse_send('error', str(e))

        self._sse_send('done', '')

    def handle_file_answer_stream(self):
        """Save last query answer as wiki page via claude -p."""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        question = params.get('q', [''])[0]
        answer = params.get('answer', [''])[0]

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        self._sse_send('status', '답변을 위키 페이지로 저장하고 있습니다...')

        try:
            prompt = f"""다음 질의 답변을 wiki/answers/ 에 마크다운 파일로 저장해주세요.

질문: {question}

답변:
{answer}

지침:
1. CLAUDE.md의 Answer Page 형식을 따르세요
2. 파일명은 질문을 kebab-case로 변환하세요
3. wiki/index.md의 답변 테이블에 추가하세요
4. wiki/log.md에 기록을 추가하세요
5. 저장한 파일 경로를 알려주세요"""

            result = subprocess.run(
                ['claude', '-p', prompt],
                capture_output=True, text=True,
                timeout=120,
                cwd=WIKI_ROOT
            )

            if result.returncode == 0:
                self._sse_send('result', result.stdout.strip())
                # Rebuild site
                subprocess.run(['python3', os.path.join(SITE_DIR, 'build.py')],
                             capture_output=True, cwd=WIKI_ROOT, timeout=30)
                self._sse_send('status', '사이트 데이터를 갱신했습니다. 새로고침하세요.')
            else:
                self._sse_send('error', result.stderr.strip() or '저장 실패')
        except Exception as e:
            self._sse_send('error', str(e))

        self._sse_send('done', '')

    def _sse_send(self, event, data):
        # Escape newlines for SSE
        escaped = data.replace('\n', '\\n')
        msg = f"event: {event}\ndata: {escaped}\n\n"
        self.wfile.write(msg.encode('utf-8'))
        self.wfile.flush()

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except:
            return {}

    def _json_response(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        # Quieter logging
        if '/api/' in (args[0] if args else ''):
            print(f"[API] {args[0]}")


if __name__ == '__main__':
    # Also handle /api/file-answer-stream
    orig_get = WikiHandler.do_GET
    def patched_get(self):
        if self.path.startswith('/api/file-answer-stream'):
            self.handle_file_answer_stream()
        else:
            orig_get(self)
    WikiHandler.do_GET = patched_get

    server = http.server.HTTPServer(('127.0.0.1', PORT), WikiHandler)
    print(f"""
╔══════════════════════════════════════╗
║   LLM Wiki Server                    ║
║   http://localhost:{PORT}               ║
║   Ctrl+C to stop                     ║
╚══════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()

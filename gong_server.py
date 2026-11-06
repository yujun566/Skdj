#!/usr/bin/env python3
"""
공 리눅스 에이전트 — 폰의 공이 이 서버에서 명령 실행/파일 편집을 할 수 있게 해주는 작은 HTTP 서버.
의존성: 파이썬 3.8+ 표준 라이브러리만.

실행:  python3 gong_server.py            (포트 8790, 첫 실행 때 토큰 생성해서 보여줌)
옵션:  GONG_PORT=9000 GONG_ROOT=/home/me/projects python3 gong_server.py

보안:
 - 모든 요청에 헤더 X-Gong-Token 필요 (토큰은 gong_token.txt 에 저장)
 - 파일 작업은 GONG_ROOT 아래로만 (기본: 이 파일이 있는 폴더의 상위 = 홈)
 - 명령은 60초 제한, 출력 20KB 제한
 - 폰에서 https로 접근하려면 Cloudflare 터널:  cloudflared tunnel --url http://localhost:8790
"""
import json
import os
import secrets
import shlex
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("GONG_PORT", "8790"))
ROOT = Path(os.environ.get("GONG_ROOT", str(Path.home()))).resolve()
TOKEN_FILE = Path(__file__).with_name("gong_token.txt")
MAX_OUT = 20000

if TOKEN_FILE.exists():
    TOKEN = TOKEN_FILE.read_text().strip()
else:
    TOKEN = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(TOKEN)
    os.chmod(TOKEN_FILE, 0o600)


def safe(p: str) -> Path:
    """ROOT 밖으로 못 나가게"""
    q = (ROOT / p).resolve() if not p.startswith("/") else Path(p).resolve()
    if ROOT not in q.parents and q != ROOT:
        raise PermissionError(f"허용 범위 밖: {q} (ROOT={ROOT})")
    return q


def run(cmd: str, cwd: str = ".") -> dict:
    try:
        r = subprocess.run(cmd, shell=True, cwd=str(safe(cwd)), capture_output=True, text=True, timeout=60)
        out = (r.stdout + ("\n[stderr]\n" + r.stderr if r.stderr.strip() else "")).strip()
        return {"ok": r.returncode == 0, "code": r.returncode, "out": out[-MAX_OUT:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -1, "out": "60초 초과로 중단"}
    except Exception as e:
        return {"ok": False, "code": -1, "out": str(e)}


ACTIONS = {
    "ping":   lambda a: {"ok": True, "root": str(ROOT), "host": os.uname().nodename},
    "run":    lambda a: run(a["cmd"], a.get("cwd", ".")),
    "ls":     lambda a: {"ok": True, "items": sorted(
                  f"{'📁' if x.is_dir() else '📄'} {x.name}" + ("" if x.is_dir() else f"  ({x.stat().st_size}b)")
                  for x in safe(a.get("path", ".")).iterdir())[:300]},
    "read":   lambda a: {"ok": True, "content": safe(a["path"]).read_text(encoding="utf-8", errors="replace")[: a.get("max", 30000)]},
    "write":  lambda a: (safe(a["path"]).parent.mkdir(parents=True, exist_ok=True),
                         safe(a["path"]).write_text(a["content"], encoding="utf-8"),
                         {"ok": True, "bytes": len(a["content"].encode())})[-1],
    "append": lambda a: (open(safe(a["path"]), "a", encoding="utf-8").write(a["content"]), {"ok": True})[-1],
    "delete": lambda a: (_rm(safe(a["path"])), {"ok": True})[-1],
    "mkdir":  lambda a: (safe(a["path"]).mkdir(parents=True, exist_ok=True), {"ok": True})[-1],
    "replace": lambda a: _replace(a),
}


def _rm(p: Path):
    import shutil
    if p == ROOT:
        raise PermissionError("루트는 삭제 불가")
    shutil.rmtree(p) if p.is_dir() else p.unlink()


def _replace(a):
    p = safe(a["path"]); s = p.read_text(encoding="utf-8")
    n = s.count(a["old"])
    if n == 0:
        return {"ok": False, "out": "old 문자열을 못 찾음"}
    if n > 1 and not a.get("all"):
        return {"ok": False, "out": f"old 문자열이 {n}군데 있음. all=true 로 전부 바꾸거나 더 구체적으로"}
    p.write_text(s.replace(a["old"], a["new"]), encoding="utf-8")
    return {"ok": True, "replaced": n}


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Gong-Token")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._json(200, {"gong": "ok", "hint": "POST /api with X-Gong-Token"})

    def do_POST(self):
        if self.headers.get("X-Gong-Token", "") != TOKEN:
            return self._json(401, {"ok": False, "out": "토큰 불일치"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) or b"{}")
            act = req.get("action")
            if act not in ACTIONS:
                return self._json(400, {"ok": False, "out": f"없는 action: {act}"})
            print(f"  ▶ {act} {json.dumps({k: (str(v)[:60]) for k, v in req.items() if k != 'action'}, ensure_ascii=False)}")
            self._json(200, ACTIONS[act](req))
        except Exception as e:
            self._json(500, {"ok": False, "out": f"{type(e).__name__}: {e}"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("=" * 60)
    print(f"  공 리눅스 에이전트  http://0.0.0.0:{PORT}   ROOT={ROOT}")
    print(f"  토큰: {TOKEN}")
    print(f"  (폰 공 설정 → 리눅스 서버 URL/토큰 에 넣기)")
    print("  https 주소 만들기:  cloudflared tunnel --url http://localhost:%d" % PORT)
    print("=" * 60)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

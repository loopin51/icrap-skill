#!/usr/bin/env python3
"""ICRAP 워크스페이스에 SSH(coder ssh)로 붙어 코드를 보내고 실행하고 결과를 가져온다(표준 라이브러리만).

  ws.py check                                            coder CLI·로그인·내 워크스페이스 상태
  ws.py info <워크스페이스>                               파이썬·GPU·디스크·/shared 상태
  ws.py push <워크스페이스> [--dest DIR]                 현재 git 저장소의 파일을 DIR/src 로 보낸다(이전 src 는 지운다)
  ws.py run  <워크스페이스> [--dest DIR] [--timeout S] -- <명령>   DIR/src 에서 명령을 실행하고 출력을 DIR/logs 에도 남긴다
  ws.py exec <워크스페이스> [--cwd DIR] [--timeout S] -- <명령>    아무 디렉터리(기본 홈)에서 명령을 실행한다
  ws.py put  <워크스페이스> <로컬 파일·디렉터리> <원격 디렉터리>    파일·디렉터리 하나를 보낸다
  ws.py pull <워크스페이스> <원격 경로> [로컬 디렉터리]       원격 파일·디렉터리를 가져온다

Coder 주소는 공개 주소 https://coder.blueodor.xyz 가 기본이다(Tailscale 없이 된다). ICRAP_CODER_URL 이나
CODER_URL 로 바꿀 수 있다. 로그인(coder login)은 사용자가 직접 한다 — 이 스크립트는 세션 토큰을 읽거나 출력하지 않는다.

DIR 기본값은 ~/icrap-run/<로컬 저장소 이름>. 실행은 항상 timeout 으로 감싼다(세션이 끊겨도 프로세스가 남지 않게).
종료 코드는 원격 명령의 것을 그대로 돌려준다(124 = 시간 초과). 원격에 닿기 전에 멈추면 3 = 로그인 필요,
4 = 계정 정지·만료다.
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys

MAX_PUSH_BYTES = 200 * 2**20  # 데이터셋까지 실려 가는 것을 막는다. 큰 데이터는 /shared 나 /data 에 둔다.
DEFAULT_TIMEOUT = 540         # Claude Code 의 Bash 도구 한도(10분) 안에서 끝나게 한다.
DEFAULT_CODER_URL = "https://coder.blueodor.xyz"
PORTAL_URL = "https://icrap.blueodor.xyz"
# 워크스페이스의 비대화형 셸에는 conda 가 PATH 에 없다. 사용자가 설치한 uv(~/.local/bin)도 함께 연다.
ENV_PREFIX = 'export PATH="$HOME/miniforge3/bin:$HOME/.local/bin:$PATH"; '


def die(msg, code=2):
    print(f"ws: {msg}", file=sys.stderr)
    sys.exit(code)


def coder():
    path = shutil.which("coder") or os.path.expanduser("~/.local/bin/coder")
    if not os.path.exists(path):
        die("coder CLI 가 없습니다. icrap 스킬의 reference.md \"coder CLI 준비\" 를 따라 설치·로그인하세요.")
    return path


def coder_url():
    return (os.environ.get("ICRAP_CODER_URL") or os.environ.get("CODER_URL") or DEFAULT_CODER_URL).rstrip("/")


def coder_env():
    # coder CLI 는 로그인할 때 쓴 주소를 기억한다. tailnet 주소로 로그인했어도 같은 세션으로 공개 주소를 쓰게 덮는다.
    return {**os.environ, "CODER_URL": coder_url()}


def login_steps():
    return (f"Coder 에 로그인되어 있지 않거나 세션이 만료됐습니다. 사용자가 자기 터미널에서 직접 합니다:\n"
            f"  1) 포털({PORTAL_URL})에 로그인해 워크스페이스 '열기' 를 한 번 누른다(Coder 세션이 생긴다)\n"
            f"  2) coder login {coder_url()}  → 브라우저에 나온 세션 토큰을 그 터미널에 붙여 넣는다\n"
            f"  세션 토큰은 워크스페이스 셸 권한이다. Claude 대화창에 붙여 넣지 말 것.")


_checked = False


def preflight():
    """명령마다 한 번, 로그인돼 있는지 본다. coder ssh 는 로그아웃·만료를 원격 명령의 실패와 같은 종료 코드 1 로 낸다."""
    global _checked
    if _checked:
        return
    r = subprocess.run([coder(), "whoami"], env=coder_env(), capture_output=True, text=True)
    if r.returncode != 0:
        text = (r.stderr + r.stdout).lower()
        lines = [l.strip() for l in (r.stderr or r.stdout).splitlines() if l.strip()]
        reason = next((l for l in lines if l.lower().startswith("error:")), lines[-1] if lines else "")
        if "not active" in text or "suspended" in text:
            die("ICRAP 계정이 정지·만료되어 Coder 접속(SSH 포함)이 막혀 있습니다. 관리자에게 문의하세요.", 4)
        if any(k in text for k in ("signed out", "session has expired", "not logged in", "unauthorized")):
            die(login_steps(), 3)
        die(f"Coder({coder_url()}) 에 확인하지 못했습니다: {reason}", 1)
    _checked = True


def ssh_argv(ws, script):
    # 원격 명령은 문자열 하나로 넘긴다(coder ssh 가 그대로 셸에 준다). 시작 안내 문구는 stderr 로 나온다.
    return [coder(), "ssh", ws, "--", f"bash -c {shlex.quote(ENV_PREFIX + script)}"]


def ssh(ws, script, stdin=None, capture=False):
    preflight()
    return subprocess.run(ssh_argv(ws, script), env=coder_env(), stdin=stdin, stdout=subprocess.PIPE if capture else None)


def repo_root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def default_dest():
    root = repo_root() or os.getcwd()
    return f"~/icrap-run/{os.path.basename(root)}"


def remote_path(p):
    # ~ 를 원격 셸이 풀도록 따옴표 밖에 둔다.
    if p in ("~", "~/"):
        return '"$HOME"'
    return '"$HOME"/' + shlex.quote(p[2:]) if p.startswith("~/") else shlex.quote(p)


def cmd_push(a):
    root = repo_root()
    if not root:
        die("git 저장소 안에서 실행하세요(.gitignore 로 보낼 파일을 정합니다).")
    files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=root,
                           capture_output=True, check=True).stdout.split(b"\0")
    files = [f for f in files if f and os.path.isfile(os.path.join(root, f.decode()))]
    size = sum(os.path.getsize(os.path.join(root, f.decode())) for f in files)
    if size > MAX_PUSH_BYTES and not a.force:
        die(f"보낼 파일이 {size / 2**20:.0f}MiB 입니다(한도 {MAX_PUSH_BYTES // 2**20}MiB). "
            "데이터·체크포인트를 .gitignore 에 넣거나, 정말 보내려면 --force.")
    dest = a.dest or default_dest()
    src = f"{dest}/src"
    tar = subprocess.Popen(["tar", "-czf", "-", "--null", "-T", "-"], cwd=root,
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    script = f"rm -rf {remote_path(src)} && mkdir -p {remote_path(src)} {remote_path(dest + '/logs')} && tar -xzf - -C {remote_path(src)}"
    preflight()
    proc = subprocess.Popen(ssh_argv(a.workspace, script), env=coder_env(), stdin=tar.stdout)
    tar.stdin.write(b"\0".join(files) + b"\0")
    tar.stdin.close()
    tar.stdout.close()
    rc = proc.wait()
    if tar.wait() != 0 or rc != 0:
        die("보내기에 실패했습니다(위 오류 참고). 워크스페이스가 실행 중인지 `icrap workspaces` 로 확인하세요.", 1)
    print(f"{len(files)}개 파일({size / 2**20:.1f}MiB)을 {a.workspace}:{src} 로 보냈습니다.")


def cmd_run(a):
    if not a.command:
        die("실행할 명령을 -- 뒤에 주세요.")
    command = " ".join(a.command) if len(a.command) > 1 else a.command[0]
    dest = a.dest or default_dest()
    log = remote_path(dest + "/logs") + "/$(date +%Y%m%d-%H%M%S).log"
    script = (f"cd {remote_path(dest + '/src')} || {{ echo 'src 가 없습니다. 먼저 push 하세요.' >&2; exit 2; }}; "
              f"mkdir -p {remote_path(dest + '/logs')}; LOG={log}; echo \"[ws] 로그: $LOG\" >&2; "
              f"timeout --kill-after=10 {int(a.timeout)} bash -o pipefail -c {shlex.quote(command)} 2>&1 | tee \"$LOG\"; "
              "rc=${PIPESTATUS[0]}; [ $rc -eq 124 ] && echo \"[ws] 시간 제한(" + str(int(a.timeout)) + "s)에 닿아 멈췄습니다\" >&2; exit $rc")
    sys.exit(ssh(a.workspace, script).returncode)


def cmd_pull(a):
    local = a.local or "."
    os.makedirs(local, exist_ok=True)
    rp = a.remote.rstrip("/")
    parent, base = os.path.dirname(rp) or ".", os.path.basename(rp)
    script = f"tar -czf - -C {remote_path(parent)} {shlex.quote(base)}"
    preflight()
    remote = subprocess.Popen(ssh_argv(a.workspace, script), env=coder_env(), stdout=subprocess.PIPE)
    untar = subprocess.run(["tar", "-xzf", "-", "-C", local], stdin=remote.stdout)
    remote.stdout.close()
    if remote.wait() != 0 or untar.returncode != 0:
        die("가져오기에 실패했습니다(경로를 확인하세요).", 1)
    print(f"{a.workspace}:{a.remote} → {os.path.join(local, base)}")


def timed(command, timeout):
    return (f"timeout --kill-after=10 {int(timeout)} bash -o pipefail -c {shlex.quote(command)}; "
            "rc=$?; [ $rc -eq 124 ] && echo \"[ws] 시간 제한(" + str(int(timeout)) + "s)에 닿아 멈췄습니다\" >&2; exit $rc")


def cmd_exec(a):
    if not a.command:
        die("실행할 명령을 -- 뒤에 주세요.")
    command = " ".join(a.command) if len(a.command) > 1 else a.command[0]
    script = f"cd {remote_path(a.cwd)} || exit 2; " + timed(command, a.timeout)
    sys.exit(ssh(a.workspace, script).returncode)


def local_size(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            if os.path.isfile(fp) and not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total


def cmd_put(a):
    src = os.path.abspath(a.local)
    if not os.path.exists(src):
        die(f"{a.local} 가 없습니다.")
    size = local_size(src)
    if size > MAX_PUSH_BYTES and not a.force:
        die(f"보낼 크기가 {size / 2**20:.0f}MiB 입니다(한도 {MAX_PUSH_BYTES // 2**20}MiB). 큰 데이터는 잡이나 /shared 로 옮기고, "
            "정말 보내려면 --force.")
    parent, base = os.path.dirname(src), os.path.basename(src)
    dest = a.remote_dir.rstrip("/") or "/"
    script = f"mkdir -p {remote_path(dest)} && tar -xzf - -C {remote_path(dest)}"
    preflight()
    tar = subprocess.Popen(["tar", "-czf", "-", "-C", parent, base], stdout=subprocess.PIPE)
    proc = subprocess.Popen(ssh_argv(a.workspace, script), env=coder_env(), stdin=tar.stdout)
    tar.stdout.close()
    rc = proc.wait()
    if tar.wait() != 0 or rc != 0:
        die("보내기에 실패했습니다(위 오류 참고).", 1)
    print(f"{a.local}({size / 2**20:.1f}MiB) → {a.workspace}:{dest}/{base}")


def cmd_check(a):
    path = coder()
    ver = subprocess.run([path, "version"], capture_output=True, text=True).stdout.strip().splitlines()
    print(f"coder CLI: {path} ({ver[0] if ver else '버전 알 수 없음'})")
    print(f"Coder 주소: {coder_url()}")
    preflight()
    r = subprocess.run([path, "list", "-o", "json"], env=coder_env(), capture_output=True, text=True)
    if r.returncode != 0:
        die(f"워크스페이스 목록을 읽지 못했습니다: {r.stderr.strip().splitlines()[-1:] or ''}", 1)
    rows = json.loads(r.stdout or "[]")
    if not rows:
        print("로그인됨. 워크스페이스가 없습니다(만들기는 포털에서 합니다).")
    else:
        print(f"로그인됨({rows[0].get('owner_name', '?')}). 내 워크스페이스:")
    for w in rows:
        b = w.get("latest_build") or {}
        healthy = (w.get("health") or {}).get("healthy")
        state = b.get("status", "?") + ("" if b.get("status") != "running" else (" · 정상" if healthy else " · 에이전트 확인 중"))
        print(f"  {w.get('name'):<24} {state:<20} {w.get('template_name', '')}")


def cmd_info(a):
    script = r"""
echo "python: $(command -v python || echo 없음) $(python --version 2>&1)"
python -c 'import torch; print("torch:", torch.__version__, "cuda:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")' 2>/dev/null || echo "torch: 없음"
echo "uv: $(command -v uv || echo 없음)"
if command -v nvidia-smi >/dev/null; then nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader; else echo "GPU: 없음"; fi
echo "CPU: $(nproc)코어 · 메모리 한도: $(awk '{printf "%.1fGi", $1/1073741824}' /sys/fs/cgroup/memory.max 2>/dev/null || echo ?)"
df -h "$HOME" /data /shared 2>/dev/null | awk 'NR==1 || /\//'
[ -d /shared/users ] && echo "팀 공유: 있음" || echo "팀 공유: 없음(팀 배정 뒤 재시작 필요)"
"""
    sys.exit(ssh(a.workspace, script).returncode)


def main():
    p = argparse.ArgumentParser(prog="ws", description="ICRAP 워크스페이스에 SSH 로 붙어 코드 실행")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("check"); s.set_defaults(fn=cmd_check)
    s = sub.add_parser("push"); s.add_argument("workspace"); s.add_argument("--dest"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_push)
    s = sub.add_parser("run"); s.add_argument("workspace"); s.add_argument("--dest")
    s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"초(기본 {DEFAULT_TIMEOUT})")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("exec"); s.add_argument("workspace"); s.add_argument("--cwd", default="~", help="원격 작업 디렉터리(기본 홈)")
    s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"초(기본 {DEFAULT_TIMEOUT})")
    s.set_defaults(fn=cmd_exec)
    s = sub.add_parser("put"); s.add_argument("workspace"); s.add_argument("local"); s.add_argument("remote_dir")
    s.add_argument("--force", action="store_true"); s.set_defaults(fn=cmd_put)
    s = sub.add_parser("pull"); s.add_argument("workspace"); s.add_argument("remote"); s.add_argument("local", nargs="?")
    s.set_defaults(fn=cmd_pull)
    s = sub.add_parser("info"); s.add_argument("workspace"); s.set_defaults(fn=cmd_info)
    # 명령은 첫 `--` 뒤 전부다. argparse 의 REMAINDER 는 옵션과 `--` 가 섞이면 `--` 를 명령에 남긴다.
    argv = sys.argv[1:]
    command = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    a = p.parse_args(argv)
    a.command = command
    a.fn(a)


if __name__ == "__main__":
    main()

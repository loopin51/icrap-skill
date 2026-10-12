#!/usr/bin/env python3
"""ICRAP 워크스페이스에 로컬 코드를 보내고 실행하고 결과를 가져온다. coder CLI 위에서 돈다(표준 라이브러리만).

  ws.py push <워크스페이스> [--dest DIR]                 현재 git 저장소의 파일을 DIR/src 로 보낸다(이전 src 는 지운다)
  ws.py run  <워크스페이스> [--dest DIR] [--timeout S] -- <명령>   DIR/src 에서 명령을 실행하고 출력을 DIR/logs 에도 남긴다
  ws.py pull <워크스페이스> <원격 경로> [로컬 디렉터리]       원격 파일·디렉터리를 가져온다
  ws.py info <워크스페이스>                               파이썬·GPU·디스크·/shared 상태

DIR 기본값은 ~/icrap-run/<로컬 저장소 이름>. 실행은 항상 timeout 으로 감싼다(세션이 끊겨도 프로세스가 남지 않게).
종료 코드는 원격 명령의 것을 그대로 돌려준다(124 = 시간 초과).
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys

MAX_PUSH_BYTES = 200 * 2**20  # 데이터셋까지 실려 가는 것을 막는다. 큰 데이터는 /shared 나 /data 에 둔다.
DEFAULT_TIMEOUT = 540         # Claude Code 의 Bash 도구 한도(10분) 안에서 끝나게 한다.
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


def ssh(ws, script, stdin=None, capture=False):
    # 원격 명령은 문자열 하나로 넘긴다(coder ssh 가 그대로 셸에 준다). 시작 안내 문구는 stderr 로 나온다.
    return subprocess.run([coder(), "ssh", ws, "--", f"bash -c {shlex.quote(ENV_PREFIX + script)}"],
                          stdin=stdin, stdout=subprocess.PIPE if capture else None)


def repo_root():
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def default_dest():
    root = repo_root() or os.getcwd()
    return f"~/icrap-run/{os.path.basename(root)}"


def remote_path(p):
    # ~ 를 원격 셸이 풀도록 따옴표 밖에 둔다.
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
    proc = subprocess.Popen([coder(), "ssh", a.workspace, "--", f"bash -c {shlex.quote(script)}"], stdin=tar.stdout)
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
    remote = subprocess.Popen([coder(), "ssh", a.workspace, "--", f"bash -c {shlex.quote(script)}"], stdout=subprocess.PIPE)
    untar = subprocess.run(["tar", "-xzf", "-", "-C", local], stdin=remote.stdout)
    remote.stdout.close()
    if remote.wait() != 0 or untar.returncode != 0:
        die("가져오기에 실패했습니다(경로를 확인하세요).", 1)
    print(f"{a.workspace}:{a.remote} → {os.path.join(local, base)}")


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
    p = argparse.ArgumentParser(prog="ws", description="ICRAP 워크스페이스에서 로컬 코드 실행")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("push"); s.add_argument("workspace"); s.add_argument("--dest"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_push)
    s = sub.add_parser("run"); s.add_argument("workspace"); s.add_argument("--dest")
    s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"초(기본 {DEFAULT_TIMEOUT})")
    s.set_defaults(fn=cmd_run)
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

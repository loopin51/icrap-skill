#!/usr/bin/env python3
"""ICRAP 공개 API(/api/v1) 클라이언트. 표준 라이브러리만 쓴다(Python 3.8+).

로그인(토큰 인증):
  icrap login          브라우저 로그인. 화면에 나온 코드를 포털 /cli-login 에서 승인하면 읽기 토큰을 받아
                       ~/.config/icrap/token 에 저장한다. 토큰을 복사·붙여 넣을 일이 없다(GitHub·이메일 로그인 모두 된다).
  icrap login --paste  토큰을 화면에 보이지 않게 입력받아 포털에 확인한 뒤 저장한다(파이프로 줘도 된다).
                       쓰기 토큰(관리자가 발급)은 이 방법으로만 넣는다 → ~/.config/icrap/write-token.
                       어느 자리에 둘지는 스코프를 보고 정한다.
  조회는 읽기 토큰을, 잡 제출·취소와 워크스페이스 시작·정지는 쓰기 토큰을 쓴다(없으면 다른 쪽으로 대신한다).

설정(환경 변수):
  ICRAP_URL    포털 주소. 기본 https://icrap.blueodor.xyz
  ICRAP_TOKEN  API 토큰(rp_...). 주면 저장된 토큰 대신 이것 하나만 쓴다.
  (RP_BASE·RP_TOKEN 도 같은 뜻으로 받는다 — docs/api.md 예시와 같은 이름이다.)

종료 코드: 0 성공 · 1 API 오류 · 2 설정·사용법 오류 · 3 잡이 실패로 끝남(wait)

토큰 원문은 어디에도 출력하지 않는다.
"""
import argparse
import getpass
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

DEFAULT_URL = "https://icrap.blueodor.xyz"
TOKEN_DIR = os.path.expanduser("~/.config/icrap")
TOKEN_FILE = os.path.join(TOKEN_DIR, "token")              # 읽기 토큰
WRITE_TOKEN_FILE = os.path.join(TOKEN_DIR, "write-token")  # 쓰기 토큰(read 스코프도 함께 든다)
WRITE_SCOPES = ("jobs:write", "workspaces:write")
# 안내에 실제 설치 위치를 쓴다(프로젝트의 .claude/skills 에 설치했을 수도 있다).
_SELF = os.path.abspath(__file__)
_HOME = os.path.expanduser("~")
LOGIN_CMD = "python3 " + ("~" + _SELF[len(_HOME):] if _SELF.startswith(_HOME + os.sep) else _SELF) + " login"
LOGIN_HINT = f"`{LOGIN_CMD}` 을 실행하고 화면에 나온 코드를 브라우저에서 승인하세요"
WRITE_HINT = ("쓰기 토큰은 관리자만 발급합니다. 관리자에게 필요한 스코프(jobs:write, workspaces:write)로 발급을 요청하고, "
              f"받은 토큰은 터미널에서 `{LOGIN_CMD} --paste` 를 실행해 입력하세요.")
TERMINAL_PHASES = ("succeeded", "failed")
MIN_POLL_SECONDS = 30  # 포털이 이미 5초마다 수집한다. 외부 폴링은 30초 이상(docs/api.md "폴링").

PHASE_KO = {
    "queued": "줄 서는 중(쿼터 대기)",
    "requeued": "선점되어 다시 줄 섬",
    "waiting_node": "자리 기다리는 중(노드 대기)",
    "preparing": "준비 중(코드·이미지 받는 중)",
    "running": "실행 중",
    "succeeded": "완료",
    "failed": "실패",
    "unknown": "알 수 없음",
}
FAILURE_KO = {
    "oom": "메모리 부족",
    "deadline": "시간 초과(72시간)",
    "clone": "코드 받기 실패",
    "exit": "비정상 종료",
    "evicted": "퇴출됨",
}


class ApiError(Exception):
    def __init__(self, status, code, message, body=None):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message, self.body = status, code, message, body or {}


def die(msg, code=2):
    print(f"icrap: {msg}", file=sys.stderr)
    sys.exit(code)


def base_url():
    return (os.environ.get("ICRAP_URL") or os.environ.get("RP_BASE") or DEFAULT_URL).rstrip("/")


def env_token():
    return os.environ.get("ICRAP_TOKEN") or os.environ.get("RP_TOKEN")


def file_token(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.readline().strip() or None


def token(write=False):
    """조회는 읽기 토큰, 쓰기는 쓰기 토큰을 먼저 쓴다. 쓰기 토큰이 없으면 읽기 토큰으로 보내고 서버의 insufficient_scope 를 안내로 바꾼다."""
    t = env_token()
    if not t:
        r, w = file_token(TOKEN_FILE), file_token(WRITE_TOKEN_FILE)
        t = (w or r) if write else (r or w)
    if not t:
        die(f"로그인되어 있지 않습니다. {LOGIN_HINT}.")
    if not t.startswith("rp_"):
        die("토큰 형식이 아닙니다(rp_ 로 시작해야 합니다).")
    return t


def call(method, path, body=None, tok=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url() + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {tok or token(write=method != 'GET')}")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.status, json.loads(res.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            # 문서가 약속하지 않은 경로(Next.js 기본 500 등). 버그로 보고한다.
            raise ApiError(e.code, "unexpected_response", raw[:300].decode("utf-8", "replace"))
        err = (parsed or {}).get("error") or {}
        raise ApiError(e.code, err.get("code", "unknown"), err.get("message", ""), parsed)
    except urllib.error.URLError as e:
        die(f"{base_url()} 에 닿지 않습니다: {e.reason}. ICRAP_URL 을 바꿨다면 기본값({DEFAULT_URL})으로 되돌려 보세요.", 1)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def gib(n):
    return "?" if n is None else f"{n / 2**30:.1f}Gi"


def fmt_job(j):
    phase = PHASE_KO.get(j["phase"], j["phase"])
    if j.get("failure"):
        phase += f" · {FAILURE_KO.get(j['failure'], j['failure'])}"
    qp = j.get("queuePosition")
    if qp:
        phase += f" · 대기 {qp['position'] + 1}번째/{qp['pending']}개"
    gpu = f"GPU {j['gpuCount']}" + (f"({j['gpuClass']})" if j.get("gpuClass") else "")
    line = f"{j['team']}/{j['name']}  {phase}  {gpu}  {j['imageId']}  ref={j.get('ref') or '(기본)'}"
    if j.get("reason"):
        line += f"\n    사유: {j['reason']}"
    return line


# ---------- 로그인 ----------

def is_write(scopes):
    return any(s in scopes for s in WRITE_SCOPES)


def save_token(path, t):
    os.makedirs(TOKEN_DIR, mode=0o700, exist_ok=True)
    os.chmod(TOKEN_DIR, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(t + "\n")
    os.chmod(path, 0o600)


def describe(me, label):
    u, t = me["user"], me["token"]
    line = f"{label}: {u['email']} · 토큰 '{t['name']}' · 스코프 {','.join(t['scopes'])} · {t['daysRemaining']}일 남음({t['expiresAt'][:10]})"
    if t["daysRemaining"] <= 14:
        line += "\n  ⚠️ 곧 만료됩니다. " + ("관리자에게 재발급을 요청하세요." if is_write(t["scopes"]) else f"{LOGIN_HINT}(같은 컴퓨터면 이전 토큰이 교체됩니다).")
    return line


def store_token(t, me):
    """확인을 마친 토큰을 스코프에 맞는 자리에 저장하고 무엇을 할 수 있는지 알린다. 원문은 출력하지 않는다."""
    write = is_write(me["token"]["scopes"])
    path = WRITE_TOKEN_FILE if write else TOKEN_FILE
    other_path = TOKEN_FILE if write else WRITE_TOKEN_FILE
    other = file_token(other_path)
    if other:
        try:
            _, other_me = call("GET", "/api/v1/me", tok=other)
            if other_me["user"]["email"] != me["user"]["email"]:
                print(f"⚠️ 저장된 {'읽기' if write else '쓰기'} 토큰은 다른 계정({other_me['user']['email']})의 것입니다. "
                      f"`icrap logout --{'read' if write else 'write'}` 로 지우세요.", file=sys.stderr)
        except ApiError:
            pass  # 만료·폐기된 다른 쪽 토큰은 me 가 알려 준다.
    save_token(path, t)
    print(describe(me, "쓰기 토큰 저장" if write else "읽기 토큰 저장"))
    print(f"  위치: {path}")
    if write:
        print("  잡 제출·취소, 워크스페이스 시작·정지에 이 토큰을 씁니다." +
              ("" if file_token(TOKEN_FILE) else " 읽기 토큰이 따로 없으므로 조회에도 씁니다."))
    else:
        print("  조회(클러스터·잡·로그·워크스페이스 목록)에 이 토큰을 씁니다. 잡 제출 같은 쓰기 작업은 이 토큰으로 할 수 없습니다.")
        if not file_token(WRITE_TOKEN_FILE):
            print("  " + WRITE_HINT)
    if env_token():
        print("⚠️ ICRAP_TOKEN 환경 변수가 설정되어 있어 저장한 토큰 대신 그것을 씁니다.", file=sys.stderr)


def cmd_login(a):
    if a.paste:
        return login_paste()
    return login_browser(a)


def login_paste():
    if sys.stdin.isatty():
        try:
            raw = getpass.getpass("ICRAP API 토큰(rp_..., 입력은 화면에 보이지 않습니다): ")
        except (EOFError, KeyboardInterrupt):
            die("입력을 취소했습니다.")
    else:
        raw = sys.stdin.readline()
    t = raw.strip()
    if not t:
        die(f"토큰이 입력되지 않았습니다. 읽기 토큰이면 `{LOGIN_CMD}`(브라우저 로그인)을 쓰세요.")
    if not t.startswith("rp_"):
        die("토큰 형식이 아닙니다(rp_ 로 시작해야 합니다). 저장하지 않았습니다.")
    try:
        _, me = call("GET", "/api/v1/me", tok=t)
    except ApiError as e:
        die(f"포털이 이 토큰을 받지 않았습니다({e.code}). 폐기·만료되지 않았는지 포털 → 계정 → API 토큰에서 확인하세요. 저장하지 않았습니다.", 1)
    store_token(t, me)


def public_post(path, body):
    """토큰 없이 부르는 터미널 로그인 엔드포인트. (HTTP 상태, 본문)을 돌려주고 4xx·5xx 는 ApiError 로 올린다."""
    req = urllib.request.Request(base_url() + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.loads(res.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            err = (json.loads(raw) or {}).get("error") or {}
        except ValueError:
            raise ApiError(e.code, "unexpected_response", raw[:300].decode("utf-8", "replace"))
        raise ApiError(e.code, err.get("code", "unknown"), err.get("message", ""))
    except urllib.error.URLError as e:
        die(f"{base_url()} 에 닿지 않습니다: {e.reason}.", 1)


def can_open_browser():
    # 원격(SSH) 세션이나 화면이 없는 리눅스에서는 열지 않는다. webbrowser 가 터미널용 브라우저(lynx 등)를
    # 띄워 이 터미널을 가로챌 수 있다.
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return sys.platform in ("darwin", "win32")


LOGIN_ERRORS = {
    "access_denied": "포털에서 이 로그인 요청을 거부했습니다.",
    "account_inactive": "이 계정은 정지됐거나 사용 기간이 끝났습니다. 관리자에게 문의하세요.",
    "token_limit_reached": "활성 읽기 토큰이 이미 2개입니다. 포털 → 계정 → API 토큰에서 하나를 폐기한 뒤 다시 로그인하세요.",
    "expired_token": "코드가 만료됐습니다(10분). 다시 로그인하세요.",
    "too_many_pending": "지금 대기 중인 로그인 요청이 너무 많습니다. 몇 분 뒤 다시 시도하세요.",
}


def login_browser(a):
    client = f"{getpass.getuser()}@{socket.gethostname()}"
    try:
        _, start = public_post("/api/cli-login/start", {"client": client})
    except ApiError as e:
        die(LOGIN_ERRORS.get(e.code) or f"로그인을 시작하지 못했습니다({e.status} {e.code}).", 1)
    url = base_url() + "/cli-login"
    interval = max(int(start.get("interval", 5)), 5)
    deadline = time.time() + int(start.get("expiresIn", 600))
    print("브라우저에서 아래 주소를 열고, 포털에 로그인한 뒤 코드를 입력해 승인하세요.")
    print(f"  주소: {url}")
    print(f"  코드: {start['userCode']}   (10분 안에, 이 컴퓨터: {client})")
    print("직접 실행한 로그인이 아니면 승인하지 마세요. 기다리는 중… (Ctrl+C 로 취소)", flush=True)
    if not a.no_browser and can_open_browser():
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 — 열지 못해도 주소를 이미 보여 줬다
            pass
    try:
        while time.time() < deadline:
            time.sleep(interval)
            try:
                status, res = public_post("/api/cli-login/poll", {"deviceCode": start["deviceCode"]})
            except ApiError as e:
                if e.code == "slow_down":
                    interval += 5
                    continue
                if e.status >= 500:
                    continue  # 잠깐의 장애는 만료 전까지 다시 묻는다
                die(LOGIN_ERRORS.get(e.code) or f"로그인하지 못했습니다({e.status} {e.code}).", 1)
            if status == 200 and res.get("status") == "approved":
                t = res["token"]
                try:
                    _, me = call("GET", "/api/v1/me", tok=t)
                except ApiError as e:
                    die(f"받은 토큰을 포털이 확인하지 못했습니다({e.code}). 다시 로그인하세요.", 1)
                print("승인됐습니다.")
                store_token(t, me)
                return
        die(LOGIN_ERRORS["expired_token"], 1)
    except KeyboardInterrupt:
        die("로그인을 취소했습니다.")


def cmd_logout(a):
    targets = {"read": [TOKEN_FILE], "write": [WRITE_TOKEN_FILE]}.get(a.which, [TOKEN_FILE, WRITE_TOKEN_FILE])
    removed = []
    for p in targets:
        if os.path.exists(p):
            os.remove(p)
            removed.append(p)
    print("지웠습니다: " + ", ".join(removed) if removed else "지울 토큰이 없습니다.")
    if removed:
        print("이 컴퓨터에서만 지웠습니다. 토큰 자체를 무효로 하려면 포털 → 계정 → API 토큰에서 폐기하세요.")


# ---------- 읽기 ----------

def cmd_me(a):
    env = env_token()
    slots = [("ICRAP_TOKEN 환경 변수", env)] if env else [
        ("읽기 토큰", file_token(TOKEN_FILE)), ("쓰기 토큰", file_token(WRITE_TOKEN_FILE))]
    slots = [(label, t) for label, t in slots if t]
    if not slots:
        token()  # 로그인 안내를 내고 끝난다.
    results, by_token = [], {}
    for label, t in slots:
        try:
            _, me = call("GET", "/api/v1/me", tok=t)
            results.append((label, me, None))
            by_token[t] = me["token"]["scopes"]
        except ApiError as e:
            results.append((label, None, e))
    # 실제로 쓰일 토큰 기준이다: 조회는 읽기 토큰이 무효면 쓰기 토큰으로 넘어가지 않는다.
    read_scopes = by_token.get(token(write=False), [])
    write_scopes = by_token.get(token(write=True), [])
    if a.json:
        return out([{"slot": label, **(me or {"error": {"code": e.code, "message": e.message}})} for label, me, e in results])
    first = next((me for _, me, _ in results if me), None)
    if first:
        print(f"{first['user']['email']} ({first['user']['role']}) · {base_url()}")
    for label, me, e in results:
        if me:
            print(describe(me, label))
        else:
            print(f"{label}: 쓸 수 없음({e.code}). " + ("관리자에게 재발급을 요청하세요." if "쓰기" in label else f"{LOGIN_HINT}."))
    can = ["조회"] if "read" in read_scopes else []
    can += ["잡 제출·취소"] if "jobs:write" in write_scopes else []
    can += ["워크스페이스 시작·정지"] if "workspaces:write" in write_scopes else []
    print("할 수 있는 일: " + (", ".join(can) or "없음"))
    if not is_write(write_scopes):
        print("쓰기 작업(잡 제출·취소, 워크스페이스 시작·정지)을 하려면: " + WRITE_HINT)
    if not can:
        sys.exit(1)


def cmd_cluster(a):
    _, c = call("GET", "/api/v1/cluster")
    if a.json:
        return out(c)
    print(f"수집 시각 {c['collectedAt']}" + (f" · ⚠️ 일부 수집 실패: {c['degraded']}" if c["degraded"] else ""))
    print("노드:")
    for n in c["nodes"]:
        g = n["gpuCount"]
        gpu = f"GPU {g['requested']}/{g['allocatable']} 예약" if g["allocatable"] else "GPU 없음"
        cpu, mem = n["cpuCores"], n["memoryBytes"]
        used = "측정 불가" if cpu["used"] is None else f"{cpu['used']:.1f}"
        print(f"  {n['name']:<24} {n['gpuClass'] or 'none':<12} {gpu:<16} "
              f"CPU 예약 {cpu['requested']:.1f}/{cpu['allocatable']:.0f}(사용 {used})  "
              f"메모리 예약 {gib(mem['requested'])}/{gib(mem['allocatable'])}")
    if c["queues"]:
        print("팀 큐:")
        for q in c["queues"]:
            gpus = [r for r in q["resources"] if r["resource"] == "nvidia.com/gpu"]
            g = ", ".join(f"{r['flavor']} {r['used']:g}/{r['nominal']:g}" + (f"(+빌림 {r['borrowed']:g})" if r["borrowed"] else "")
                          for r in gpus) or "GPU 쿼터 없음"
            print(f"  {q['name']:<12} 대기 {q['pendingWorkloads']}개 · GPU {g}")
    busy = [x for x in c["consumers"] if x["gpuCount"]]
    if busy:
        print("GPU 를 쥔 워크로드:")
        for x in busy:
            note = " · 잡·워크스페이스가 요청하면 회수됨" if x["kind"] == "serving" else ""
            print(f"  {x['kind']:<9} {x['name']:<40} GPU {x['gpuCount']} · {x['status']} · {x['owner'] or '-'}{note}")


def cmd_templates(a):
    _, body = call("GET", "/api/v1/templates")
    if a.json:
        return out(body)
    for t in body["templates"]:
        s = t["spec"]
        if not s:
            print(f"  {t['name']:<18} {t['displayName']} (스펙을 읽지 못함)")
            continue
        gpu = f"GPU {s['gpu']}×{s['gpuClass']}" if s["gpu"] else "CPU"
        print(f"  {t['name']:<18} {gpu:<20} CPU {s['cpuRequest']}~{s['cpuLimit']} · 메모리 {s['memoryRequest']}~{s['memoryLimit']} "
              f"· 홈 {s['disk']}" + (f" · /data {s['dataDisk']}" if s.get("dataDisk") else "")
              + (f"  [{t['displayName']}]" if t.get("displayName") else ""))


def list_workspaces():
    return call("GET", "/api/v1/workspaces")[1]["workspaces"]


def cmd_workspaces(a):
    ws = list_workspaces()
    if a.json:
        return out({"workspaces": ws})
    if not ws:
        print("워크스페이스가 없습니다(만들기는 포털에서 합니다).")
    for w in ws:
        print(f"  {w['name']:<24} {w['status']:<10} {w['templateName']:<18} id={w['id']}")


def list_jobs():
    _, body = call("GET", "/api/v1/jobs")
    if body.get("degraded"):
        print(f"⚠️ 일부 수집 실패: {body['degraded']}", file=sys.stderr)
    return body["jobs"]


def cmd_jobs(a):
    jobs = list_jobs()
    if a.name:
        jobs = [j for j in jobs if j["name"] == a.name]
    if a.json:
        return out({"jobs": jobs})
    if not jobs:
        print("잡이 없습니다." if not a.name else f"'{a.name}' 잡이 없습니다(끝난 잡은 7일 뒤 사라집니다).")
    for j in jobs:
        print(fmt_job(j))


# ---------- 잡 쓰기 ----------

def cmd_submit(a):
    body = {"name": a.name, "repo": a.repo, "command": a.command, "gpus": a.gpus, "imageId": a.image, "vram": a.vram}
    if a.ref:
        body["ref"] = a.ref
    try:
        status, res = call("POST", "/api/v1/jobs", body)
    except ApiError as e:
        if e.code == "job_exists":
            job = e.body.get("job")
            if job:
                # 같은 입력이면 재시도가 이미 성공한 것이다. 입력이 다르면 다른 실험을 같은 이름으로 낸 것이다.
                if job["command"] != a.command or (a.ref and job.get("ref") != a.ref):
                    print(f"같은 이름의 내 잡이 있는데 명령이나 ref 가 다릅니다. 새 실험이면 이름을 바꾸세요:\n{fmt_job(job)}",
                          file=sys.stderr)
                    sys.exit(1)
                print(f"같은 이름의 내 잡이 이미 있습니다(재제출하지 않음):\n{fmt_job(job)}")
                return
            die(f"'{a.name}' 은 같은 팀의 다른 사람이 쓰는 이름입니다. 다른 이름으로 제출하세요.", 1)
        if e.code == "submit_unknown":
            # 만들어졌는지 모른다. 확인 없이 재시도하지 않는다(docs/api.md).
            print("클러스터가 제출을 확인하지 않았습니다(submit_unknown). 목록에서 확인합니다…", file=sys.stderr)
            time.sleep(5)
            found = [j for j in list_jobs() if j["name"] == a.name]
            if found:
                print(f"제출되어 있습니다:\n{fmt_job(found[0])}")
                return
            die("목록에 없습니다. 같은 이름으로 한 번 다시 제출해도 됩니다(중복되면 job_exists 로 막힙니다).", 1)
        raise
    job = res.get("job")
    print(f"제출됨: {res['team']}/{res['name']}")
    if job:
        print(fmt_job(job))
    print(f"결과물 위치: /shared/runs/<내 이름>/{res['name']}/ (잡 안에서는 $RUN_DIR)")


def find_job(name, team=None):
    found = [j for j in list_jobs() if j["name"] == name and (team is None or j["team"] == team)]
    if not found:
        return None
    if len(found) > 1:
        die(f"'{name}' 잡이 여러 팀에 있습니다: {[j['team'] for j in found]}. --team 으로 고르세요.")
    return found[0]


def cmd_cancel(a):
    team = a.team
    if not team:
        j = find_job(a.name)
        if not j:
            print(f"'{a.name}' 잡이 목록에 없습니다(이미 끝나 사라졌을 수 있습니다).")
            return
        team = j["team"]
    _, res = call("DELETE", f"/api/v1/jobs/{urllib.parse.quote(team)}/{urllib.parse.quote(a.name)}")
    print("취소됨" if res.get("deleted") else "지울 잡이 없습니다(이미 끝나 사라졌거나 내 잡이 아닙니다).")


def cmd_wait(a):
    interval = max(a.interval, MIN_POLL_SECONDS)
    deadline = time.time() + a.timeout if a.timeout else None
    last = None
    while True:
        j = find_job(a.name, a.team)
        if not j:
            die(f"'{a.name}' 잡이 목록에 없습니다.", 1)
        line = fmt_job(j)
        if line != last:
            print(time.strftime("%H:%M:%S"), line, flush=True)
            last = line
        if j["phase"] in TERMINAL_PHASES:
            sys.exit(0 if j["phase"] == "succeeded" else 3)
        if deadline and time.time() + interval > deadline:
            print(f"시간 제한({a.timeout}s)에 닿아 기다리기를 멈춥니다. 잡은 계속 돕니다.")
            return
        time.sleep(interval)


def cmd_logs(a):
    team = a.team
    if not team:
        j = find_job(a.name)
        if not j:
            die(f"'{a.name}' 잡이 목록에 없습니다(끝난 잡은 7일 뒤 사라집니다).", 1)
        team = j["team"]
    q = urllib.parse.urlencode({"container": a.container, "tail": a.tail})
    _, r = call("GET", f"/api/v1/jobs/{urllib.parse.quote(team)}/{urllib.parse.quote(a.name)}/logs?{q}")
    if a.json:
        return out(r)
    if r["lines"] is None:
        why = {"no_pod": "파드가 아직 없습니다(줄 서는 중이거나, 끝난 지 오래돼 지워졌습니다)",
               "container_not_started": f"{a.container} 컨테이너가 아직 시작 전입니다"}.get(r["reason"], r["reason"])
        print(f"로그 없음: {why}", file=sys.stderr)
        return
    if not r["lines"]:
        print(f"({a.container} 컨테이너가 아무것도 출력하지 않았습니다)", file=sys.stderr)
        return
    if r["truncated"]:
        print(f"(응답 한도 때문에 마지막 {len(r['lines'])}줄만 왔습니다)", file=sys.stderr)
    for line in r["lines"]:
        print(line)


# ---------- 워크스페이스 쓰기 ----------

def resolve_ws(ref):
    ws = list_workspaces()
    for w in ws:
        if ref in (w["id"], w["name"]):
            return w
    die(f"'{ref}' 워크스페이스가 없습니다. 내 워크스페이스: {[w['name'] for w in ws]}", 1)


def ws_transition(a, action):
    w = resolve_ws(a.workspace)
    _, res = call("POST", f"/api/v1/workspaces/{w['id']}/{action}")
    verb = "시작" if action == "start" else "정지"
    if res.get("changed"):
        print(f"{w['name']}: {verb} 요청됨(이전 상태 {res['previousStatus']}). "
              f"{'실행까지 보통 30초' if action == 'start' else '멈추기까지 보통 10초'} 안팎 걸립니다.")
    else:
        print(f"{w['name']}: 이미 {res['previousStatus']} 상태라 바꾸지 않았습니다.")


# ---------- 진입점 ----------

def main():
    p = argparse.ArgumentParser(prog="icrap", description="ICRAP API 클라이언트")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="응답 원문(JSON)을 출력한다")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, **k):
        return sub.add_parser(name, parents=[common], **k)

    s = add("login", help="브라우저에서 승인해 읽기 토큰을 받는다(--paste: 토큰을 직접 입력, 쓰기 토큰은 이쪽)")
    s.add_argument("--paste", action="store_true", help="토큰을 입력받아 확인하고 저장한다(읽기·쓰기 자리는 스코프로 정한다)")
    s.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않는다(주소만 보여 준다)")
    s.set_defaults(fn=cmd_login)
    s = add("logout", help="저장한 토큰을 이 컴퓨터에서 지운다")
    s.add_argument("--read", dest="which", action="store_const", const="read", help="읽기 토큰만")
    s.add_argument("--write", dest="which", action="store_const", const="write", help="쓰기 토큰만")
    s.set_defaults(fn=cmd_logout, which="all")
    add("me", help="로그인한 계정, 토큰별 스코프·만료, 할 수 있는 일").set_defaults(fn=cmd_me)
    add("cluster", help="노드·팀 큐·GPU 점유 현황").set_defaults(fn=cmd_cluster)
    add("templates", help="워크스페이스 템플릿과 스펙").set_defaults(fn=cmd_templates)
    add("workspaces", help="내 워크스페이스 목록").set_defaults(fn=cmd_workspaces)
    s = add("jobs", help="내 배치 잡 목록")
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_jobs)

    s = add("submit", help="배치 잡 제출(jobs:write 필요)")
    s.add_argument("--name", required=True, help="소문자·숫자·하이픈 40자 이내, 팀 안에서 유일")
    s.add_argument("--repo", required=True, help="공개 https git 저장소")
    s.add_argument("--ref", help="브랜치·태그·커밋 SHA(생략하면 기본 브랜치)")
    s.add_argument("--command", required=True, help="저장소 루트에서 uv 가상환경을 켠 채 실행할 명령")
    s.add_argument("--gpus", type=int, default=1, help="GPU 장수 0~8(기본 1, CPU 잡은 0)")
    s.add_argument("--image", default=None, help="pytorch-2.14-cu130(GPU 기본) · pytorch-2.11-cu128 · python-3.12-cpu(CPU 기본)")
    s.add_argument("--vram", default="any", choices=["any", "24g"])
    s.set_defaults(fn=cmd_submit)

    s = add("cancel", help="내 잡 취소(jobs:write 필요)")
    s.add_argument("name")
    s.add_argument("--team")
    s.set_defaults(fn=cmd_cancel)

    s = add("wait", help="잡이 끝날 때까지 상태 변화를 출력한다")
    s.add_argument("name")
    s.add_argument("--team")
    s.add_argument("--interval", type=int, default=60, help=f"폴링 간격(초, 최소 {MIN_POLL_SECONDS})")
    s.add_argument("--timeout", type=int, default=0, help="이 시간(초)이 지나면 기다리기만 멈춘다(0 = 끝날 때까지)")
    s.set_defaults(fn=cmd_wait)

    s = add("logs", help="내 잡의 로그 마지막 N줄(read 로 충분)")
    s.add_argument("name")
    s.add_argument("--team")
    s.add_argument("--container", default="main", choices=["main", "uv-install", "git-clone"])
    s.add_argument("--tail", type=int, default=200, help="마지막 몇 줄(1~5000, 기본 200)")
    s.set_defaults(fn=cmd_logs)

    for action in ("start", "stop"):
        s = add(f"ws-{action}", help=f"내 워크스페이스 {'시작' if action == 'start' else '정지'}(workspaces:write 필요)")
        s.add_argument("workspace", help="이름 또는 id")
        s.set_defaults(fn=lambda a, act=action: ws_transition(a, act))

    a = p.parse_args()
    if a.cmd == "submit" and a.image is None:
        a.image = "python-3.12-cpu" if a.gpus == 0 else "pytorch-2.14-cu130"
    try:
        a.fn(a)
    except ApiError as e:
        print(json.dumps({"status": e.status, "code": e.code, "message": e.message}, ensure_ascii=False), file=sys.stderr)
        if e.code == "insufficient_scope":
            print(f"icrap: 이 작업에는 쓰기 토큰이 필요합니다. {WRITE_HINT}", file=sys.stderr)
        elif e.code in ("invalid_token", "token_expired"):
            print(f"icrap: 토큰이 폐기됐거나 만료됐습니다. `icrap me` 로 어느 토큰인지 확인하세요. 읽기 토큰이면 {LOGIN_HINT}.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

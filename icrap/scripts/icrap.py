#!/usr/bin/env python3
"""ICRAP 공개 API(/api/v1) 클라이언트. 표준 라이브러리만 쓴다(Python 3.8+).

설정(환경 변수):
  ICRAP_URL    포털 주소. 기본 https://icrap.blueodor.xyz
  ICRAP_TOKEN  API 토큰(rp_...). 없으면 ~/.config/icrap/token 파일의 첫 줄을 읽는다.
  (RP_BASE·RP_TOKEN 도 같은 뜻으로 받는다 — docs/api.md 예시와 같은 이름이다.)

종료 코드: 0 성공 · 1 API 오류 · 2 설정·사용법 오류 · 3 잡이 실패로 끝남(wait)

토큰 원문은 어디에도 출력하지 않는다.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://icrap.blueodor.xyz"
TOKEN_FILE = os.path.expanduser("~/.config/icrap/token")
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


def token():
    t = os.environ.get("ICRAP_TOKEN") or os.environ.get("RP_TOKEN")
    if not t and os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as f:
            t = f.readline().strip()
    if not t:
        die(f"토큰이 없습니다. ICRAP_TOKEN 을 설정하거나 {TOKEN_FILE} 에 넣으세요(포털 → 계정 → API 토큰).")
    if not t.startswith("rp_"):
        die("토큰 형식이 아닙니다(rp_ 로 시작해야 합니다).")
    return t


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url() + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token()}")
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


# ---------- 읽기 ----------

def cmd_me(a):
    _, body = call("GET", "/api/v1/me")
    if a.json:
        return out(body)
    u, t = body["user"], body["token"]
    print(f"{u['email']} ({u['role']})")
    print(f"토큰 '{t['name']}' 스코프 {','.join(t['scopes'])} · {t['daysRemaining']}일 남음({t['expiresAt'][:10]})")
    if t["daysRemaining"] <= 14:
        print("⚠️ 토큰이 곧 만료됩니다. 포털 → 계정 → API 토큰에서 새로 발급하세요.")


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

    add("me", help="내 계정과 토큰 스코프·만료").set_defaults(fn=cmd_me)
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
        sys.exit(1)


if __name__ == "__main__":
    main()

# ICRAP 참고 자료

SKILL.md 에서 필요할 때만 읽는다. 원본은 `icrap <명령> --help` 와 포털 `문서` 의 사용자 매뉴얼·배치 잡 안내·터미널 접속 안내다.

## 명령 전체

| 명령 | 하는 일 | 필요한 것 |
|---|---|---|
| `icrap login [--no-browser]` | 브라우저 승인으로 읽기 토큰(90일). 같은 컴퓨터에서 다시 하면 그 컴퓨터의 이전 토큰만 교체된다. `--no-browser` 는 브라우저를 열지 않는다 | — |
| `icrap login --ssh` | 읽기 토큰 + Coder 세션(워크스페이스 셸 권한, 7일·쓸 때마다 연장) | — |
| `icrap login --paste` | 관리자가 준 쓰기 토큰 입력. **사용자가 자기 터미널에서** | — |
| `icrap logout [--read\|--write\|--ssh]` | 이 컴퓨터에서 지운다. `--ssh` 는 Coder 세션을 서버에서도 폐기 | — |
| `icrap me` | 계정, 토큰별 스코프·만료, SSH 세션, 할 수 있는 일 | 토큰 |
| `icrap update` / `icrap version [--local]` | 최신으로 교체 / CLI·포털 버전(`--local` 은 포털에 묻지 않는다) | — |
| `icrap cluster` / `icrap templates` | 클러스터 현황 / 워크스페이스 템플릿 | 읽기 |
| `icrap job list [이름]` / `show <잡>` | 내 잡 | 읽기 |
| `icrap job logs <잡> [--tail N] [--container main\|uv-install\|git-clone] [--team]` | 로그 마지막 N줄(기본 200) | 읽기 |
| `icrap job wait <잡> [--timeout 초] [--interval 초] [--team]` | 상태 변화 출력. 0 완료·시간 제한, 3 실패 | 읽기 |
| `icrap job submit --name --repo --ref --command [--gpus] [--image] [--vram any\|24g]` | 제출 | `jobs:write` |
| `icrap job cancel <잡> [--team]` | 취소. `--team` 은 같은 이름이 여러 팀에 있을 때 | `jobs:write` |
| `icrap ws list` | 내 워크스페이스 | 읽기 |
| `icrap ws start <ws>` / `stop <ws>` | 시작·정지. 이미 그 상태면 그대로 성공 | `workspaces:write` |
| `icrap ws check` / `info <ws>` | coder·세션·워크스페이스 상태 / 원격 파이썬·torch·GPU·디스크 | SSH 세션 |
| `icrap ws push <ws> [--dest] [--force]` | 현재 git 저장소를 `~/icrap-run/<저장소>/src` 로(200MiB 상한) | SSH 세션 |
| `icrap ws run <ws> [--timeout] -- <명령>` | `src` 에서 실행, 로그를 `~/icrap-run/<저장소>/logs/` 에도 | SSH 세션 |
| `icrap ws exec <ws> [--cwd] [--timeout] -- <명령>` | 아무 디렉터리(기본 홈)에서 실행 | SSH 세션 |
| `icrap ws put <ws> <로컬> <원격 디렉터리> [--force]` / `pull <ws> <원격> [로컬 디렉터리]` | 파일·디렉터리 하나 보내기(200MiB 상한, `--force` 로 넘김)·가져오기 | SSH 세션 |
| `icrap ws ssh <ws>` | 대화형 접속(사용자 터미널용) | SSH 세션 |
| `icrap ws config-ssh` | `ssh <ws>.coder`·scp·VS Code Remote-SSH 설정 | SSH 세션 |

SSH 명령은 꺼진 워크스페이스를 켜지 않는다(exit 1 과 `icrap ws start` 안내). `ws run`·`exec`·`info`·`ssh` 의 종료 코드는 원격 명령의 것이다.
공통: `--json` 은 응답 원문. 환경 변수 `ICRAP_URL`(포털 주소, 기본 `https://icrap.blueodor.xyz`), `ICRAP_TOKEN`(CI 용, 저장된 토큰 대신),
`ICRAP_CODER_BIN`(받아 둔 coder 대신 쓸 바이너리).

## 잡 환경과 자원

잡은 항상 uv 가상환경 `/workspace/.venv` 를 켠 채 `--command` 를 저장소 루트에서 실행한다.

| 저장소 | 잡이 하는 일 | 언제 고르나 |
|---|---|---|
| `pyproject.toml`(`[project]`) + `uv.lock` | `uv sync --frozen` | 재현성이 필요할 때. **torch 도 의존성에 넣어야 한다** |
| `pyproject.toml`(`[project]`) 만 | `uv sync` | 버전 고정이 필요 없을 때 |
| 그 밖 | 이미지의 파이썬(PyTorch 포함) | 짧은 실험. 설치 시간이 없다 |

- torch 를 넣은 uv 프로젝트는 첫 잡에 약 9분, 같은 팀 다음 잡도 약 2분을 설치에 쓴다. 짧은 실험이면 이미지의 torch 를 쓴다.
- 몇 개만 더 필요하면: `uv pip install -r requirements.txt && python train.py`(requirements 에 torch 를 넣지 않는다).
- `--gpus`: 코드가 실제로 쓰는 장수. `torchrun --nproc_per_node=2` 일 때만 2. 2장 잡은 RTX 5080 노드에서만 돌고 오래 기다릴 수 있다.
- `--vram 24g`: 16GB 에서 OOM 이 나는 모델에만(A5000 만 쓰게 된다).
- CPU·메모리는 플랫폼이 정한다: GPU 1장 8코어·24GiB(`24g` 면 32GiB), 5080 2장 20코어·48GiB, CPU 잡(`--gpus 0`) 4코어·16GiB.
- 이미지: `pytorch-2.14-cu130`(GPU 기본), `pytorch-2.11-cu128`, `python-3.12-cpu`(`--gpus 0` 기본).
- 최대 실행 72시간(대기 제외), `/workspace` 잡당 200GiB. 팀마다 동시에 도는 잡은 2개까지다.

## 잡 상태와 실패 사유

`icrap job show <잡> --json` 의 `phase`:

| phase | 뜻 | 할 일 |
|---|---|---|
| `queued` | 팀 쿼터를 기다린다(`queuePosition` 0부터) | 기다린다. 다시 제출하지 않는다 |
| `requeued` | 선점되어 다시 줄 섰다 | 기다린다. 다시 시작되면 처음부터 돈다 |
| `waiting_node` | 쿼터는 받았고 노드 자리를 기다린다 | 기다린다 |
| `preparing` | clone, 이미지(3~4GB), uv 설치 | 몇 분, torch 설치면 10분 가까이 |
| `running` · `succeeded` | | |
| `failed` | `failure` 에 사유 | 아래 표 |
| `unknown` | 포털이 상태를 못 읽었다 | 잠시 뒤 다시 본다 |

| failure | 원인 | 볼 로그 · 고칠 것 |
|---|---|---|
| `clone` | URL·ref 오류, 비공개 저장소, push 안 됨 | `--container git-clone`. 공개 여부·SHA 확인 |
| `exit`(사유 `uv 준비 실패`) | `uv.lock` 이 `pyproject.toml` 과 어긋남, 해석 실패 | `--container uv-install` |
| `exit`(사유 `종료 코드 N`) | 명령이 실패 | `main`(기본). 맨 아래 예외와 그 직전 내 코드 줄 |
| `oom` | 배정 메모리 초과 | 배치 크기·DataLoader worker 수를 줄인다 |
| `deadline` | 72시간 초과 | 체크포인트에서 이어 가는 잡으로 나눈다 |
| `evicted` | 대개 `/workspace` 200GiB 초과 | 큰 파일은 `$RUN_DIR`, 큰 데이터는 `/shared` 에서 직접 |

모르는 failure 는 실패로 다룬다. 환경 단계에서 실패하면 `main` 로그는 "컨테이너가 아직 시작 전" 이다. 끝난 잡은 7일 뒤 목록에서 사라지고 결과물은 `$RUN_DIR` 에 남는다.

## 잡 안의 경로

| 경로 / 변수 | 용도 |
|---|---|
| `/workspace` | clone 한 코드와 임시 공간(NVMe, 끝나거나 선점되면 사라진다) |
| `$RUN_DIR` = `/shared/runs/<내 이름>/<잡 이름>/` | 결과물. `commit.txt` 에 실행한 커밋 |
| `/shared/datasets/` | 팀 공용 데이터셋 |
| `$HF_HOME` · `$UV_CACHE_DIR` · `$PIP_CACHE_DIR` | 팀 공유 캐시 |

- `/shared` 는 HDD 다. 큰 파일 순차 읽기(약 200MiB/s)는 빠르고 작은 파일 수십만 개는 느리다. tar·parquet·webdataset 으로 묶거나
  `cp -r /shared/datasets/<name> /workspace/data && python train.py --data /workspace/data` 로 NVMe 에 복사한다(100GiB 약 8분).
- 큰 공개 데이터셋은 내려받기 잡으로: `--gpus 0 --command "pip install -q huggingface_hub && huggingface-cli download <org>/<dataset> --repo-type dataset --local-dir /shared/datasets/<name>"`.

## 선점에 견디는 체크포인트

```python
import os, torch
ckpt = os.path.join(os.environ.get("RUN_DIR", "runs/local"), "checkpoint.pt")
start_epoch = 0
if os.path.exists(ckpt):
    state = torch.load(ckpt)
    model.load_state_dict(state["model"]); optimizer.load_state_dict(state["optim"])
    start_epoch = state["epoch"] + 1
for epoch in range(start_epoch, EPOCHS):
    train_one_epoch()
    torch.save({"model": model.state_dict(), "optim": optimizer.state_dict(), "epoch": epoch}, ckpt + ".tmp")
    os.replace(ckpt + ".tmp", ckpt)   # 저장 도중 선점돼도 깨진 파일이 남지 않는다
```

## 클러스터 읽는 법

- 노드의 `GPU N/M 예약` 은 요청(예약) 수다. 아직 뜨지 않은 모델 서빙의 예약까지 세고, 서빙(`kind: serving`)이 쥔 GPU 는 잡·워크스페이스가
  요청하면 회수되므로 사실상 빈 자리다. 실제 사용률이 아니다.
- `팀 큐` 의 `대기 N개` 는 그 팀 큐의 대기 수다(다른 팀의 대기는 내 순서와 무관하다).
- `used: null` 은 "측정하지 못했다", `used: 0` 은 "쓰지 않는다"다.
- `degraded` 가 비어 있지 않으면 일부 수집이 실패한 것이다(`metrics` → 사용량 null, `queues` → 큐 빈 배열). 나머지 값은 유효하다.
- 팀마다 A5000 1장과 RTX 5080 1장이 배정돼 있고, 남는 몫은 빌려 쓴다(빌린 몫은 선점될 수 있다).
- 내 팀은 `icrap me` 에 나오지 않는다. 제출이 `team_not_assigned` 로 거부되면 팀이 없는 것이니 관리자에게 배정을 요청한다.

## 오류 코드

API 오류는 exit 1 과 표준 오류의 `{"status","code","message"}` 한 줄이다. **`code` 로 판단한다.**

| code | 상태 | 대응 |
|---|---|---|
| `invalid_token` · `token_expired` | 401 | exit 3. `icrap me` 로 어느 토큰인지 본다. 읽기면 `icrap login`, 쓰기면 관리자 재발급 → 사용자가 `login --paste` |
| `account_inactive` | 403 | exit 4. 관리자에게. 복구되면 같은 토큰이 다시 통한다 |
| `insufficient_scope` | 403 | 쓰기 토큰이 필요하다(SKILL.md 0절) |
| `forbidden` | 403 | 관리자 전용 경로 |
| `bad_input` · `unknown_image` | 400 | `message` 의 필드를 고친다 |
| `no_gpu_class_available` | 400 | GPU 장수·VRAM·이미지 조건을 낮춘다 |
| `team_not_assigned` · `team_misconfigured` · `shared_volume_unavailable` | 409 | 관리자에게 |
| `job_exists` | 409 | CLI 가 처리한다. 같은 명령이면 이미 제출된 것, 다르면 이름을 바꾼다 |
| `transition_in_progress` | 409 | 워크스페이스 전이 중. 10~30초 뒤 다시 |
| `not_found` | 404 | 그런 잡·워크스페이스가 없다 |
| `submit_unknown` | 502 | CLI 가 목록을 확인해 준다. 확인 전에는 재시도하지 않는다 |
| `job_rejected` · `team_lookup_failed` | 502·500 | 잡은 만들어지지 않았다. 반복되면 관리자에게 |
| `cluster_unreachable` · `coder_unreachable` · `gpu_classes_unavailable` · `auth_unavailable` | 5xx | 1분쯤 뒤 다시 |
| `cluster_token_expired` · `cluster_not_configured` · `jobs_not_configured` | 5xx | 플랫폼 설정 문제. 관리자에게 |
| `unexpected_response` | — | 문서에 없는 응답. 내용을 사용자에게 보여 주고 관리자에게 알리게 한다 |

## 워크스페이스 SSH 의 내부

- `icrap login --ssh` 가 받은 Coder 세션은 `~/.config/icrap/coder/` 에 따로 둔다. 사용자가 직접 한 `coder login` 설정은 건드리지 않는다.
- coder 바이너리는 `~/.local/share/icrap/coder-<버전>` 과 고정 이름 `coder` 로 icrap 이 관리한다. PATH 의 `coder` 는 쓰지 않는다(`ICRAP_CODER_BIN` 을 주면 그것).
  Coder 서버가 업그레이드되면 다음 `icrap ws …` 가 새 버전을 받아 고정 이름을 바꾼다.
- 바이너리를 못 받으면(네트워크, 지원하지 않는 OS·CPU, 해시 불일치) exit 1 과 원인이 나온다. 사용자가 직접 설치한 coder 경로를 `ICRAP_CODER_BIN` 에 주면 된다.
- `ws config-ssh` 는 `~/.ssh/config` 의 Coder 블록을 icrap 의 세션·고정 이름 바이너리로 **다시 쓴다**(전에 `coder config-ssh` 를 했다면 그 블록이 바뀐다).
  그 뒤 `ssh <ws>.coder` 는 icrap 세션에 묶인다: `icrap logout --ssh` 나 만료 뒤에는 `icrap login --ssh` 를 해야 다시 된다.
  꺼진 워크스페이스를 `ssh <ws>.coder` 가 켜지도 않는다(`--disable-autostart`).
- 계정이 정지·만료되면 5분 안에 SSH 가 막힌다(exit 4).

## 워크스페이스 저장 공간

| 위치 | 있는 템플릿 | 워크스페이스를 지우면 |
|---|---|---|
| `/home/coder` | 전체 | 함께 지워진다 |
| `/data` | GPU 템플릿과 `full-*`(`icrap templates` 에 `/data` 크기가 보이는 것) | 함께 지워진다 |
| `/shared` | 팀에 배정된 사람의 모든 워크스페이스 | 남는다(팀당 1.5TiB) |

## 토큰 교체

활성 API 토큰은 2개까지다. `icrap me` 가 만료 14일 전부터 경고한다. 읽기 토큰은 `icrap login` 을 다시 하면 교체되고,
쓰기 토큰은 관리자에게 재발급을 요청해 사용자가 `icrap login --paste` 로 넣은 뒤 옛 토큰을 포털에서 폐기한다.

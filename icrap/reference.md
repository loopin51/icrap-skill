# ICRAP 참고 자료

SKILL.md 에서 필요할 때만 읽는다. 원본은 포털 `/docs` 의 `api.md`·`researcher-jobs.md`·`researcher-cli.md` 다.

## 잡 상태와 실패 사유

`icrap jobs --json` 의 `phase`:

| phase | 뜻 | 할 일 |
|---|---|---|
| `queued` | 팀 쿼터가 비기를 기다린다. `queuePosition` 이 순번(0부터)이다 | 기다린다. 다시 제출하지 않는다 |
| `requeued` | 선점되어 다시 줄 섰다 | 기다린다. 다시 시작되면 처음부터 돈다 |
| `waiting_node` | 쿼터는 받았는데 노드에 자리가 없다 | 기다린다 |
| `preparing` | 코드 clone, 이미지(3~4GB) 받기, uv 설치 중 | 처음엔 몇 분, torch 를 설치하면 10분 가까이 걸린다 |
| `running` · `succeeded` | | |
| `failed` | `failure` 에 사유가 있다 | 아래 표 |
| `unknown` | 포털이 상태를 못 읽었다 | 잠시 뒤 다시 본다 |

`failure`(모르는 값은 실패로 처리한다):

| failure | 원인 | 고칠 것 |
|---|---|---|
| `oom` | 배정 메모리 초과(GPU 1장 24GiB, `24g` 32GiB, 5080 2장 48GiB, CPU 잡 16GiB) | 배치 크기·DataLoader worker 수를 줄인다 |
| `deadline` | 72시간 초과 | 체크포인트에서 이어 가는 잡으로 나눈다. 더 필요하면 관리자 |
| `clone` | 저장소 URL·ref 오류, 비공개 저장소 | 공개 여부, ref 가 push 됐는지 확인한다 |
| `exit` | 명령이 0 아닌 값으로 끝났다 | `icrap logs <이름>` 으로 `main` 을 읽는다. 사유가 `uv 준비 실패` 면 `--container uv-install` |
| `evicted` | 노드가 퇴출했다. 대개 `/workspace` 200GiB 초과 | 큰 파일을 `$RUN_DIR` 로, 큰 데이터는 `/shared` 에서 직접 읽는다 |

끝난 잡은 7일 뒤 목록에서 사라진다. 결과물은 `$RUN_DIR` 에 남는다.

## 잡 안의 경로

| 경로 / 변수 | 용도 |
|---|---|
| `/workspace` | clone 한 코드와 임시 공간. NVMe, 잡당 최대 200GiB, 잡이 끝나거나 선점되면 사라진다 |
| `$RUN_DIR` = `/shared/runs/<내 이름>/<잡 이름>/` | 결과물. `commit.txt` 에 실행한 커밋이 기록된다 |
| `/shared/datasets/` | 팀 공용 데이터셋 |
| `$HF_HOME` · `$UV_CACHE_DIR` · `$PIP_CACHE_DIR` | 팀 공유 캐시 |

- `/shared` 는 HDD 다. 순차 읽기는 초당 약 200MiB 로 빠르지만 작은 파일 수십만 개는 느리다. tar·parquet·webdataset 으로 묶는다.
- 작은 파일이 많은 데이터는 명령 앞에서 NVMe 로 복사한다: `cp -r /shared/datasets/<name> /workspace/data && python train.py --data /workspace/data`.
  100GiB 복사에 약 8분이 걸리고, 선점되면 복사도 다시 한다.
- 팀 디스크 쿼터 때문에 팀마다 동시에 도는 잡은 2개까지다. 나머지는 `queued` 로 기다린다.
- 큰 공개 데이터셋은 내려받기 잡으로 넣는다:
  `--gpus 0 --command "pip install -q huggingface_hub && huggingface-cli download <org>/<dataset> --repo-type dataset --local-dir /shared/datasets/<name>"`
  (저장소는 아무 공개 저장소나 쓴다).

## 선점에 견디는 체크포인트

```python
import os, torch
ckpt = os.path.join(os.environ["RUN_DIR"], "checkpoint.pt")
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

로컬에서 돌릴 때를 위해 `os.environ.get("RUN_DIR", "runs/local")` 처럼 기본값을 두면 같은 코드를 양쪽에서 쓸 수 있다.

## 클러스터 읽는 법

- `used: null` 은 "측정하지 못했다", `used: 0` 은 "쓰지 않는다"다. 둘을 섞지 않는다.
- `degraded` 가 비어 있지 않으면 일부 수집이 실패한 것이다(`metrics` → 사용량이 null, `queues` → 큐 목록이 빈 배열). 나머지 값은 유효하다.
- `gpuCount.requested` 는 예약된 GPU 수다. 서빙(`kind: serving`)이 쥔 GPU 는 잡·워크스페이스가 요청하면 회수되므로 사실상 빈 자리다.
- 팀마다 A5000 1장과 RTX 5080 1장이 배정돼 있고, 남는 몫은 같은 cohort 안에서 빌려 쓴다(빌린 몫은 선점될 수 있다).

## 오류 코드

공통(인증·계정):

| code | 상태 | 대응 |
|---|---|---|
| `invalid_token` | 401 | 토큰이 없거나 틀렸거나 폐기됐다. 새로 발급 |
| `token_expired` | 401 | 90일이 지났다. 새로 발급 |
| `account_inactive` | 403 | 계정 정지·만료. 관리자에게. 복구되면 같은 토큰이 다시 통한다 |
| `forbidden` | 403 | 관리자 전용 경로 |
| `auth_unavailable` | 503 | 포털 DB 오류. 잠시 뒤 재시도 |
| `cluster_token_expired` · `cluster_not_configured` | 502·503 | 플랫폼 설정 문제. 관리자에게 |

쓰기:

| code | 상태 | 대응 |
|---|---|---|
| `insufficient_scope` | 403 | 관리자에게 그 스코프의 토큰을 요청 |
| `bad_input` | 400 | `message` 의 필드를 고친다 |
| `unknown_image` | 400 | 이미지 id 를 확인한다 |
| `no_gpu_class_available` | 400 | GPU 장수·VRAM·이미지 조건을 낮춘다 |
| `team_not_assigned` · `team_misconfigured` · `shared_volume_unavailable` | 409 | 관리자에게 |
| `job_exists` | 409 | 같은 이름의 잡이 있다. 내 잡이면 이미 제출된 것으로 본다(스크립트가 처리) |
| `transition_in_progress` | 409 | 워크스페이스가 전이 중. 10~30초 뒤 다시 |
| `not_found` | 404 | 그런 잡·워크스페이스가 없다 |
| `team_lookup_failed` | 500 | 잡은 만들어지지 않았다. 잠시 뒤 재시도 |
| `job_rejected` | 502 | 클러스터가 거부했다. 잡은 만들어지지 않았다. 반복되면 관리자에게 |
| `submit_unknown` | 502 | 만들어졌는지 모른다. **목록 확인 전에는 재시도하지 않는다**(스크립트가 처리) |
| `cluster_unreachable` · `coder_unreachable` | 502 | 잠시 뒤 재시도 |
| `gpu_classes_unavailable` · `jobs_not_configured` | 503 | 앞은 잠시 뒤 재시도, 뒤는 관리자에게 |

거부 계열(`unknown_image`·`no_gpu_class_available`·`job_rejected` 등)은 같은 문구만 돌려준다. 자세한 사유는 포털 화면에 있다.

## coder CLI 준비

사용자가 한 번 해야 하는 일이다. 단계를 안내하고, 로그인처럼 브라우저가 필요한 단계는 사용자에게 맡긴다.

Coder 공개 주소 `https://coder.blueodor.xyz` 로 인터넷 어디서든 된다(Tailscale 불필요).

1. 설치(sudo 불필요, 서버와 같은 버전): `mkdir -p ~/.local/bin && curl -fsSL -o ~/.local/bin/coder https://coder.blueodor.xyz/bin/coder-linux-amd64 && chmod +x ~/.local/bin/coder`
   (맥 `coder-darwin-arm64`·`coder-darwin-amd64`, 윈도 `coder-windows-amd64.exe`)
2. **사용자가 자기 터미널에서** `coder login https://coder.blueodor.xyz` 를 실행한다(`Paste your token here` 에서 기다린다).
3. 사용자가 브라우저에서 `https://icrap.blueodor.xyz/coder-cli` 를 열어 `Coder 세션 토큰 받기` 를 누르고, 나온 토큰을 그 터미널에 붙여 넣는다.
   워크스페이스가 없어도 된다. Coder 로그인 화면으로는 들어갈 수 없다(포털이 만든 계정이라 비밀번호가 없고, GitHub 로 시도하면
   `Incorrect login type`). 사용자가 그 오류를 말하면 `/coder-cli` 를 안내한다.
4. 확인: `python3 ~/.claude/skills/icrap-run/scripts/ws.py check` 가 `로그인됨` 과 내 워크스페이스를 보여 준다.
5. 선택: `coder config-ssh` 를 하면 `ssh <워크스페이스>.coder`, `scp`, `rsync`, VS Code Remote-SSH 가 그대로 통한다.

- CLI 세션 토큰은 워크스페이스 셸 권한이다. **대화창에 붙여 달라고 하지 않고**, 출력·저장·커밋하지 않는다.
  사용자가 붙여 넣었다면 `coder logout`(서버에서 폐기) 뒤 다시 로그인하기를 권한다.
- 세션은 7일 동안 유효하고 쓸 때마다 늘어난다. `coder tokens create` 토큰은 최대 7일이다. 계정이 정지·만료되면 5분 안에 막힌다.
- `ws.py check` 가 로그인 안내를 내면 2·3단계를 다시 하게 한다.

## 워크스페이스 저장 공간

| 위치 | 있는 템플릿 | 워크스페이스를 지우면 |
|---|---|---|
| `/home/coder` | 전체 | 함께 지워진다 |
| `/data` | GPU 템플릿(`gpu-a5000`·`gpu-rtx5080-*`)과 `full-*`(`icrap templates` 에 `/data` 크기가 보이는 것) | 함께 지워진다 |
| `/shared` | 팀에 배정된 사람의 모든 워크스페이스 | 남는다(팀당 1.5TiB) |

## 토큰 교체

활성 토큰은 2개까지다. 새 토큰을 발급 → `icrap login` 으로 입력(같은 자리를 덮어쓴다) → 옛 토큰을 포털에서 폐기하면
끊김 없이 바꿀 수 있다. `icrap me` 가 토큰마다 만료 14일 전부터 경고한다. 쓰기 토큰의 재발급은 관리자에게 요청한다.

---
name: icrap
description: 연구팀 GPU 자원 플랫폼 ICRAP(icrap.blueodor.xyz)을 쓸 때 사용한다. 학습·추론 코드를 배치 잡으로 제출하고 상태를 지켜보거나 취소할 때, 클러스터에 남은 GPU 를 확인할 때, 내 워크스페이스를 시작·정지하거나 coder CLI 로 접속해 결과물(/shared/runs)을 볼 때 쓴다. "ICRAP", "배치 잡", "잡 제출", "클러스터 GPU", "워크스페이스", "coder ssh" 가 나오면 이 스킬을 먼저 읽는다.
---

# ICRAP 사용

ICRAP 은 연구팀의 온프렘 GPU 클러스터(RTX A5000 24GB ×2대, RTX 5080 16GB ×2장 1대)를 나눠 쓰는 플랫폼이다.
연구원이 쓰는 길은 두 가지다.

- **배치 잡**: 공개 git 저장소의 코드를 큐에 넣으면 GPU 가 날 때 실행되고 끝나면 GPU 를 반납한다. 긴 학습은 항상 이것으로 한다.
- **워크스페이스**: Coder 가 띄우는 개인 개발 환경(CPU·GPU). 코드 작성·디버깅·결과 확인용이다.

코드를 돌린 뒤 로그·지표를 검토하고 고쳐서 다시 돌리는 반복은 `icrap-run` 스킬이 맡는다(이 스킬의 클라이언트를 쓴다).

이 스킬의 API 클라이언트는 `scripts/icrap.py` 다(표준 라이브러리만 쓴다). 아래에서 `icrap` 은
`python3 ~/.claude/skills/icrap/scripts/icrap.py` 를 뜻한다(프로젝트에 설치했다면 `.claude/skills/icrap/scripts/icrap.py`).

## 0. 처음에 확인한다

```bash
icrap me
```

ICRAP 은 사용자 본인 계정의 **API 토큰**으로 로그인한다. 토큰은 두 종류다.

| 토큰 | 누가 발급하나 | 할 수 있는 일 | 저장 위치 |
|---|---|---|---|
| 읽기(`read`) | 사용자 본인: 포털 → `계정` → `API 토큰` | 클러스터·템플릿·내 워크스페이스·내 잡·잡 로그 조회 | `~/.config/icrap/token` |
| 쓰기(`jobs:write`, `workspaces:write`) | **관리자만** | 위의 조회 + 잡 제출·취소(`jobs:write`), 워크스페이스 시작·정지(`workspaces:write`) | `~/.config/icrap/write-token` |

클라이언트는 조회에 읽기 토큰을, 쓰기 작업에 쓰기 토큰을 쓴다. `icrap me` 출력의 `할 수 있는 일` 을 보고 무엇을 할지 정한다.

- `로그인되어 있지 않습니다` → 사용자에게 포털에서 읽기 토큰을 발급하고 **사용자 자신의 터미널에서**
  `python3 ~/.claude/skills/icrap/scripts/icrap.py login` 을 실행해 입력하라고 안내하고 기다린다(입력은 화면에 보이지 않는다).
  `login` 은 토큰을 포털에 확인한 뒤 스코프를 보고 읽기·쓰기 자리에 저장한다. Claude 가 직접 `login` 을 실행하면
  입력을 받을 수 없어 실패한다. 사용자가 Claude Code 에서 `! <명령>` 으로 실행해도 입력 창이 뜨지 않을 수 있으니
  별도 터미널을 권한다.
- 쓰기 작업이 필요한데 `할 수 있는 일` 에 없다(`insufficient_scope`) → 우회하지 말고 사용자에게 알린다:
  "관리자에게 `jobs:write`(필요하면 `workspaces:write`) 쓰기 토큰 발급을 요청하고, 받은 토큰을 같은 `login` 으로 입력하세요."
  쓰기 토큰을 기다리는 동안 할 수 있는 조회·준비(저장소 정리, 명령 확인)는 계속한다.
- 로그아웃은 `icrap logout`(`--read`·`--write` 로 한쪽만)이다. 이 컴퓨터의 파일만 지우므로, 토큰 자체를 무효로 하려면
  포털 → `계정` → `API 토큰` 에서 폐기하라고 알린다.
- `ICRAP_TOKEN` 환경 변수를 주면 저장된 토큰 대신 그것 하나만 쓴다(CI 용).
- 기본 주소는 공개 도메인 `https://icrap.blueodor.xyz` 다. 다른 주소를 써야 하면 `ICRAP_URL` 로 바꾼다.

⚠️ 토큰을 대화창에 붙여 달라고 요청하지 않는다. 토큰 원문을 출력하거나, 파일·커밋·로그에 쓰거나, 명령줄 인자로 넘기지 않는다.
사용자가 그래도 대화창에 붙여 넣었다면 `icrap login <<'EOF'` 처럼 표준 입력으로 저장해 주고 다시 말하지 않으며,
대화 기록에 남았으니 포털에서 그 토큰을 폐기하고 새로 발급하기를 권한다.

## 1. 배치 잡으로 학습 돌리기

### 제출 전에 저장소를 준비한다

잡은 **원격 저장소를 clone 해서** 돌린다. 로컬의 커밋하지 않은 변경, push 하지 않은 커밋은 잡에 들어가지 않는다.

1. 저장소가 **공개** `https://` git 저장소인지 확인한다. 비공개 저장소는 지원하지 않는다. 비공개라면 사용자에게 알리고 멈춘다.
2. 변경을 커밋하고 push 한 뒤 `--ref` 에 **그 커밋 SHA** 를 넘긴다(브랜치 이름보다 재현성이 좋다). push 는 사용자 확인 뒤에 한다.
3. 파이썬 환경을 정한다. 잡은 항상 uv 가상환경 `/workspace/.venv` 를 켠 채 `command` 를 실행한다.

| 저장소 | 잡이 하는 일 | 언제 고르나 |
|---|---|---|
| `pyproject.toml`(`[project]`) + `uv.lock` | `uv sync --frozen` | 재현성이 필요할 때(권장). **torch 도 의존성에 넣어야 한다** |
| `pyproject.toml`(`[project]`) 만 | `uv sync` | 버전 고정이 필요 없을 때 |
| 그 밖 | 이미지의 파이썬(PyTorch 포함)으로 빈 환경 | 짧은 실험. 설치 시간이 없다 |

   - torch 를 넣은 uv 프로젝트는 첫 잡에 약 9분, 같은 팀의 다음 잡도 약 2분을 설치에 쓴다(2026-10-11 실측).
     짧은 실험이면 uv 프로젝트로 만들지 말고 이미지의 torch 를 쓴다.
   - 패키지 몇 개만 더 필요하면 명령에 붙인다: `uv pip install -r requirements.txt && python train.py`.
     이때 `requirements.txt` 에 torch 를 넣지 않는다(다시 내려받는다).
4. **선점에 대비해 체크포인트에서 이어 하게 짠다.** 잡은 다른 팀이 자기 몫의 GPU 를 되찾으면 중단되고 처음부터 다시 시작한다.
   체크포인트는 `$RUN_DIR`(= `/shared/runs/<내 이름>/<잡 이름>/`)에 임시 파일로 쓰고 `os.replace` 로 바꿔치기한다.
   `/workspace` 는 잡이 끝나거나 선점되면 사라진다. 코드 예시는 [reference.md](reference.md#선점에-견디는-체크포인트).
5. 결과물(모델·지표)은 `$RUN_DIR` 에 쓴다. 표준 출력은 `icrap logs` 로 읽을 수 있지만 **가장 최근 실행**의 것뿐이다.
   선점 전 기록까지 남기려면 명령 끝에 `2>&1 | tee -a "$RUN_DIR/stdout.log"` 를 붙인다. 명령은 `bash -o pipefail` 로 실행되므로
   파이프를 붙여도 실패가 그대로 실패로 남는다. 반대로 `python train.py; ls "$RUN_DIR"` 처럼 본 명령 뒤에 `;` 로 무언가를
   붙이면 마지막 명령의 종료 코드가 잡의 성공·실패를 정하므로, 앞에 붙일 것은 `&&` 로 잇고 본 명령을 맨 끝에 둔다.

### 자원을 고른다

- `--gpus` 는 **코드가 실제로 쓰는 장수**다. 1장용 코드에 2를 주면 1장이 논다. `torchrun --nproc_per_node=2` 일 때만 2.
  GPU 2장 잡은 RTX 5080 노드에서만 돌고 다른 팀 몫을 빌려야 시작되므로 오래 기다릴 수 있다.
- `--vram 24g` 는 16GB 에서 OOM 이 나는 모델에만 준다(A5000 만 쓰게 된다).
- CPU·메모리는 플랫폼이 정한다: GPU 1장 잡은 CPU 8코어·메모리 24GiB(`24g` 면 32GiB), RTX 5080 2장 잡은 20코어·48GiB,
  CPU 잡(`--gpus 0`)은 4코어·16GiB. 배정 메모리를 넘으면 `oom` 으로 실패한다.
- 이미지: `pytorch-2.14-cu130`(GPU 기본, 모든 GPU), `pytorch-2.11-cu128`, `python-3.12-cpu`(`--gpus 0` 기본).
- 최대 실행 시간은 72시간(대기 제외)이고, `/workspace` 한도는 잡당 200GiB 다.

지금 GPU 가 비었는지 궁금하면 `icrap cluster` 로 노드별 GPU 예약과 팀 큐 대기 수를 본다.

### 제출하고 지켜본다

```bash
icrap submit --name resnet-lr3e4 --repo https://github.com/<org>/<repo> --ref <commit-sha> \
  --command 'python train.py --lr 3e-4 2>&1 | tee -a "$RUN_DIR/stdout.log"' --gpus 1
icrap wait resnet-lr3e4 --timeout 1800     # 상태가 바뀔 때마다 한 줄. 끝나면 exit 0(완료) / 3(실패)
icrap jobs                                  # 내 잡 전체
icrap logs resnet-lr3e4 --tail 200          # 표준 출력·오류의 마지막 200줄(실행 중에도 된다)
icrap logs resnet-lr3e4 --container uv-install   # 환경 만들기 단계(git-clone 도 있다)
```

- **이름은 보낸 그대로 쓰이고 팀 안에서 유일해야 한다.** 소문자·숫자·하이픈 40자 이내, 영숫자로 시작·끝.
  실험 내용을 담아 짓는다(`resnet-lr3e4`). 같은 이름으로 다시 제출하면 재시도로 처리되어 잡이 둘 생기지 않는다.
  다른 실험이면 이름을 바꾼다.
- `submit` 이 `submit_unknown` 을 받으면 스크립트가 목록을 확인해 준다. 이 경우 말고는 실패한 제출을 고민 없이 다시 보내도 된다.
- `queued`(줄 서는 중)는 쿼터가 비기를 기다리는 정상 상태다. **다시 제출하지 않는다.** 자리가 나면 자동으로 실행된다.
- `wait` 는 오래 걸릴 수 있다. Bash 도구의 시간 제한(최대 10분) 안에서 끝나도록 `--timeout 540` 처럼 끊어 부르고,
  더 기다려야 하면 사용자에게 알린 뒤 백그라운드로 돌리거나 나중에 `icrap jobs <이름>` 으로 다시 본다.
  폴링 간격은 30초 미만으로 줄이지 않는다.
- 상태와 실패 사유(`oom`·`deadline`·`clone`·`exit`·`evicted`)별 대응은 [reference.md](reference.md#잡-상태와-실패-사유).

### 취소한다

```bash
icrap cancel resnet-lr3e4
```

돌고 있는 학습을 끝내는 일이므로 **사용자가 요청했거나 확인했을 때만** 취소한다. 남의 잡은 취소할 수 없다.

## 2. 워크스페이스

```bash
icrap templates            # 고를 수 있는 템플릿과 스펙
icrap workspaces           # 내 워크스페이스(이름·상태·id)
icrap ws-start <이름>       # 정지된 워크스페이스 시작(보통 30초). 최신 템플릿 버전으로 갱신된다
icrap ws-stop <이름>        # 정지(보통 10초). 홈·/data 는 남는다
```

- 정지는 그 안에서 돌던 프로세스를 끊는다. **사용자가 요청했을 때만** 정지한다.
- 워크스페이스 만들기·삭제는 API 에 없다. 포털 `워크스페이스` 화면에서 사용자가 한다.
- 이미 그 상태면 아무것도 바꾸지 않고 성공으로 끝난다. `transition_in_progress` 면 잠시 뒤 다시 부른다.

### 워크스페이스 안에서 명령 돌리기(SSH)

워크스페이스에 SSH 로 들어가 파일을 보거나 명령을 돌릴 때는 `icrap-run` 스킬의 `ws.py` 를 쓴다(coder CLI 위에서 돈다).
공개 주소 `https://coder.blueodor.xyz` 로 되므로 Tailscale 은 필요 없다. coder CLI 설치와 `coder login` 은 사용자가
자기 터미널에서 한 번 한다([reference.md](reference.md#coder-cli-준비)). Claude 는 세션 토큰을 받거나 다루지 않는다.

```bash
ws=~/.claude/skills/icrap-run/scripts/ws.py
python3 $ws check                                                        # 로그인·내 워크스페이스 상태(처음 한 번)
python3 $ws exec <워크스페이스> -- 'ls /shared/runs/<내 이름>/resnet-lr3e4/'   # 잡 결과물 확인
python3 $ws exec <워크스페이스> -- 'tail -n 50 /shared/runs/<내 이름>/resnet-lr3e4/stdout.log'   # 선점 전 기록까지
```

`check` 나 다른 명령이 로그인 안내(종료 코드 3)를 내면 그 안내를 사용자에게 그대로 전하고 기다린다.
종료 코드 4 는 계정 정지·만료다(관리자에게 문의).

- `/shared` 는 팀 공유 볼륨이다(팀에 배정된 사람의 모든 워크스페이스와 잡이 함께 본다). **팀원끼리 서로 지울 수 있으니
  남의 폴더는 건드리지 않는다.** 남길 것은 `/shared/users/<내 이름>/` 으로 옮긴다. 워크스페이스를 지우면 홈과 `/data` 는 사라진다.
- `<내 이름>` 은 이메일 `@` 앞부분이다(`icrap me` 로 확인).
- 긴 학습을 워크스페이스에서 `nohup` 등으로 띄우지 않는다. 배치 잡으로 보낸다.

## 할 수 없는 일 (포털 화면이나 관리자에게 넘긴다)

| 하고 싶은 일 | 방법 |
|---|---|
| 잡이 만든 파일(체크포인트·지표 파일) 읽기 | 워크스페이스에서 coder ssh 로 `/shared/runs/<내 이름>/<잡 이름>/` 을 읽는다. 표준 출력은 `icrap logs` 로 된다 |
| 워크스페이스 만들기·삭제 | 포털 `워크스페이스` 화면 |
| 모델 서빙(OpenAI 호환 API) | 포털 `모델 서빙` 화면(Premium 배포만). 만든 뒤 `https://serving.blueodor.xyz/<내 이름>/v1` 로 부른다 |
| 쓰기 토큰 발급, 팀 배정, 우선순위·72시간 초과 요청 | 관리자 |
| 비공개 저장소로 잡 돌리기 | 지원하지 않는다. 공개 저장소로 옮기거나 워크스페이스에서 돌린다 |

## 오류를 만나면

오류는 표준 오류에 `{"status", "code", "message"}` JSON 으로 나오고 exit 1 이다. **`message` 가 아니라 `code` 로 판단한다.**
자주 나오는 것만 적는다. 전체 표는 [reference.md](reference.md#오류-코드).

| code | 할 일 |
|---|---|
| `insufficient_scope` | 이 토큰으로는 못 한다. 사용자에게 관리자에게 쓰기 토큰을 요청하라고 안내한다 |
| `token_expired` · `invalid_token` | `icrap me` 로 어느 토큰인지 본다. 읽기 토큰이면 사용자가 새로 발급하고, 쓰기 토큰이면 관리자에게 재발급을 요청한 뒤 `login` 으로 다시 입력하게 한다 |
| `account_inactive` | 계정이 정지·만료됐다. 관리자에게 문의 |
| `team_not_assigned` | 배치 팀 배정이 없다. 관리자에게 요청 |
| `bad_input` | `message` 에 틀린 필드가 있다. 고쳐서 다시 낸다 |
| `no_gpu_class_available` | GPU 장수·VRAM·이미지 조건을 만족하는 노드가 없다. 조건을 낮춘다 |
| `cluster_unreachable` · `coder_unreachable` · `gpu_classes_unavailable` | 1분쯤 뒤 다시 시도한다 |
| `unexpected_response` | 문서에 없는 응답이다. 내용을 사용자에게 보여 주고 관리자에게 알리게 한다 |

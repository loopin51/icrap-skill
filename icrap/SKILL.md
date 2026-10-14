---
name: icrap
description: 연구팀 GPU 자원 플랫폼 ICRAP(icrap.blueodor.xyz)을 쓸 때 사용한다. 배치 잡을 제출·조회·취소하거나 로그를 볼 때, 클러스터에 남은 GPU 를 확인할 때, 내 워크스페이스를 시작·정지하거나 SSH 로 들어가 결과물(/shared/runs)을 볼 때, `icrap` 명령이 없거나 로그인을 요구할 때 읽는다. "ICRAP", "배치 잡", "잡 제출", "클러스터 GPU", "워크스페이스", "icrap login" 이 나오면 먼저 읽는다.
---

# ICRAP 사용

ICRAP 은 연구팀의 온프렘 GPU 클러스터(RTX A5000 24GB ×2대, RTX 5080 16GB ×2장 1대)를 나눠 쓰는 플랫폼이다. 길은 둘이다.

- **배치 잡**: 공개 git 저장소의 커밋을 큐에 넣으면 GPU 가 날 때 돌고 끝나면 반납한다. 긴 학습은 항상 잡이다.
- **워크스페이스**: Coder 가 띄우는 개인 개발 환경(CPU·GPU). 작성·디버깅·결과 확인용이다.

코드를 돌리고 → 로그·지표를 검토하고 → 고쳐서 다시 돌리는 반복은 `icrap-run` 스킬을 함께 읽는다.
모든 조작은 `icrap` CLI 로 한다. 명령·옵션은 `icrap <명령> --help` 가 원본이다. 전체 표·상태·오류 코드는 [reference.md](reference.md).

## 0. 준비: 설치·로그인·종료 코드

**설치.** `command -v icrap` 도 `~/.local/bin/icrap` 도 없으면 설치한다(`ICRAP_URL` 이 설정돼 있으면 그 포털의 `$ICRAP_URL/cli/install.sh`).

```bash
curl -fsSL https://icrap.blueodor.xyz/cli/install.sh | sh
```

PATH 에 없으면 `~/.local/bin/icrap` 로 부른다(Python 3.8 이상, sudo 불필요, 맥·리눅스·WSL). 설치했다는 사실은 로그인 안내와 **같은 메시지**에 알린다.
출력에 "새 icrap 이 있습니다" 가 보이면 `icrap update` 를 실행한다.

**로그인.** 먼저 `icrap me` 로 상태와 `할 수 있는 일` 을 본다. 로그인이 필요하면:

1. 조회·잡만 필요하면 `icrap login`, 워크스페이스 SSH(`icrap ws check·info·push·run·exec·put·pull·ssh·config-ssh`)가 필요하면 `icrap login --ssh`.
2. **Bash `run_in_background` 로** 실행한다(승인까지 최대 10분 기다린다). 출력의 `주소` 와 `코드` 를 **그대로** 사용자에게 전하고,
   브라우저에서 그 주소를 열어 포털에 로그인한 뒤 코드를 입력해 승인하라고 한다. 같은 메시지에 함께 적는다:
   - `--ssh` 면: "`--ssh` 로 승인하면 이 컴퓨터가 내 워크스페이스 전체를 조작(셸 접속 포함)할 수 있게 됩니다(7일, 쓸 때마다 연장)."
   - 요청에 잡 제출·취소나 워크스페이스 시작·정지가 들어 있으면: 그 일에는 관리자가 발급하는 쓰기 토큰이 필요하고 사용자가 자기 터미널에서
     `icrap login --paste` 로 넣어야 한다는 것(아래).
3. 사용자가 "승인했다" 고 해도 그 말만 믿지 않는다. 백그라운드 출력에 `승인됐습니다` 와 `읽기 토큰 저장`(`--ssh` 면 `워크스페이스 SSH 세션 저장` 도)이
   있는지 보고, `icrap me` 로 `할 수 있는 일` 을 확인한 뒤 이어 간다. 프로세스가 성공 없이 끝났으면(만료·거부·활성 토큰 2개) 그 문구를 전하고 새로 로그인한다.
4. 백그라운드 실행을 쓸 수 없는 환경이면 사용자에게 자기 터미널에서 `icrap login`(필요하면 `--ssh`)을 실행하게 하고 끝나면 `icrap me` 로 확인한다.

쓰기(잡 제출·취소 `jobs:write`, 워크스페이스 시작·정지 `workspaces:write`)는 **관리자가 발급한 쓰기 토큰**이 있어야 한다.
`insufficient_scope` 나 `할 수 있는 일` 에 없으면 사용자에게 "관리자에게 쓰기 토큰을 요청하고, 받은 토큰은 **자기 터미널에서** `icrap login --paste`
로 입력하세요(화면에 보이지 않습니다)" 라고 안내한다. `--paste` 는 Claude 가 실행하지 않는다. 기다리는 동안 조회·준비는 계속한다.

**종료 코드로 판단한다**(문구가 아니라):

| 코드 | 뜻 | 할 일 |
|---|---|---|
| 0 | 성공 | — |
| 1 | API 오류. 표준 오류에 `{"status","code","message"}` | `code` 로 대응([reference.md](reference.md#오류-코드)) |
| 2 | 사용법·설정 오류. 메시지에 `icrap update` 가 있으면 낡은 CLI | `icrap update` 후 같은 명령을 다시 |
| 3 | 로그인 필요. `job wait` 에서는 **잡 실패**(표준 오류에 로그인 안내가 없을 때) | 위 로그인 흐름. SSH 명령이면 `icrap login --ssh` |
| 4 | 계정 정지·만료 | 우회하지 않는다. 관리자에게 문의하라고 알린다 |
| 124 | `ws run`·`exec` 시간 초과 | 잡으로 보낼지 판단한다 |

`ws run`·`exec`·`info`·`ssh` 의 종료 코드는 **원격 명령의 것**이다. 위 표(1·2·3·4)는 표준 오류에 `icrap:` 줄이 있을 때만 적용한다.

**Bash 도구 시간 제한**은 기본 120초, 최대 600초다. `job wait`, `ws run`·`exec`·`push`·`pull` 은 Bash 에 `timeout: 600000` 을 주고 부르며,
`job wait --timeout`·`ws run --timeout` 은 540초 이하로 둔다.

### 비밀값

- 토큰·세션을 대화창에 붙여 달라고 하지 않는다. `~/.config/icrap/` 의 파일을 읽거나 출력하지 않는다. 명령줄 인자로 넘기지 않는다.
- 출력이나 대화에 `rp_` 로 시작하는 값이 보이면 사용자에게 알리고 포털 `계정` → `API 토큰` 에서 그 토큰을 폐기하게 한다.
  Coder 세션 키가 드러났으면 `icrap logout --ssh`(서버에서도 폐기) 뒤 `icrap login --ssh` 를 권한다.
- `icrap logout` 은 이 컴퓨터의 파일만 지운다(`--ssh` 만 서버 폐기). 토큰 자체를 무효로 하려면 포털에서 폐기한다.

## 1. 배치 잡

```bash
icrap cluster                       # 노드별 GPU 예약·팀 큐 대기
icrap job submit --name resnet-lr3e4 --repo https://github.com/<org>/<repo> --ref <커밋 SHA> --gpus 1 \
  --command 'python train.py --lr 3e-4 2>&1 | tee -a "$RUN_DIR/stdout.log"'
icrap job wait resnet-lr3e4 --timeout 540   # 상태가 바뀔 때마다 한 줄
icrap job list                      # 내 잡 전체. 하나만: icrap job show <이름>
icrap job logs resnet-lr3e4 --tail 200      # 실행 중에도 된다. --container uv-install|git-clone
icrap job cancel resnet-lr3e4       # 사용자가 요청·확인했을 때만
```

### 제출 전에

1. 잡은 **원격 저장소를 clone** 한다. 저장소가 **공개 `https://`** 인지 확인한다. 비공개면 사용자에게 알리고 멈춘다(워크스페이스 경로는 된다).
2. 변경을 커밋하고 push 한다. **push 는 사용자 확인 뒤에** 한다. `--ref` 에는 push 한 **그 커밋 SHA**(`git rev-parse HEAD`)를 준다.
   남의 공개 저장소면 `git ls-remote <repo> HEAD` 로 SHA 를 얻는다. `--command` 를 짓기 전에 저장소의 README·`--help` 로 학습 인자를 확인한다.
3. 처음 돌리는 코드는 **짧은 시험 실행**(스텝·에폭을 줄인 것)을 먼저 보낸다. 몇 시간짜리 본 실행을 시험 없이 보내지 않는다.
4. **성공·실패는 명령 전체의 마지막 종료 코드다.** 앞에 붙일 것은 `&&` 로 잇고 학습을 맨 끝에 둔다. 학습 뒤에 `;` 로 무엇도 붙이지 않는다
   (`python train.py; ls "$RUN_DIR"` 는 학습이 실패해도 완료가 된다). 포털이 명령을 `bash -o pipefail -c` 로 실행하므로 `| tee -a …` 는
   학습의 실패를 그대로 남긴다. 그 밖의 파이프(`| grep`, `| head`)·`|| true` 는 붙이지 않는다(실패를 바꾸거나 학습을 끊는다).
5. 결과물·체크포인트는 `$RUN_DIR`(= `/shared/runs/<내 이름>/<잡 이름>/`)에 쓴다. `/workspace` 는 끝나거나 선점되면 사라진다.
   명령 끝에 `2>&1 | tee -a "$RUN_DIR/stdout.log"` 를 붙인다(`job logs` 는 가장 최근 실행만 준다).
6. 선점되면 처음부터 다시 돈다. 체크포인트에서 이어 가게 짠다([reference.md](reference.md#선점에-견디는-체크포인트)).
7. 파이썬 환경(uv·이미지의 torch)과 자원(`--gpus`·`--vram`·이미지)은 [reference.md](reference.md#잡-환경과-자원) 를 보고 정한다.
   `--gpus` 는 코드가 실제로 쓰는 장수다.

### 제출한 뒤

- **이름은 팀 안에서 유일**하다(소문자·숫자·하이픈 40자). 같은 이름·같은 명령의 재제출은 새 잡을 만들지 않는다. 다른 실험은 이름을 바꾼다.
- `queued` 는 정상 대기다. **다시 제출하지 않는다.**
- `job wait` 는 `--timeout 540`(Bash `timeout: 600000`)으로 끊어 부른다. exit 0 은 완료 **또는** 시간 제한(마지막 줄이 `시간 제한…` 이면 아직 도는 중),
  exit 3 은 실패다. 몇 번 끊어 불러도 안 끝나면 사용자에게 알리고 나중에 `job show` 로 다시 보거나 `job wait` 를 백그라운드로 돌린다.
  폴링 간격은 **30초 미만으로 줄이지 않는다**(`--interval` 최소 30).
- 실패하면 `job show` 의 `failure` 로 나누고 해당 컨테이너 로그를 읽는다([reference.md](reference.md#잡-상태와-실패-사유)).

## 2. 워크스페이스

```bash
icrap templates                  # 템플릿과 스펙
icrap ws list                    # 내 워크스페이스(이름·상태)
icrap ws start <ws>              # 보통 30초. 최신 템플릿으로 갱신된다(workspaces:write)
icrap ws stop <ws>               # 안에서 돌던 프로세스가 끊긴다. 사용자가 요청했을 때만
icrap ws check                   # coder·SSH 세션·워크스페이스 상태(SSH 를 쓰기 전에 한 번)
icrap ws exec <ws> -- 'ls /shared/runs/<내 이름>/resnet-lr3e4/'
```

- SSH 명령은 icrap 이 Coder 서버와 같은 버전의 coder 를 `~/.local/share/icrap/` 에 받아 쓴다(처음 한 번 수십 초). 따로 설치·`coder login` 하지 않는다.
- 꺼진 워크스페이스는 자동으로 켜지지 않는다. SSH 명령은 `<ws> 워크스페이스가 stopped 상태입니다…`(exit 1)로 멈춘다.
  사용자에게 알리고 `ws start`(쓰기 토큰 없으면 포털에서 켜 달라고) 한다.
- 만들기·삭제는 API 에 없다. 포털 `워크스페이스` 화면에서 사용자가 한다.
- `ws exec`·`ws run` 은 시간 제한(기본 540초) 안에서 돌고 원격 종료 코드를 돌려준다. `--` 뒤 따옴표 규칙은 `icrap-run` 스킬 3절.
- 긴 학습을 워크스페이스에서 돌리지 않는다(`nohup`·`&` 포함). 잡으로 보낸다.
- `/shared` 는 팀 공유다. 팀원끼리 서로 지울 수 있으니 **남의 폴더를 건드리지 않는다.** 남길 것은 `/shared/users/<내 이름>/` 으로.
  `<내 이름>` 은 이메일 `@` 앞부분이다(`icrap me`).

## 할 수 없는 일

| 하고 싶은 일 | 방법 |
|---|---|
| 워크스페이스 만들기·삭제, 모델 서빙 | 포털 화면 |
| 쓰기 토큰 발급, 팀 배정, 72시간 초과 | 관리자 |
| 비공개 저장소로 잡 | 지원하지 않는다. 공개 저장소로 옮기거나 워크스페이스에서 |

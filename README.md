# ICRAP Claude Code 스킬

연구팀 GPU 자원 플랫폼 **ICRAP**(`https://icrap.blueodor.xyz`)을 Claude Code 가 `icrap` CLI 로 대신 쓰게 하는 스킬 모음입니다.

| 스킬 | 하는 일 |
|---|---|
| `icrap` | CLI 설치·로그인, 배치 잡 제출·대기·취소·로그, 클러스터 GPU 현황, 워크스페이스 시작·정지·SSH |
| `icrap-run` | 로컬 코드를 배치 잡이나 워크스페이스에서 돌리고, 로그·지표를 검토하고, 고쳐서 다시 돌리는 반복 |

설치한 뒤에는 Claude Code 에 이렇게 말하면 됩니다.

- "ICRAP 에 지금 빈 GPU 있어?"
- "이 저장소의 train.py 를 GPU 에서 3 에폭만 돌려 보고 학습이 제대로 되는지 검토해 줘"
- "내 워크스페이스에서 테스트 돌려 보고 실패하면 고쳐 줘"

## 설치

1. 스킬: 공개 저장소 `https://github.com/loopin51/icrap-skill` 을 받아 두 스킬을 **함께** 링크합니다(`icrap-run` 이 `icrap` 의 규칙을 씁니다). 갱신은 `git pull` 로 합니다.

   ```bash
   git clone https://github.com/loopin51/icrap-skill ~/icrap-skill
   mkdir -p ~/.claude/skills
   ln -s ~/icrap-skill/icrap ~/icrap-skill/icrap-run ~/.claude/skills/
   ```

   한 프로젝트에서만 쓰려면 `<프로젝트>/.claude/skills/` 에 복사합니다.

2. CLI: 미리 설치해 두어도 되고, 없으면 Claude 가 알리고 설치합니다. Python 3.8 이상, 맥·리눅스(윈도는 WSL)에서 됩니다.

   ```bash
   curl -fsSL https://icrap.blueodor.xyz/cli/install.sh | sh     # ~/.local/bin/icrap
   ```

   포털이 새 버전을 배포하면 CLI 가 알려 주고 `icrap update` 로 바꿉니다.

### 예전 스킬에서 올리기

예전 스킬(`scripts/icrap.py`·`ws.py` 를 쓰던 것)을 쓰고 있었다면:

1. `cd ~/icrap-skill && git pull` — `scripts/` 가 지워지고 스킬이 `icrap` CLI 를 부르게 바뀝니다.
2. 위의 설치 한 줄로 CLI 를 설치합니다. 저장된 토큰(`~/.config/icrap/token`, `write-token`)은 그대로 쓰이므로 다시 로그인할 필요가 없습니다.
3. 워크스페이스 SSH 를 쓰려면 `icrap login --ssh` 를 한 번 합니다. 예전에 `coder config-ssh` 를 했다면 `icrap ws config-ssh` 가 그 블록을
   icrap 의 로그인으로 다시 씁니다(`ssh <이름>.coder` 가 icrap 세션을 쓰게 됩니다).

## 로그인

토큰을 복사해 붙여 넣을 필요는 없습니다. Claude 가 로그인을 시작하고 **주소와 코드**를 알려 주면,
브라우저에서 `https://icrap.blueodor.xyz/cli-login` 을 열어 포털에 로그인한 뒤 코드를 입력하고 `승인` 을 누릅니다.

| 명령 | 받는 것 |
|---|---|
| `icrap login` | **읽기 토큰**(90일): 클러스터·내 잡·로그·내 워크스페이스 조회 |
| `icrap login --ssh` | 읽기 토큰 + **Coder 세션**: 워크스페이스 SSH(명령 실행·파일 주고받기). 승인 화면에 경고가 보입니다 |
| `icrap login --paste` | 관리자가 발급한 **쓰기 토큰**(잡 제출·취소, 워크스페이스 시작·정지). **직접 내 터미널에서** 실행합니다 |

- **직접 실행한(또는 Claude 가 방금 알려 준) 로그인의 코드만 승인하세요.** 남이 보내 준 코드를 승인하면 그 사람이 내 계정을 쓰게 됩니다.
- `--ssh` 세션은 내 워크스페이스 전체를 조작(셸 접속 포함)할 수 있는 권한입니다. 7일 동안 유효하고 쓸 때마다 연장됩니다.
- `icrap me` 로 계정, 토큰별 스코프·만료, SSH 세션, 할 수 있는 일을 봅니다. `icrap logout`(`--read`·`--write`·`--ssh`)은 이 컴퓨터에서 지웁니다.
  토큰 자체를 무효로 하려면 포털 → `계정` → `API 토큰` 에서 폐기합니다.
- 토큰·세션을 Claude Code 대화창에 붙여 넣지 마세요(대화 기록에 남습니다). 붙여 넣었다면 폐기하고 새로 받으세요.

## Claude 가 하는 일과 하지 않는 일

- `icrap` 이 없으면 알리고 설치하고, 로그인이 필요하면 `icrap login`(SSH 가 필요하면 `--ssh`)을 실행해 주소·코드를 알려 준 뒤 승인을 기다립니다.
- push, 잡 취소, 워크스페이스 정지, 큰 패키지 설치는 사용자에게 확인을 받은 뒤에 합니다.
- 처음 돌리는 코드는 짧은 시험 실행을 먼저 보내고, 잡 상태는 30초보다 짧은 간격으로 묻지 않으며, 워크스페이스 실행에는 항상 시간 제한을 둡니다.
- 토큰·세션 원문을 읽거나 출력하지 않고, `icrap login --paste` 를 대신 실행하지 않습니다. 출력에 토큰이 보이면 폐기를 권합니다.

## 관리

이 저장소는 ICRAP 플랫폼 저장소(비공개)의 `skills/` 를 내보낸 것입니다. 고칠 때는 원본을 고치고, CLI(`icrap --help`)와
연구원 문서(`/docs` 의 API·배치 잡·터미널 접속)와 맞춘 뒤 실제 계정으로 조회·잡 제출·워크스페이스 실행까지 확인해 내보냅니다.

# ICRAP Claude Code 스킬

연구팀 GPU 자원 플랫폼 **ICRAP**(`https://icrap.blueodor.xyz`)을 Claude Code 가 대신 쓰게 하는 스킬 모음입니다.

| 스킬 | 하는 일 |
|---|---|
| `icrap` | 배치 잡 제출·대기·취소·로그 읽기, 클러스터 GPU 현황, 워크스페이스 시작·정지 |
| `icrap-run` | 로컬 코드를 배치 잡이나 워크스페이스에서 돌리고, 로그·지표를 검토하고, 고쳐서 다시 돌리는 반복 |

설치한 뒤에는 Claude Code 에 이렇게 말하면 됩니다.

- "ICRAP 에 지금 빈 GPU 있어?"
- "이 저장소의 train.py 를 GPU 에서 3 에폭만 돌려 보고 학습이 제대로 되는지 검토해 줘"
- "내 워크스페이스에서 테스트 돌려 보고 실패하면 고쳐 줘"

## 설치

```bash
git clone https://github.com/loopin51/icrap-skill.git ~/icrap-skill
mkdir -p ~/.claude/skills
ln -s ~/icrap-skill/icrap ~/icrap-skill/icrap-run ~/.claude/skills/   # 갱신은 git pull 로
```

한 프로젝트에서만 쓰려면 `<프로젝트>/.claude/skills/` 에 복사합니다. 두 스킬을 **함께** 설치하세요(`icrap-run` 이 `icrap` 의 클라이언트를 씁니다).
Python 3.8 이상만 있으면 되고 추가 패키지는 없습니다.

### 로그인(API 토큰)

Claude Code 는 내 계정의 API 토큰으로 ICRAP 을 씁니다.

1. 포털 → `계정` → `API 토큰` 에서 **읽기 토큰**을 발급합니다. 조회(클러스터, 내 잡·로그, 내 워크스페이스)는 이것으로 충분합니다.
2. 터미널에서 로그인합니다. 토큰은 화면에 보이지 않게 입력받고, 포털에 확인한 뒤 `~/.config/icrap/` 에 권한 600 으로 저장합니다.

   ```bash
   python3 ~/.claude/skills/icrap/scripts/icrap.py login
   python3 ~/.claude/skills/icrap/scripts/icrap.py me     # 계정, 토큰별 스코프·만료, 할 수 있는 일
   ```

3. 잡 제출·취소, 워크스페이스 시작·정지까지 맡기려면 **관리자에게 쓰기 토큰**(`jobs:write`, `workspaces:write`)을 요청합니다.
   받은 토큰도 같은 `login` 으로 입력하면 쓰기 토큰 자리에 따로 저장되고, 쓰기 작업에만 쓰입니다.

토큰을 Claude Code 대화창에 붙여 넣지 마세요(대화 기록에 남습니다). 지우려면 `icrap.py logout`, 무효로 하려면 포털에서 폐기합니다.
CI 에서는 `ICRAP_TOKEN` 환경 변수를 쓸 수 있습니다. 포털 주소는 기본으로 `https://icrap.blueodor.xyz` 이고 `ICRAP_URL` 로 바꿀 수 있습니다.

### 워크스페이스까지 쓰려면: coder CLI(SSH)

배치 잡만 쓴다면 필요 없습니다. Claude Code 가 워크스페이스에 SSH 로 붙어 코드를 돌리려면 coder CLI 를 설치하고
**직접** 로그인합니다. 공개 주소로 되므로 Tailscale 은 필요 없습니다.

```bash
mkdir -p ~/.local/bin && curl -fsSL -o ~/.local/bin/coder https://coder.blueodor.xyz/bin/coder-linux-amd64 && chmod +x ~/.local/bin/coder
# 포털에서 워크스페이스 '열기' 를 한 번 누른 뒤
coder login https://coder.blueodor.xyz           # 브라우저에 나온 세션 토큰을 이 터미널에 붙여 넣습니다
python3 ~/.claude/skills/icrap-run/scripts/ws.py check
```

세션 토큰은 워크스페이스 셸 권한입니다. Claude Code 대화창에 붙여 넣지 마세요. 자세한 절차(맥·윈도)는
[`icrap/reference.md`](icrap/reference.md#coder-cli-준비) 에 있습니다.

## 안전장치

- 토큰 원문은 출력·저장·커밋하지 않습니다.
- push, 잡 취소, 워크스페이스 정지, 큰 패키지 설치는 사용자에게 확인을 받은 뒤에 합니다.
- 잡 상태는 30초보다 짧은 간격으로 묻지 않고, 워크스페이스 실행에는 항상 시간 제한을 둡니다.
- Coder 세션 토큰을 읽거나 출력하지 않습니다. 로그인(`coder login`)은 사용자가 합니다.

## 관리

이 저장소는 ICRAP 플랫폼 저장소(비공개)의 `skills/` 를 내보낸 것입니다. 고칠 때는 원본을 고치고, API·잡 규칙 문서
(`docs/api.md`·`docs/researcher-jobs.md`·`docs/researcher-cli.md`)와 맞춘 뒤, 실제 토큰으로 `me`·`cluster`·`jobs` 를
돌리고 쓰기 경로를 바꿨다면 임시 계정으로 잡 제출·취소까지 확인해 내보냅니다.

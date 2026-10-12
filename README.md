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

### API 토큰

포털 → `계정` → `API 토큰` 에서 읽기 토큰을 발급합니다. 잡 제출·워크스페이스 시작·정지까지 맡기려면 관리자에게
쓰기 토큰(`jobs:write`·`workspaces:write`)을 요청합니다. 토큰은 파일이나 환경 변수로 줍니다.

```bash
mkdir -p ~/.config/icrap && (umask 077; printf '%s\n' 'rp_...' > ~/.config/icrap/token)
python3 ~/.claude/skills/icrap/scripts/icrap.py me     # 계정·스코프·만료일이 나오면 됩니다
```

`ICRAP_TOKEN` 환경 변수도 됩니다. 포털 주소는 기본으로 `https://icrap.blueodor.xyz` 이고 `ICRAP_URL` 로 바꿀 수 있습니다.

### 워크스페이스까지 쓰려면: coder CLI

배치 잡만 쓴다면 필요 없습니다. 워크스페이스에서 코드를 돌리려면 Tailscale 연결과 coder CLI 로그인이 필요합니다.
절차는 [`icrap/reference.md`](icrap/reference.md#coder-cli-준비) 에 있습니다.

## 안전장치

- 토큰 원문은 출력·저장·커밋하지 않습니다.
- push, 잡 취소, 워크스페이스 정지, 큰 패키지 설치는 사용자에게 확인을 받은 뒤에 합니다.
- 잡 상태는 30초보다 짧은 간격으로 묻지 않고, 워크스페이스 실행에는 항상 시간 제한을 둡니다.

## 관리

이 저장소는 ICRAP 플랫폼 저장소(비공개)의 `skills/` 를 내보낸 것입니다. 고칠 때는 원본을 고치고, API·잡 규칙 문서
(`docs/api.md`·`docs/researcher-jobs.md`·`docs/researcher-cli.md`)와 맞춘 뒤, 실제 토큰으로 `me`·`cluster`·`jobs` 를
돌리고 쓰기 경로를 바꿨다면 임시 계정으로 잡 제출·취소까지 확인해 내보냅니다.

# HAM 에이전트 스킬

한국어 · [English](../skill-guide.md) · [README](../../README.ko.md)

HAM을 사용하면 팝업을 열지 않고도 Codex와 Claude Code에서 현재 Herdr
에이전트로 프롬프트를 전달할 수 있습니다. 번들 스킬의 정식 이름은
`herdr-agent-messenger`이며 **HAM**은 짧은 사용자 표시 이름입니다.

## 플러그인과 함께 설치

플러그인에는 다음 항목이 포함됩니다.

- Codex: `.agents/skills/herdr-agent-messenger`
- Claude Code: `.claude/skills/herdr-agent-messenger`

저장소 체크아웃은 프로젝트 범위에서 자동으로 발견됩니다. 모든 workspace에서
사용하려면 Herdr 명령 팔레트에서 **HAM Skill**을 열고 Codex 또는 Claude 대상을
**System** 범위로 설치하세요. **Project** 범위는 현재 Herdr workspace에만
적용됩니다.

Agent Messenger에서 `Ctrl+G`를 눌러 같은 설치 화면을 열 수 있고, `?`를 누르면
호출 가이드를 볼 수 있습니다. 상태 배지의 의미는 다음과 같습니다.

- `✓` 최신 상태
- `↑` 갱신 가능
- `○` 미설치
- `!` 충돌 파일 존재

설치기는 같은 이름의 관련 없는 스킬 디렉터리를 덮어쓰지 않습니다. 새 스킬이
보이지 않으면 에이전트 세션을 새로 시작하세요.

셸에서도 설치 화면을 열 수 있습니다.

```bash
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

체크아웃 또는 설치된 플러그인 루트에서 번들 스킬 경로를 출력하려면 다음 명령을
사용합니다.

```bash
python3 agent_messenger.py skill-path
```

## HAM 호출

Codex CLI와 IDE 확장에서는 `$` mention을 사용합니다. `$ham`을 입력한 뒤 스킬
선택기에서 **HAM — Herdr Agent Messenger**를 선택하세요. `$ham`은 검색어이며
정식 스킬 이름은 계속 `herdr-agent-messenger`입니다.

Claude Code는 자연어 요청에 맞춰 스킬을 자동 선택할 수 있습니다. 명시적 호출
문법은 `/herdr-agent-messenger`이며 `$ham`은 Claude 명령이 아닙니다.

항상 호스트가 포함된 정확한 Agent Labels 값을 사용하세요.

```text
$ham local/yellow-falcon에게 현재 변경을 검토해달라고 요청해.
응답을 기다린 뒤 필요한 후속 작업을 정리해줘.
```

리터럴 호스트 `local`만 현재 Herdr 서버를 뜻합니다. 나머지 호스트는 모두
명시적인 SSH 별칭이어야 합니다. 호스트 없이 라벨만 사용하면 다른 호스트와
충돌하거나 AI 클라이언트 자체 서브에이전트로 오인될 수 있습니다.

## 요청 수명 주기

번들 도우미는 `list`, `status`, `send`, `batch`, `read`, `request`,
`request-status`를 지원합니다. 일반 작업에는 `request`를 권장합니다. 현재
수신자를 확인하고 프롬프트를 한 번만 제출한 뒤 새 turn을 관찰해 제한된 크기의
출력을 반환합니다.

시간이 초과됐지만 종료되지 않은 요청을 자동으로 전송 실패로 판단하면 안 됩니다.
요청 ID를 보관하고 다음 명령으로 이어서 확인하세요.

```bash
python3 herdr_agent_messenger.py request-status --request-id <request-id>
```

저장된 요청이 종료 상태가 되기 전에는 다시 보내지 마세요. 배치 결과는 입력 순서를
유지하며 `succeeded`, `submitted`, `failed`, `timeout`, `cancelled`로
보고됩니다. `submitted`는 프롬프트 접수는 확인됐지만 완료되지 않은 상태이고,
`timeout`은 접수 여부를 확인하지 못한 상태입니다.

`list`는 기본적으로 `address`, `status`, `workspace`만 반환합니다. 전체
정보는 `--verbose`를 사용하세요. `read`는 `--max-bytes`와 반환된
`--cursor`를 지원합니다. 터미널이 다시 그려져 cursor를 안전하게 쓸 수 없으면
추측하지 않고 현재 화면을 제한된 크기로 반환합니다.

## 플러그인 없이 HAM 사용

HAM 플러그인을 설치하거나 활성화하지 않고 Herdr와 HAM 스킬만 사용할 수 있습니다.
현재 단독 설치는 소스 기반입니다. 스킬 래퍼가 저장소의 라우터 모듈을 불러오므로
지속적으로 유지할 체크아웃이 필요합니다. 스킬 디렉터리만 복사하는 방식은 아직
독립 실행형 설치가 아닙니다.

```bash
git clone https://github.com/zerodice0/herdr-agent-labels.git \
  "$HOME/.local/share/ham"
mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills"
ln -s "$HOME/.local/share/ham/.agents/skills/herdr-agent-messenger" \
  "$HOME/.agents/skills/herdr-agent-messenger"
ln -s "$HOME/.local/share/ham/.claude/skills/herdr-agent-messenger" \
  "$HOME/.claude/skills/herdr-agent-messenger"
```

갱신 방법:

```bash
git -C "$HOME/.local/share/ham" pull --ff-only
```

플러그인 없는 HAM에서도 라벨 기반 요청·대기·읽기·배치 라우팅은 동작합니다.
하지만 팝업, 명령 팔레트 설치기, 자동 라벨, agent-detected hook은 제공하지
않습니다. 수신자 이름은 직접 고유하게 지정해야 합니다.

```bash
herdr api snapshot
herdr agent rename <pane-id> yellow-falcon
```

로컬과 선택할 모든 SSH 호스트에 Herdr가 설치돼 실행 중이어야 합니다. 원격
호스트는 `~/.ssh/config`의 명시적인 별칭이어야 합니다.

# HAM 에이전트 스킬

한국어 · [English](../skill-guide.md) · [README](../../README.ko.md)

HAM은 기존 Herdr 에이전트로 메시지를 보내고 응답을 수집하며, `spawn`으로 새
에이전트 세션도 시작할 수 있습니다. Codex, Claude Code, omp에서 사용할 수 있고,
번들 스킬의 정식 이름은 `herdr-agent-messenger`입니다. **HAM**은 짧은 사용자
표시 이름입니다.

## 설치와 클라이언트별 호출

플러그인에는 Codex용 `.agents/skills/herdr-agent-messenger`와 Claude Code용
`.claude/skills/herdr-agent-messenger`가 포함됩니다. 저장소 체크아웃에서는 각
클라이언트가 프로젝트 스킬을 발견합니다. omp는 아래 설치기로 설치하세요.

모든 workspace에서 사용하려면 Herdr 명령 팔레트에서 **HAM Skill**을 열고
Codex, Claude 또는 omp 대상을 **System** 범위로 설치하세요. **Project** 범위는
현재 Herdr workspace에만 적용됩니다. 설치 경로는 다음과 같습니다.

| 클라이언트 | System 경로 | Project 경로 |
| --- | --- | --- |
| Codex | `~/.agents/skills/herdr-agent-messenger` | `<root>/.agents/skills/herdr-agent-messenger` |
| Claude Code | `~/.claude/skills/herdr-agent-messenger` | `<root>/.claude/skills/herdr-agent-messenger` |
| omp | `~/.omp/agent/skills/herdr-agent-messenger` | `<root>/.omp/skills/herdr-agent-messenger` |

Agent Messenger에서 `Ctrl+G`를 눌러 같은 설치 화면을 열 수 있고, `?`를 누르면
호출 가이드를 볼 수 있습니다. 상태 배지의 의미는 다음과 같습니다.

- `✓`는 최신 상태입니다.
- `↑`는 갱신할 수 있는 상태입니다.
- `○`는 설치되지 않은 상태입니다.
- `!`는 충돌하는 파일이 있는 상태입니다.

설치기는 같은 이름의 관련 없는 스킬 디렉터리를 덮어쓰지 않으며, 관리 대상 파일의
경로에 심볼릭 링크가 있으면 교체를 중단합니다. 새 파일을 임시 디렉터리에 모두
복사한 뒤 기존 설치를 교체하므로 복사가 실패해도 이전 설치를 유지합니다.
교체가 실패하면 이전 설치로 복구하며, 복구까지 실패하면 오류에 보존한 백업 경로를
표시합니다. 사용자가 추가한 파일은 유지하고 바이트코드와 `.DS_Store`는 제외합니다.
새 스킬이 보이지 않으면 에이전트 세션을 새로 시작하세요.

셸에서도 설치 화면을 열 수 있습니다.

```bash
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

체크아웃 또는 설치된 플러그인 루트에서는 다음 명령으로 번들 스킬 경로를 확인하고
System 범위로 설치할 수 있습니다. 설치 대상은 `codex`, `claude`, `omp`, `all`이며,
`all`은 세 클라이언트 모두를 설치합니다.

```bash
python3 agent_messenger.py skill-path
python3 agent_skill_installer.py install omp
python3 agent_skill_installer.py install all
```

설치기는 스킬 파일을 복사합니다. 플러그인이 Herdr에 등록되어 있지 않다면 복사한
스킬만으로 체크아웃을 찾을 수 없으므로 아래의
[플러그인 없는 설치 방법](#플러그인-없이-ham-사용)에 따라 심볼릭 링크를 사용하세요.

클라이언트별 호출 방법은 다음과 같습니다.

- **Codex CLI와 IDE 확장**에서는 `$ham`을 입력한 뒤 스킬 선택기에서
  **HAM — Herdr Agent Messenger**를 선택하세요. `$ham`은 검색어이며 정식 스킬
  이름은 계속 `herdr-agent-messenger`입니다.
- **Claude Code**에서는 자연어 요청으로 스킬을 자동 선택하거나
  `/herdr-agent-messenger`로 명시적으로 호출하세요. `$ham`은 Claude 명령이 아닙니다.
- **omp**에서는 위 경로에 설치한 뒤 자연어로 HAM 작업을 요청하거나
  `skill://herdr-agent-messenger`를 읽도록 지시하세요.

```text
$ham local/yellow-falcon에게 현재 변경을 검토해달라고 요청해.
응답을 기다린 뒤 필요한 후속 작업을 정리해줘.
```

## 주소 선택과 새 세션 생성

항상 호스트가 포함된 정확한 Agent Labels 주소를 사용하세요. 리터럴 호스트
`local`만 현재 Herdr 서버를 뜻합니다. 나머지 호스트는 모두 설정된 SSH 파일의
명시적인 `Host` 별칭이어야 합니다. 현재 기기 이름과 같더라도 `local`이 아니면
SSH로 처리합니다. 라벨만 사용하면 다른 호스트와 충돌하거나 AI 클라이언트 자체
서브에이전트로 오인될 수 있습니다.

기존 에이전트에는 `list`로 확인한 `address`를 그대로 전달합니다. 아래 예시는
저장소 또는 설치된 플러그인 루트에서 `HAM_CLI`를 절대 경로로 설정한 뒤 실행합니다.
작업 디렉터리를 바꾸더라도 같은 경로를 사용하세요.

```bash
HAM_CLI="$PWD/.agents/skills/herdr-agent-messenger/scripts/herdr_agent_messenger.py"
python3 "$HAM_CLI" list --host local
python3 "$HAM_CLI" list --host macbook-pro
python3 "$HAM_CLI" status --address macbook-pro/purple-koala
python3 "$HAM_CLI" request --address macbook-pro/purple-koala \
  --message '현재 작업을 검토하고 막힌 부분을 알려주세요.' --timeout 120000
```

`list` 결과의 `address`는 `status`, `send`, `read`, `request`의 `--address`에
바로 사용할 수 있고, 배치에서는 `{"address":"host/label","message":"..."}`로
사용할 수 있습니다. 호스트나 라벨이 없거나 모호하면 그 사실을 보고하세요.
라벨을 추측하거나 다른 에이전트로 대체하지 마세요. 누락된 라벨을 찾았다는 이유만으로
새 세션을 만들지 말고, 사용자가 생성을 요청한 경우에만 만드세요.

사용자가 새 에이전트 세션을 시작하거나 열어서 메시지를 보내라고 요청하면 먼저
`spawn`을 사용한 뒤 반환된 `address`로 `request`를 실행하세요. 직접
`herdr agent start <name>`을 실행하면 HAM의 라벨 선택과 메타데이터 처리를
우회하므로 이 작업의 대안으로 사용하지 마세요.

```bash
python3 "$HAM_CLI" spawn --kind omp --cwd /path/to/project --placement tab \
  -- --model anthropic/claude-haiku-5-5
# spawn 결과의 address를 그대로 사용합니다.
python3 "$HAM_CLI" request --address local/yellow-heron \
  --message '이 프로젝트의 현재 변경을 검토하고 결과를 알려주세요.'
```

위 `local/yellow-heron`은 예시입니다. 실제 반환값이 다르면 실제 값을 사용하세요.
`spawn`은 기본적으로 사용 중이지 않은 HAM `color-animal` 라벨을 선택하고 색상
메타데이터를 보고합니다. `--label`로 명시한 이름을 사용할 수도 있습니다.

GUI에서 선택한 수신자는 라벨이 없을 수도 있으므로 GUI가 제공한 절대 CLI 경로와
불투명한 `--route` token을 그대로 사용하세요. `status`, `spawn` 및 요청 결과의
`route`도 후속 작업에 사용할 수 있습니다. 수신자 확인에 성공한 요청 결과는
최상위 `route`와 `recipient.route`를 제공할 수 있습니다. token을 해독하거나
수정하거나 추측한 `herdr` 명령으로 바꾸지 마세요. `route_refreshed: true`이면
이후 작업에 반환된 최신 `route`를 사용하세요. 각 작업은 현재 점유자를 다시
확인하므로 에이전트가 재시작되어도 같은 라벨이 같은 세션이라고 가정하지 않습니다.
자세한 연속성 규칙은 [SSH 및 라우팅](ssh-and-routing.md)을 참고하세요.

## CLI 전체 참고서

하위 명령은 `list`, `status`, `send`, `batch`, `read`, `request`,
`request-status`, `spawn`의 8개입니다. 모든 하위 명령은 `-h` 또는 `--help`로
도움말을 표시합니다. 일반적인 단일 작업에는 하위 수준의 `send`보다 `request`를
권장합니다.

### 공통 수신자 옵션

`status`, `send`, `read`, `request`에 다음 옵션이 공통으로 적용됩니다.

| 옵션 | 기본값과 규칙 |
| --- | --- |
| `--host HOST` | 기본값은 `local`입니다. 원격 호스트는 설정된 명시적 SSH 별칭이어야 합니다. |
| `--address HOST/LABEL` | `list` 또는 `spawn`이 반환한 정확한 주소를 지정합니다. 기본값은 없습니다. |
| `--label LABEL` | `--host`에서 현재 사용 중인 정확한 Agent Labels 값을 지정합니다. 기본값은 없습니다. |
| `--route TOKEN` | HAM이 반환한 불투명한 route token을 지정합니다. 기본값은 없습니다. token에 포함된 호스트로 연결합니다. |

`--address`, `--label`, `--route` 중 정확히 하나가 필수이며 함께 지정할 수
없습니다. `--address`를 사용하면 주소의 호스트가 적용됩니다. 기본값이 아닌
`--host`까지 지정했는데 주소의 호스트와 다르면 `conflicting_address`가 발생합니다.

### `list`

```bash
python3 "$HAM_CLI" list --host local
```

| 옵션 | 기본값과 규칙 |
| --- | --- |
| `--host HOST` | 기본값은 `local`입니다. 지정한 호스트의 현재 라벨이 있는 에이전트를 나열합니다. |
| `--verbose` | 기본적으로 꺼져 있습니다. 전체 AgentRecord 호환 정보를 포함합니다. |
| `--legacy` | `--verbose`와 동일하게 동작하는 기존 소비자용 별칭입니다. 기본적으로 꺼져 있습니다. |

기본 결과는 `{"host":"local","agents":[...]}`이며 각 항목은 `address`,
`status`, `workspace`를 포함하는 간결한 정보입니다. 전체 정보가 필요할 때만
`--verbose`를 사용하세요.

### `status`

```bash
python3 "$HAM_CLI" status --address local/yellow-falcon
python3 "$HAM_CLI" status --route ROUTE_TOKEN --verbose
```

공통 수신자 옵션 `--host`, `--address`, `--label`, `--route`를 받습니다.
추가 옵션 `--verbose`는 기본적으로 꺼져 있으며, 켜면 `agent`에 전체 AgentRecord
호환 정보를 포함합니다. 결과에는 `agent`, `route_refreshed`, 현재 `route`가
포함됩니다. 호스트 전체를 다시 나열하지 않고 선택한 수신자의 상태를 확인합니다.

### `send`

```bash
python3 "$HAM_CLI" send --address local/yellow-falcon \
  --message '현재 상태를 알려주세요.' --no-wait
```

공통 수신자 옵션 `--host`, `--address`, `--label`, `--route`를 받습니다.

| 옵션 | 기본값과 규칙 |
| --- | --- |
| `--message TEXT` | 필수입니다. 공백만 있는 메시지는 허용하지 않습니다. |
| `--wait` | 기본값입니다. Herdr의 완료 신호를 기다립니다. |
| `--no-wait` | 접수 후 완료를 기다리지 않고 반환합니다. `--wait`와 함께 사용할 수 없습니다. |
| `--timeout MS` | 기본값은 `120000`밀리초이며 0보다 큰 정수여야 합니다. `--wait`의 대기 제한입니다. |

성공 결과에는 `sent`, `recipient`, `waited`, `route_refreshed`, `route`,
`warnings`가 포함됩니다. `--wait`에서는 `wait_can_track_submitted_turn`도
반환합니다. 수신자가 이미 작업 중이면 `recipient_already_working` 경고와
`wait_can_track_submitted_turn: false`가 반환될 수 있습니다. 이 경우 Herdr의
완료 신호만으로 새 요청의 완료를 판단할 수 없습니다. `send`는 수명 주기
`request_id`나 응답 본문을 제공하지 않으므로 안전한 요청 추적에는 `request`를
사용하세요. 메시지의 앞뒤 공백을 제거하고 `Message from host/label:` 헤더를 붙여
전달합니다.

### `request`

```bash
python3 "$HAM_CLI" request --address macbook-pro/purple-koala \
  --message '현재 변경을 검토하고 결과를 알려주세요.' \
  --timeout 120000 --output-lines 120 --output-chars 12000
```

공통 수신자 옵션 `--host`, `--address`, `--label`, `--route`를 받습니다.

| 옵션 | 기본값과 규칙 |
| --- | --- |
| `--message TEXT` | 필수입니다. 공백만 있는 메시지는 허용하지 않습니다. |
| `--timeout MS` | 기본값은 `120000`밀리초이며 0보다 큰 정수여야 합니다. 제출 후 수명 주기를 관찰하는 대기 제한입니다. |
| `--output-lines N` | 기본값은 `120`줄이며 0보다 큰 정수여야 합니다. 반환할 응답의 최대 줄 수입니다. |
| `--output-chars N` | 기본값은 `12000`자이며 0보다 큰 정수여야 합니다. 반환할 응답의 최대 문자 수이며 바이트 수가 아닙니다. |

`HERDR_PANE_ID`로 송신자를 확인할 수 있도록 코디네이터의 활성 Herdr 에이전트
pane에서 실행하세요. 수신자를 확인하고 기준 화면을 수집한 뒤 프롬프트를 한 번만
제출합니다. Herdr의 모호한 `--wait`에 의존하지 않고 새 작업 시작과 종료를
관찰하며, 기준 화면 이후 출력을 지정한 한도 안에서 반환합니다. 수신자가 이미
작업 중이었다면 첫 종료는 기존 turn의 경계로만 취급하고 그 다음 작업 시작과
종료를 확인해야 새 요청을 완료로 판정합니다.

### `request-status`

```bash
python3 "$HAM_CLI" request-status --request-id REQUEST_ID
```

`--request-id ID`가 필수이며 기본값은 없습니다. `request` 또는 배치 수명 주기
결과에서 받은 32자리 소문자 16진수 ID를 그대로 전달하세요. 저장된 원자적 상태를
읽고, 종료되지 않은 요청이면 현재 수신자를 한 번 관찰해 상태를 진전시킵니다.
프롬프트를 다시 보내거나 새 대기 루프를 시작하지 않습니다. 계속 진행 중이면 같은
ID로 나중에 다시 확인하세요. 종료 상태이면 저장된 결과를 그대로 반환합니다.

요청 상태는 같은 실행 환경의 로컬 저장소에 보관됩니다.
`HERDR_AGENT_REQUEST_STATE_DIR`로 경로를 지정할 수 있으며, 기본적으로
`HERDR_PLUGIN_STATE_DIR/requests` 또는 XDG 상태 경로의
`herdr-agent-messenger/requests`를 사용합니다. 이전 플러그인의 요청 저장소가
있으면 해당 저장소를 이어서 사용할 수 있습니다. 다른 환경에서 조회해
`request_not_found`가 발생했다고 해서 미전달로 판단하지 마세요.

### `batch`

```bash
python3 "$HAM_CLI" batch \
  --requests-json '[{"address":"local/yellow-falcon","message":"변경된 코드를 검토해주세요."},{"route":"ROUTE_TOKEN","message":"관련 문서를 검토해주세요."}]' \
  --wait --timeout 120000 --max-workers 4
```

| 옵션 | 기본값과 규칙 |
| --- | --- |
| `--requests-json JSON` | 필수입니다. 비어 있지 않은 JSON 배열 또는 `{"requests":[...]}` 객체를 받습니다. `-`를 지정하면 표준 입력에서 읽습니다. |
| `--wait` | 기본값입니다. 각 요청의 수명 주기를 관찰합니다. |
| `--no-wait` | 접수 후 완료를 관찰하지 않고 반환합니다. `--wait`와 함께 사용할 수 없습니다. |
| `--timeout MS` | 기본값은 `120000`밀리초이며 0보다 큰 정수여야 합니다. 전체 배치가 아니라 각 요청의 대기 제한입니다. |
| `--max-workers N` | 기본값은 `4`이며 `1`부터 `8`까지의 정수여야 합니다. 동시에 전송할 요청 수의 상한입니다. |

각 항목은 비어 있지 않은 문자열 `message`와 `address` 또는 `route` 중 정확히
하나를 포함해야 합니다. 같은 에이전트에 주소와 token을 각각 사용한 경우도
실제 수신자 identity를 기준으로 중복을 탐지하여 `duplicate_route`로 거부합니다.
CLI는 이미 작성된 개별 지시를 제한된 동시성으로 전달할 뿐, 요청을 의미적으로
분해하거나 메시지를 고쳐 쓰지 않습니다. 결과는 완료 순서가 아니라 입력 순서를
유지합니다.

`--wait`에서 수명 주기에 진입한 항목은 `request_id`와 제한된 `response`를
포함합니다. 사전 검증에 실패한 항목과 `--no-wait` 결과에는 요청 ID가 없을 수
있습니다. `submitted` 항목은 `request-status`로 이어서 확인하고 다시 보내지
마세요. 배치 응답의 필드와 종료 코드 해석은 아래 표를 참고하세요.

### `read`

```bash
python3 "$HAM_CLI" read --address macbook-pro/purple-koala \
  --lines 160 --max-bytes 65536
python3 "$HAM_CLI" read --address macbook-pro/purple-koala \
  --lines 160 --max-bytes 65536 --cursor PREVIOUS_CURSOR
```

공통 수신자 옵션 `--host`, `--address`, `--label`, `--route`를 받습니다.

| 옵션 | 기본값과 규칙 |
| --- | --- |
| `--lines N` | 기본값은 `120`줄이며 0보다 큰 정수여야 합니다. 최근 출력에서 읽을 최대 줄 수입니다. |
| `--max-bytes N` | 기본값은 `65536`바이트이며 0보다 큰 정수여야 합니다. 반환할 UTF-8 출력의 최대 바이트 수입니다. |
| `--cursor TOKEN` | 기본값은 없습니다. 이전 `read`가 반환한 불투명한 `cursor`를 전달하면 안전하게 계산할 수 있는 경우 변경분만 반환합니다. |
| `--watermark TOKEN` | `--cursor`와 같은 옵션의 별칭이며 기본값은 없습니다. |

결과에는 `address`, `output`, `truncated`, `delta`, `cursor_status`, `cursor`,
`route_refreshed`, `route`가 포함됩니다. 터미널은 추가 전용 로그가 아니라 다시
그려지는 화면일 수 있으므로 줄 번호로 진행 상황을 추측하지 마세요.
`cursor_status: expired`이면 `delta`는 `false`이며 현재 화면을 제한된 크기로
다시 반환합니다. 안전하지 않은 변경분을 추측하지 않습니다. `truncated: true`이면
이전 출력의 일부가 생략되었다고 보고하세요.

### `spawn`

```bash
python3 "$HAM_CLI" spawn --kind codex --cwd /path/to/project --placement workspace
python3 "$HAM_CLI" spawn --kind omp --host macbook-pro \
  --cwd /remote/project --placement split --from-pane REMOTE_PANE --direction down \
  -- --model anthropic/claude-haiku-5-5
```

| 옵션 | 기본값과 규칙 |
| --- | --- |
| `--kind KIND` | 필수입니다. `codex`, `claude`, `omp` 등 대상 Herdr가 지원하는 에이전트 종류를 지정합니다. 공백 없는 비어 있지 않은 token이어야 합니다. |
| `--host HOST` | 기본값은 `local`입니다. 원격 호스트는 명시적인 SSH 별칭이어야 합니다. |
| `--cwd PATH` | 로컬 기본값은 현재 작업 디렉터리입니다. SSH 호스트에서는 필수이며 원격 경로를 지정합니다. |
| `--placement split\|tab\|workspace` | 기본값은 `split`입니다. 분할 pane, 새 tab 또는 새 workspace를 만듭니다. |
| `--from-pane PANE` | 원본 pane을 지정합니다. 로컬 `split`에서는 생략 시 `HERDR_PANE_ID`를 사용합니다. 원격 `split`에서는 필수입니다. `tab`에서는 workspace를 찾는 데 사용할 수 있습니다. |
| `--direction right\|down` | 기본값은 `right`이며 `split`의 방향을 지정합니다. |
| `--workspace WS` | 새 `tab`을 만들 workspace를 지정합니다. 생략 시 원본 pane에서 찾고, 원본 pane도 없으면 Herdr의 기본 대상을 사용합니다. |
| `--workspace-label TEXT` | 새 `tab` 또는 `workspace`의 표시 이름을 지정합니다. 생략 시 명시한 `--label`을 사용하며, 둘 다 없으면 시작 후 자동 HAM 라벨로 이름을 맞춥니다. |
| `--label LABEL` | 기본적으로 사용 중이지 않은 HAM `color-animal` 라벨을 선택합니다. 직접 지정할 때는 비어 있지 않고 `/`를 포함하지 않아야 합니다. |
| `--timeout MS` | 기본값은 `90000`밀리초이며 `1`부터 `300000`까지의 정수여야 합니다. 대화형 에이전트의 준비 완료를 기다리는 제한입니다. |
| `-- AGENT_ARGS...` | 선택 사항입니다. `--` 뒤의 인수를 대화형 에이전트에 전달합니다. HAM 옵션은 구분자 앞에 두세요. |

성공 결과에는 `address`, `label`, `marker`, `color`, `host`, `pane_id`,
`workspace_id`, `kind`, `cwd`, `route`, 간결한 `agent` 정보,
`label_metadata_reported`, `placement_label_reported`, `created`가 포함됩니다.
`tab_id`는 값이 있을 때만 포함됩니다. `created`는 `pane`, `tab`, `workspace`
중 하나입니다. HAM 팔레트에 없는 사용자 지정 라벨은 `marker`와 `color`가 빈
문자열이고 `label_metadata_reported`가 `false`일 수 있습니다. 이 필드나
`placement_label_reported`가 `false`여도 세션 생성 실패를 뜻하지는 않습니다.
실제 주소와 상태를 확인하세요.

생성 후 시작 단계가 실패하면 HAM은 자신이 만든 리소스를 닫으려고 시도하고 오류
메시지에 `cleanup` 결과를 포함합니다. 실패 시 무조건 다시 생성하지 말고 해당
리소스와 세션이 남았는지 먼저 확인하세요.

## 결과 계약과 종료 코드

### 요청 수명 주기

`request`와 `request-status`의 수명 주기 payload에는 `request_id`, `state`,
`phase`, `terminal`, `submitted`, `error`, `error_code`, `response`가
포함됩니다. `error`는 사람이 읽는 설명이고 `error_code`는 기계가 분기할 코드이며,
오류가 없으면 둘 다 `null`입니다. 수명 주기에 진입하기 전의 입력 검증이나 송신자
확인이 실패하면 `{"error":{"code":"...","message":"..."}}` 형태의 오류
envelope가 반환되고 `request_id`는 없습니다. 모든 명령 결과에 요청 ID가 있는
것은 아닙니다.

| `state` | 의미와 후속 조치 |
| --- | --- |
| `submission_failed` | 수신자 확인에 실패했거나 제출이 거부되었습니다. 원인을 고치고 미전달임을 확인한 뒤 재시도할 수 있습니다. |
| `submitted_working` | 요청을 제출했거나 제출했을 수 있으며 마지막으로 확인한 수신자는 작업 중입니다. 완료를 뜻하지 않습니다. `request-status`로 확인하세요. |
| `submitted_settled` | 새 요청의 작업 시작과 종료를 관찰했습니다. 응답 품질과 상관관계를 확인한 뒤 사용하세요. |
| `submitted_unknown` | 제출했거나 제출했을 수 있으나 해당 turn의 완료를 안전하게 확인하지 못했습니다. 재전송하지 말고 저장된 상태와 수신자를 확인하세요. |

`submitted`는 접수가 확인되면 `true`, 미제출 또는 거부가 확인되면 `false`, 접수
여부가 불확실하면 `null`입니다. `terminal`은 더 이상 자동 관찰로 진전시키지 않는
상태인지 나타냅니다. 보통 실패와 완료는 종료 상태이며, 진행 중과 불명 상태는 계속
조회할 수 있습니다. 단, 점유자가 바뀐 `phase: recipient_changed`는
`submitted_unknown`이면서 `terminal: true`입니다. 이때 기존 경로와 이미 수집한
출력만 보존하며 새 에이전트의 출력이나 경로를 이전 요청에 연결하지 않습니다.
종료 상태라는 이유만으로 원래 요청이 미전달이었다고 판단하지 마세요.

주요 관찰 단계는 `waiting_for_preexisting_turn`, `waiting_for_requested_turn`,
`waiting_for_requested_settlement`, `settled`, `wait_timed_out`,
`wait_cancelled`, `refresh_unavailable`, `recipient_changed`입니다.
`phase`는 진단 정보이고, 재전송 판단에는 `state`, `submitted`, `terminal` 및
`error_code`를 함께 사용해야 합니다.

응답 필드는 다음과 같이 해석합니다.

| 필드 | 의미 |
| --- | --- |
| `response.output` | 기준 화면 이후에서 수집한 제한된 텍스트입니다. 화면 연속성을 찾지 못하면 현재 화면 일부가 포함될 수 있습니다. |
| `response.truncated` | 줄·문자 한도로 출력이 잘렸거나, 기준 화면과의 연속성 또는 기준 화면 읽기의 신뢰성을 잃었음을 뜻합니다. 전체 응답이라고 단정하지 마세요. |
| `response.correlated` | 새 요청의 작업 시작과 종료를 관찰했고 기준 화면과 최종 읽기도 성공했음을 뜻합니다. 출력이 잘리지 않았거나 내용이 정확하다는 보장은 아닙니다. |
| `response.anchored` | 화면 겹침을 찾지 못했을 때 마지막 `Message from host/label:` 헤더를 찾아 그 위치부터 수집했음을 뜻합니다. 성공한 경우 `true`로 포함되며, 없으면 `false`로 취급하세요. 요청별 고유 ID로 응답을 인증한 것은 아닙니다. |
| `response.error` | 응답 화면 읽기에 실패했을 때 포함될 수 있는 설명입니다. 수명 주기의 최상위 `error_code`와 별도로 확인하세요. |

### 배치 결과

배치 결과는 `{"status":"...","results":[...]}`입니다. 각 항목에는 `route`와
`status`가 있고 필요에 따라 `error`, `detail`, `request_id`, `response`가
포함됩니다. 배치의 `error`는 보통 오류 코드이며 `detail`이 설명입니다. 수명 주기
제출 실패를 정규화한 일부 결과는 `error`에 사람이 읽는 설명이 들어갈 수 있으므로
항목에 요청 ID가 있으면 `request-status`의 `error_code`로 정확히 분기하세요.
배치의 `response`는 `output`, `truncated`, `correlated`를 제공하며 원본 수명
주기의 `anchored` 필드는 전달하지 않습니다.

| 항목 `status` | 의미와 후속 조치 |
| --- | --- |
| `succeeded` | 해당 요청의 완료를 확인했습니다. 응답을 검토하세요. |
| `submitted` | 접수는 확인했지만 이 실행에서 완료를 확인하지 못했습니다. `--no-wait`도 여기에 해당합니다. 요청 ID가 있으면 `request-status`로 이어서 확인하세요. |
| `failed` | 입력·주소 검증이나 제출이 실패했습니다. 해당 항목의 원인과 전달 여부를 확인한 뒤 미전달 항목만 재시도하세요. |
| `timeout` | 접수를 확인하지 못했거나 전송 호출이 시간 초과되었습니다. 미전달의 증거가 아니므로 자동으로 다시 보내지 마세요. |
| `cancelled` | 해당 항목이 취소되었습니다. 재시도 전 전달 여부를 확인하세요. 접수가 확인된 후 대기만 취소되면 `submitted`로 보고됩니다. |

| 전체 `status` | 의미 |
| --- | --- |
| `succeeded` | 모든 항목이 `succeeded` 또는 `submitted`입니다. 모두 전달되었다는 뜻이며 모두 완료되었다는 뜻은 아닙니다. |
| `partial` | 일부 항목만 `succeeded` 또는 `submitted`입니다. 각 항목을 개별적으로 처리하세요. |
| `failed` | `succeeded` 또는 `submitted`인 항목이 없습니다. 불명·시간 초과 항목까지 미전달로 단정하지 마세요. |

### 프로세스 종료 코드

| 종료 코드 | 의미와 후속 조치 |
| --- | --- |
| `0` | 성공입니다. `request`와 `request-status`는 `submitted_settled`이고, 배치는 모든 항목이 `succeeded`입니다. `list`, `status`, `read`, `send`, `spawn`은 정상 payload를 반환했다는 뜻이므로 특히 `send --no-wait`를 완료로 해석하지 마세요. |
| `1` | JSON 오류 envelope, `submission_failed` 또는 배치의 `failed`·`cancelled`·`timeout` 항목이 있습니다. 오류와 각 항목을 읽고 미전달이 확인된 경우에만 원인을 고쳐 재시도하세요. 배치 전체를 다시 보내지 마세요. |
| `2` | argparse의 사용법 오류입니다. 도움말을 보고 인수 형식이나 필수 옵션을 고치세요. 보통 표준 오류에 사용법이 출력되며 JSON 결과를 기대하면 안 됩니다. |
| `3` | 전달되었거나 전달되었을 수 있지만 완료를 확인하지 못했습니다. 요청은 `submitted_working` 또는 `submitted_unknown`이며, 배치는 실패 항목 없이 `submitted`가 남은 경우입니다. 재전송하지 말고 반환된 ID로 `request-status`를 실행하세요. `--no-wait`처럼 ID가 없는 경우에는 `status`와 `read`로 수신자를 확인하세요. |

시간 초과나 SSH 연결 종료는 접수 후에도 발생할 수 있습니다. 종료 코드 `1`도
무조건 재시도하라는 뜻이 아니며, 종료 코드 `3`은 전송 실패가 아닙니다.

## 오류 코드 참고서

아래 코드는 오류 envelope의 `error.code`, 수명 주기의 `error_code` 또는 배치
항목의 `error`에 나타납니다. 같은 명령을 그대로 반복하는 대신 발생 지점과
`submitted` 값을 확인하세요. 오류가 없을 때 수명 주기의 `error_code`는 `null`입니다.

### 입력과 대상 선택: 원인을 수정한 뒤 미전달 요청만 재시도합니다

| 코드 | 의미와 조치 |
| --- | --- |
| `invalid_address`, `conflicting_address`, `missing_address` | `HOST/LABEL` 형식과 수신자 옵션을 고치고 `--host` 충돌을 제거하세요. |
| `invalid_route`, `route_expired`, `route_ambiguous` | token이 잘못되었거나 안전한 점유자를 확인할 수 없습니다. `list`와 `status` 또는 GUI에서 대상을 다시 선택하세요. 진행 중 요청을 새 점유자로 바꾸지 마세요. |
| `host_not_configured` | 해당 호스트가 설정된 명시적 SSH 별칭이 아닙니다. 기존 설정에서 올바른 별칭을 찾으세요. |
| `agent_not_found`, `agent_ambiguous` | 정확한 현재 라벨을 확인할 수 없습니다. 성공한 탐색 결과로 사용자에게 보고하고 추측하지 마세요. 생성 요청이 없으면 `spawn`하지 마세요. |
| `empty_message`, `invalid_message` | 메시지가 비었거나 배치 메시지가 문자열이 아닙니다. 메시지를 고치세요. |
| `invalid_timeout` | 일반 요청·전송·배치는 양의 밀리초 정수여야 하며 `spawn`은 `1`부터 `300000`까지여야 합니다. |
| `invalid_lines`, `invalid_max_bytes`, `invalid_output_lines`, `invalid_output_chars` | 해당 출력 한도를 양의 정수로 고치세요. |
| `invalid_cursor` | cursor가 유효하지 않습니다. token을 임의로 고치지 말고 cursor 없이 새 화면을 읽으세요. |
| `invalid_label` | `spawn --label`을 비어 있지 않고 `/`가 없는 값으로 고치세요. |
| `invalid_batch_json`, `invalid_batch`, `empty_batch` | 올바른 비어 있지 않은 JSON 배열 또는 `requests` 배열을 제공하세요. |
| `invalid_request` | 배치 항목을 객체로 만들고 `address` 또는 `route` 중 정확히 하나를 지정하세요. |
| `duplicate_route` | 같은 실제 수신자를 여러 번 지정했습니다. 중복 지시를 정리한 뒤 거부된 항목만 다시 제출하세요. |
| `invalid_workers` | `--max-workers`를 `1`부터 `8`까지의 정수로 고치세요. |
| `invalid_command` | 지원되지 않는 명령입니다. 8개 하위 명령 중 하나를 사용하세요. 일반 CLI에서는 argparse가 먼저 거부합니다. |

### 호스트와 송신자: 접근 권한을 복구하되 제출 여부를 구분합니다

| 코드 | 의미와 조치 |
| --- | --- |
| `host_unavailable` | Herdr 탐색에 실패했습니다. 연결·인증·서버 상태를 확인하세요. 로컬 상세에 샌드박스나 소켓 권한 오류가 있으면 필요한 로컬 Herdr 소켓 접근 권한을 얻어 같은 탐색 명령을 다시 실행하세요. 탐색이 성공하기 전에는 에이전트가 없다고 보고하지 마세요. 이미 제출한 요청의 관찰에서 발생했다면 새 요청을 보내지 말고 `request-status`로 이어서 확인하세요. |
| `sender_probe_failed` | 제출 전에 현재 송신자 확인이 실패했으며 프롬프트는 제출되지 않았습니다. 로컬 소켓·샌드박스 권한 문제라면 필요한 접근 권한을 얻은 뒤 정확히 그 미전달 요청만 다시 실행하세요. 배치에서는 이 코드로 실패한 항목만 재시도하고 전달·제출·불명·시간 초과 항목은 다시 보내지 마세요. |
| `sender_unavailable` | `HERDR_PANE_ID`가 없거나 현재 pane에 에이전트가 없습니다. 활성 Herdr 에이전트 pane에서 실행하세요. 제출 전에 실패합니다. |
| `recipient_is_sender` | 송신자 자신을 수신자로 지정했습니다. 다른 수신자를 선택하세요. 제출되지 않았습니다. |
| `resolve_failed` | 구체적인 코드가 없는 수신자 확인 실패입니다. 초기 실패면 미제출이며, 제출 후 조회 실패면 기존 요청만 이어서 확인하세요. |

SSH 신뢰 설정을 바꾸거나 host-key 검증을 우회하지 마세요. 설정 파일에 없는
별칭으로 보내면 안 됩니다.

### 제출과 관찰: 불명 상태는 자동 재전송하지 않습니다

| 코드 | 의미와 조치 |
| --- | --- |
| `prompt_failed` | 제출이 거부되었거나 전송 명령이 실패했습니다. 설명과 `submitted`를 확인하고 미전달이 확인된 항목만 원인을 고쳐 재시도하세요. |
| `prompt_acceptance_unknown` | 전송이 중단되었지만 접수되었을 수 있습니다. 수명 주기에서는 `submitted: null`이고 배치에서는 `timeout`으로 보고될 수 있습니다. ID가 있으면 `request-status`로, 없으면 `status`와 `read`로 확인하고 다시 보내지 마세요. |
| `wait_timed_out` | 접수 후 관찰 제한 시간이 지났습니다. 미전달이 아니므로 `request-status`로 이어서 확인하세요. |
| `prompt_timeout`, `timeout` | 하위 전송 또는 배치 호출이 시간 초과되었습니다. 접수 여부를 확인하기 전에는 재전송하지 마세요. |
| `cancelled`, `prompt_cancelled` | 제출 전 취소인지 접수 후 대기 취소인지 `submitted`와 상태로 구분하세요. 접수 후라면 기존 요청을 조회하세요. |
| `recipient_changed` | 요청 도중 점유자가 바뀌어 수집을 중단했습니다. 원래 요청의 결과는 불명 상태로 보존하며 새 점유자의 출력으로 대체하지 마세요. |
| `read_failed` | 하위 `read`가 실패했습니다. 수신자와 접근 권한을 확인한 뒤 읽기만 다시 시도하세요. 프롬프트를 재전송하지 마세요. |

### 저장소·설치·내부 오류: 복구 전에 실제 상태를 확인합니다

| 코드 | 의미와 조치 |
| --- | --- |
| `invalid_request_id`, `request_not_found` | 받은 요청 ID와 같은 실행 환경의 저장소를 사용하는지 확인하세요. ID나 상태 파일이 없다는 사실은 미전달의 증거가 아닙니다. |
| `request_state_invalid`, `request_state_unavailable` | 저장된 상태가 잘못되었거나 읽기·쓰기에 실패했습니다. 저장소 경로와 권한을 복구하고 수신자 상태를 확인하세요. 제출 후 저장 실패일 수도 있으므로 자동 재전송하지 마세요. |
| `cwd_required`, `sender_pane_unavailable` | 원격 `--cwd` 또는 분할에 필요한 원본 pane이 없습니다. `--cwd`, `--from-pane`, 로컬 `HERDR_PANE_ID`를 확인하세요. 생성 전 검증에서 실패합니다. |
| `placement_failed`, `agent_start_failed`, `label_unavailable` | 배치 위치 생성, 대화형 시작 또는 빈 라벨 선택에 실패했습니다. 오류의 `cleanup` 결과와 남은 pane·tab·workspace·에이전트를 확인한 뒤 원인을 수정하세요. |
| `invalid_sender_result`, `dispatch_failed` | 배치 전송기가 잘못된 결과를 반환했거나 예기치 않게 실패했습니다. 항목의 상세와 수신자를 확인하고 일괄 재전송하지 마세요. |
| `internal_error` | CLI가 예기치 않은 예외를 JSON으로 반환했습니다. 설명과 실제 수신자·리소스 상태를 확인하세요. 명령의 어느 단계에서 실패했는지 모르면 자동 재시도하지 마세요. |
| `cli_not_found` | 스킬 래퍼가 저장소의 CLI 모듈을 찾지 못했습니다. 유지 중인 체크아웃과 스킬 설치 경로를 복구한 뒤 다시 실행하세요. |

## 여러 에이전트 조정

1. 요청받은 각 호스트를 `list`로 조회하고 모든 라벨을 확인하세요.
2. 전체 요청을 구체적이고 서로 겹치지 않는 작업으로 분해하세요.
3. 각 worker에게 필요한 문맥만 전달하세요. 사용자가 직접 방송을 요청한 경우가
   아니라면 원본 요청 전체를 모든 worker에게 복사하지 마세요.
4. 이미 맞춤 작성한 지시를 `address`/`message` 또는 `route`/`message` JSON으로
   만들어 `batch`로 전송하세요. GUI가 제공한 절대 CLI 경로와 token은 스킬이
   전역에 설치되지 않았더라도 그대로 사용할 수 있습니다.
5. 요청한 모든 worker가 응답하거나 명확한 종료 실패가 확인될 때까지 기다리세요.
   `submitted`는 재전송하지 말고 `request-status`로 이어서 관찰하세요.
6. 각 응답을 읽고 관련 workspace에서 내용을 확인한 뒤 누락되거나 서로 맞지 않는
   부분에 후속 요청을 보내세요.
7. 결과를 종합할 때 사용할 수 없는 호스트, 시간 초과 에이전트, 검증하지 못한 주장,
   남은 위험을 구분해서 보고하세요.

## 출력 수집의 한계

응답은 구조화된 에이전트 API가 아니라 TUI 화면에서 수집합니다. pane이 좁으면
에이전트가 줄을 좁은 폭으로 강제 개행하여 응답에도 그 개행이 남을 수 있습니다.
긴 응답을 받을 새 세션은 `spawn --placement tab` 또는
`spawn --placement workspace`로 넓게 배치하는 편이 좋습니다. 출력이 잘렸거나
`response.correlated`가 `false`이면 완전한 응답이라고 단정하지 마세요.

## 플러그인 없이 HAM 사용

HAM 플러그인을 설치하거나 활성화하지 않고 Herdr와 HAM 스킬만 사용할 수 있습니다.
현재 단독 설치는 소스 기반입니다. 스킬 래퍼가 저장소의 라우터 모듈을 불러오므로
지속적으로 유지할 체크아웃이 필요합니다. 스킬 디렉터리만 복사하는 방식은 독립
실행형 설치가 아닙니다. 플러그인 없이 사용할 때는 설치기의 복사 대신 체크아웃으로
연결되는 심볼릭 링크를 사용하세요. 래퍼는 실제 스크립트의 상위 디렉터리나 Herdr의
설치된 플러그인 등록 정보에서 CLI 모듈을 찾기 때문입니다. 아래 대상 경로에 기존
설치가 있다면 먼저 확인하고 관련 없는 파일을 덮어쓰지 마세요.

```bash
git clone https://github.com/zerodice0/herdr-agent-labels.git \
  "$HOME/.local/share/ham"
mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.omp/agent/skills"
ln -s "$HOME/.local/share/ham/.agents/skills/herdr-agent-messenger" \
  "$HOME/.agents/skills/herdr-agent-messenger"
ln -s "$HOME/.local/share/ham/.claude/skills/herdr-agent-messenger" \
  "$HOME/.claude/skills/herdr-agent-messenger"
ln -s "$HOME/.local/share/ham/.agents/skills/herdr-agent-messenger" \
  "$HOME/.omp/agent/skills/herdr-agent-messenger"
```

심볼릭 링크는 같은 체크아웃을 계속 가리키므로 다음 명령으로 갱신합니다.

```bash
git -C "$HOME/.local/share/ham" pull --ff-only
```

이 체크아웃을 사용할 때는 다음 절대 CLI 경로를 사용합니다.

```bash
HAM_CLI="$HOME/.local/share/ham/.agents/skills/herdr-agent-messenger/scripts/herdr_agent_messenger.py"
python3 "$HAM_CLI" list --host local
```

플러그인 없는 HAM에서도 기존 라벨을 이용한 요청·대기·읽기·배치 라우팅과
`spawn`을 사용할 수 있습니다. `spawn`은 직접 HAM 라벨과 메타데이터를 처리하지만,
플러그인의 팝업, 명령 팔레트 설치기, 기존 세션에 대한 자동 라벨링과
agent-detected hook은 제공하지 않습니다. 기존 수신자에게 이름이 없으면 현재
snapshot을 확인해 고유한 이름을 직접 지정할 수 있습니다.

```bash
herdr api snapshot
herdr agent rename <pane-id> yellow-falcon
```

로컬과 선택할 모든 SSH 호스트에 Herdr가 설치되어 실행 중이어야 합니다. 원격
호스트는 `~/.ssh/config`의 명시적인 별칭이어야 합니다.

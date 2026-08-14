<p align="center">
  <img src="assets/ham-logo.png" alt="HAM — Herdr Agent Messenger 마스코트 로고" width="360">
</p>

# HAM — Herdr Agent Messenger

한국어 · [English](README.md)

HAM은 Herdr용 에이전트 라벨링 및 다중 에이전트 메시징 플러그인입니다.
이름 없는 에이전트에 기억하기 쉬운 `color-animal` 이름을 붙이고, 키보드
중심 팝업이나 Codex, Claude Code에서 해당 에이전트로 프롬프트를 전달합니다.

## 주요 기능

- `blue-otter` 같은 자동 라벨과 색상 표시
- `~/.ssh/config`의 명시적 별칭을 이용한 로컬·SSH 에이전트 탐색
- 코디네이터 위임과 다중 수신자 직접 전송
- Codex와 Claude Code용 `herdr-agent-messenger` 스킬
- 안전한 요청·대기·읽기·배치·원격 배포 도구

사용자가 직접 붙인 이름은 변경하지 않습니다. 에이전트 주소는
`local/blue-otter`, `macbook-pro/purple-koala`처럼 항상 호스트를
포함합니다.

## 요구 사항

- Herdr 0.8.0 이상
- Python 3

## 설치

```bash
herdr plugin install zerodice0/herdr-agent-labels --yes
```

저장소 이름은 계속 `herdr-agent-labels`를 사용하지만 플러그인 ID는
`herdr.agent-messenger`, 표시 이름은 **HAM**입니다.

로컬 개발 환경에서는 현재 체크아웃을 연결할 수 있습니다.

```bash
herdr plugin link "$PWD" --enabled
```

0.7.x에서 업그레이드할 때는 기존 `herdr.agent-labels` ID를 마이그레이션해야
합니다. 구 플러그인을 제거하기 전에 [마이그레이션 가이드](docs/ko/migration.md)를
따르세요.

## 사용

Herdr 에이전트 pane에서 **Send Prompt to Agents**를 열어 수신자를 선택하고
코디네이터 위임 또는 직접 전송 방식을 고릅니다.

Codex에서는 `$ham`을 입력한 뒤 **HAM — Herdr Agent Messenger**를 선택합니다.
Claude Code에서는 `/herdr-agent-messenger`를 명시적으로 호출하거나 자연어로
HAM 작업을 요청할 수 있습니다.

```text
$ham local/yellow-falcon에게 dxp-ui에서 사용하는 언어 라벨을 물어봐.
응답을 기다린 다음 현재 작업과 기본값을 그 답변에 맞춰줘.
```

Herdr에 표시된 정확한 `host/label`을 사용하세요. 라벨만 쓰면 다른 호스트의
에이전트와 충돌하거나 AI 클라이언트 자체 서브에이전트로 오인될 수 있습니다.

Herdr 명령 팔레트의 **HAM Skill**에서 번들 스킬을 설치·갱신하거나 다음 명령을
실행합니다.

```bash
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

HAM 플러그인을 활성화하지 않고 Herdr와 스킬만 사용할 수도 있습니다. 소스 기반
단독 설치 방법과 제약은 [스킬 가이드](docs/ko/skill-guide.md#플러그인-없이-ham-사용)를
참고하세요.

## 문서

| 주제 | 한국어 | English |
| --- | --- | --- |
| 스킬 설치와 프롬프트 작성 | [스킬 가이드](docs/ko/skill-guide.md) | [Skill guide](docs/skill-guide.md) |
| 설치 및 0.7.x 마이그레이션 | [마이그레이션](docs/ko/migration.md) | [Migration](docs/migration.md) |
| SSH 탐색과 라우팅 계약 | [SSH 및 라우팅](docs/ko/ssh-and-routing.md) | [SSH and routing](docs/ssh-and-routing.md) |
| 팝업 동작과 키보드 조작 | [UI 참고서](docs/ko/ui-reference.md) | [UI reference](docs/ui-reference.md) |
| 안전한 원격 배포 | [원격 배포](docs/ko/rollout.md) | [Rollout](docs/rollout.md) |

## 테스트

```bash
python3 -m unittest -v
```

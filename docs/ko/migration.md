# 설치 및 마이그레이션

한국어 · [English](../migration.md) · [README](../../README.ko.md)

## 새로 설치

공개 GitHub 저장소에서 HAM을 설치하고 활성화합니다.

```bash
herdr plugin install zerodice0/herdr-agent-labels --yes
```

로컬 개발 환경에서는 체크아웃을 직접 연결할 수 있습니다.

```bash
herdr plugin link "$PWD" --enabled
```

기존 이름 없는 에이전트는 **Assign Agent Label** 액션으로 라벨을 지정할 수
있습니다. 설치 후 감지되는 에이전트에는 자동으로 라벨이 붙습니다.

## 0.7.x에서 마이그레이션

HAM 0.8.0에서는 플러그인 ID가 `herdr.agent-labels`에서
`herdr.agent-messenger`로 변경됐습니다. 저장소와 설치 소스는 계속
`zerodice0/herdr-agent-labels`를 사용합니다.

기존 GitHub 설치는 구 ID를 비활성화하고 새 버전을 설치·검증한 다음에만 구
등록을 제거합니다.

```bash
herdr plugin disable herdr.agent-labels
herdr plugin install zerodice0/herdr-agent-labels --yes
herdr plugin list --plugin herdr.agent-messenger --json
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
herdr plugin uninstall herdr.agent-labels
```

로컬 개발 링크는 체크아웃을 갱신하고 Herdr 설정을 다시 불러옵니다. 로컬 링크는
경로 기반이므로 unlink/relink 없이 0.8.0 manifest의 새 ID를 인식합니다.

```bash
git pull --ff-only
herdr config check
herdr server reload-config
herdr plugin list --plugin herdr.agent-messenger --json
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

## 호환 동작

마이그레이션 중에는 다음 fallback을 유지합니다.

- 새 설정 경로에 파일이 없으면 기존 `ssh-hosts` 허용 목록을 읽습니다.
- 새 상태가 없으면 기존 탐색 캐시와 요청 상태 디렉터리를 사용합니다.
- 구 `HERDR_AGENT_LABELS_*` 환경 변수도 동작하지만 새 설정에는
  `HERDR_AGENT_MESSENGER_*`를 사용해야 합니다.
- 0.8.0 스킬 래퍼는 `herdr.agent-messenger`를 먼저 찾고 구 플러그인 ID로
  fallback합니다.

구 플러그인을 제거하기 전에 **HAM Skill**을 열어 복사된 프로젝트·시스템 스킬을
갱신하세요. 갱신하지 않은 0.7.x 스킬은 구 ID만 인식합니다.

## 최종 상태 검증

```bash
herdr config check
herdr server reload-config
herdr plugin list --plugin herdr.agent-messenger --json
herdr plugin action list --plugin herdr.agent-messenger
```

최종 액션 목록에는 `agent-skill-guide`, `label-current`, `message-agents`가
있어야 하며 `herdr.agent-messenger`만 활성화돼야 합니다.

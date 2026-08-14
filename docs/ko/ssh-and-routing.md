# SSH 탐색 및 라우팅

한국어 · [English](../ssh-and-routing.md) · [README](../../README.ko.md)

## 에이전트 탐색

HAM은 로컬 에이전트를 즉시 표시합니다. `~/.ssh/config`에 명시적인 `Host`
별칭이 있으면 원격 호스트를 비동기로 조회합니다. 5초 안에 유효한 Herdr snapshot을
반환한 호스트만 포함하며, 팝업을 다시 열 때마다 모든 호스트에 접속하지 않도록
결과를 잠시 캐시합니다.

재귀적인 SSH `Include` 파일도 지원합니다. probe는 비대화형 인증을 사용하고 SSH
forwarding, agent forwarding, X11 forwarding, local command를 비활성화합니다.
필요한 host key 신뢰, 인증, 연결 또는 실행 중인 Herdr 서버가 없는 호스트는
건너뜁니다.

## 허용 호스트 제한

이전 버전과의 호환을 위해 기본값은 모든 명시적 별칭을 조회합니다. 대상을
제한하려면 플러그인 설정 디렉터리에 `ssh-hosts` 파일을 만들고 한 줄에 하나씩
별칭을 적습니다.

```text
macbook-pro
winmini
```

SSH 설정에도 존재하는 별칭만 사용합니다. 빈 파일은 로컬 전용이며 파일이 없으면
모든 별칭을 조회합니다. 기본 경로는 다음과 같습니다.

```text
~/.config/herdr/plugins/config/herdr.agent-messenger/ssh-hosts
```

다른 경로는 `HERDR_AGENT_MESSENGER_SSH_HOSTS_FILE`로 지정합니다. 구
`HERDR_AGENT_LABELS_SSH_HOSTS_FILE`과 이전 플러그인 설정 디렉터리는
마이그레이션 fallback으로 유지됩니다. 다른 SSH 설정 파일은
`HERDR_AGENT_MESSENGER_SSH_CONFIG`로 지정하며
`HERDR_AGENT_LABELS_SSH_CONFIG`도 구 fallback으로 지원됩니다.

## Tailscale 별칭

Tailscale에 HAM 전용 형식은 필요하지 않습니다. 안정적인 별칭이 MagicDNS 이름
또는 Tailscale IP를 가리키게 설정하세요.

```sshconfig
Host winmini
  HostName winmini.example-tailnet.ts.net
  User your-remote-user
```

HAM은 명시한 별칭만 표시하고 허용합니다. tailnet의 모든 기기를 자동으로 허용하지
않습니다.

## 전송 방식

에이전트 탐색 후 두 방식 중 하나를 선택합니다.

- **코디네이터를 통한 위임**이 기본값입니다. 현재 에이전트가 전체 요청과 검증된
  worker route를 받고, 작업을 분해해 각 worker에게 맞춤 요청을 전송한 뒤 응답을
  기다리고 종합합니다. worker는 코디네이터가 전달한 문맥만 봅니다.
- **직접 전송**은 원본 요청 전체를 선택한 모든 수신자에게 즉시 복사합니다.

플러그인 자체는 작업을 의미적으로 분해하지 않습니다. 코디네이터는 HAM 스킬이
전역에 설치되지 않았더라도 요청에 포함된 라우터 경로와 route token을 사용할 수
있습니다.

두 방식은 정보 노출 범위가 다릅니다. 위임 방식에서는 전체 요청을 코디네이터만
보지만 직접 전송에서는 SSH로 연결한 에이전트를 포함한 모든 수신자가 전체 요청을
봅니다.

## Route 안전성

모든 작업은 현재 호스트와 Agent Labels 점유자를 다시 확인합니다. HAM은 pane의
이전 점유자를 조용히 재사용하지 않습니다.

V2 route token은 원본 session ID나 작업 디렉터리 대신 호스트, 점유자 fingerprint,
해시된 연속성 필드를 담습니다. 오래된 등록 라벨은 pane, workspace, agent kind가
유일하게 일치할 때만 갱신됩니다. 이름이 없거나 표시 전용인 route에는 더 엄격한
연속성 조건이 적용됩니다. 모호하거나 점유자가 바뀌면 `route_expired` 상태를
유지합니다. V1 token은 정확히 일치할 때 계속 읽을 수 있습니다.

`status`, `send`, `read`, `request`는 `route_refreshed`와 현재 `route`를
반환합니다. 이후 작업에는 반환된 token을 사용하세요.

## 저장되는 메타데이터

원격 프롬프트에는 발신자의 로컬 호스트 이름과 에이전트 라벨이 포함됩니다.
`HERDR_PLUGIN_STATE_DIR` 아래의 비공개 `0600` 탐색 캐시에는 원격 라벨,
pane/session 메타데이터, 상태, workspace 경로, 호스트 별칭이 저장됩니다.

# agent-fleet

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-v0.8.2--alpha-blue.svg)](https://github.com/metahub-tech/agent-fleet/releases/tag/v0.8.2-alpha)

[English](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · **한국어** · [Español](README.es.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português (BR)](README.pt-BR.md) · [Русский](README.ru.md)

<p align="center">
  <img src="docs/assets/agent-fleet-demo.gif" alt="agent-fleet demo — an LLM agent driving a real iPad over MCP" width="320">
  <br><sub><em>LLM 에이전트가 MCP로 실제 iPad를 조작 — 사람 손 없이.</em></sub>
</p>

> **LLM 에이전트에게 자기만의 실제 기기 함대를.**
> 실제 Windows / macOS / Android / iOS 하드웨어를 MCP로 LLM 에이전트에 연결해 사람처럼 조작하게 합니다. 설치는 명령어 한 줄:
>
> ```bash
> uvx --from "git+https://github.com/metahub-tech/agent-fleet@v0.8.2-alpha#subdirectory=cli" agent-fleet setup
> ```

## 무엇인가요

개발 머신 외부의 **실제 기기**(Windows PC, Mac, Android 폰, iPhone)를 LLM 에이전트의 도구 체인에 편입시켜, 로컬 명령처럼 구동하게 합니다: 스크린샷, 버튼 탭, 테스트 실행, 로그 읽기, GUI 디버깅.

이는 **에이전트 주도 소프트웨어 테스트와 크로스플랫폼 검증**을 위한 인프라이며, 더 넓게는 에이전트에게 물리 세계에 대한 실제 인식과 영향력을 부여하기 위한 토대입니다.

```
┌─────────────────┐                              ┌──────────────┐
│  Agent (any OS) │ ──── Tailscale Mesh ─────>  │ Windows PC   │ win-device     :8766 ✅
│  Claude Code /  │                              ├──────────────┤
│  Cursor / Cline │                              │ macOS box    │ mac-device     :8767 ✅
│  / OpenClaw /   │                              ├──────────────┤
│  Antigravity /  │                              │ Android phone│ android-device :8768 ✅
│  Hermes / ...   │                              ├──────────────┤
└─────────────────┘                              │ iPhone/iPad  │ ios-device     :8769 ✅
                                                 └──────────────┘
            ↑                                                ↑
   uvx agent-fleet setup           generates configs for 6 agent frameworks
   one command: install client + server / configure Tailscale / guide permissions / self-check / emit snippets
```

## 상태

| 구성요소 | 버전 | 상태 |
|---|---|---|
| Windows 10/11 브리지 | `0.2.0` | ✅ 릴리스됨 (win-device, 33개 도구, streamable-http) |
| macOS 12+ 브리지 | `0.3.0` | ✅ 릴리스됨 (mac-device, launchd, 31개 도구, GUI 권한 플로우) |
| Android 브리지 | `0.7.0-alpha` | ✅ 릴리스됨 (android-device, **25개 도구**, 멀티 디바이스 + USB + 무선 + 하이브리드 ADB) |
| agent-fleet CLI 마법사 | `0.5.0-alpha` | ✅ 릴리스됨 (`uvx agent-fleet setup` 원샷 설치; 6개 프레임워크 설정 생성) |
| 역할 이름 변경 → `<os>-device` + macOS 권한 안내 | `0.6.0-alpha` | ✅ 릴리스됨 |
| v0.6.x 패치 (UI 인트로스펙션, smoke 테스트, 버그픽스, 인스톨러 강화…) | `0.6.1–0.6.15` | ✅ 릴리스됨 — [CHANGELOG.md](CHANGELOG.md) 참조 |
| iOS / iPadOS 브리지 | `0.8.0-alpha` | ✅ 릴리스됨 (ios-device, 26개 도구, WebDriverAgent + pymobiledevice3, iPad 검증됨) |
| iOS WDA 데몬 (부팅 자동 시작 + 킵얼라이브) | `0.8.2-alpha` | ✅ 릴리스됨 (go-ios runwda + tunneld launchd; 무료/유료 서명 모드) |
| 디바이스 간 협업 | `0.9.0` | 🔭 향후 |
| 공개 안정 릴리스 | `1.0.0` | 🔭 향후 (alpha 커뮤니티 피드백 이후) |

자세한 내용은 [`docs/roadmap.md`](docs/roadmap.md).

## 빠른 시작

**입문자 / 원샷 플로우** — 제어할 기기(PC, 또는 폰이 연결된 PC)에서:

```bash
# macOS / Linux  —  NOT `curl ... | bash`!  The wizard is interactive and bash
# piped from curl uses stdin for the script itself, so questionary's prompts
# die with EOFError.  The `bash -c "$(...)"` form puts the script in argv and
# leaves stdin = terminal.
bash -c "$(curl -fsSL https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.sh)"

# Windows  —  `irm | iex` is fine on PowerShell because iex runs the script in
# the current session and Read-Host reads from the console host, not stdin.
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/metahub-tech/agent-fleet/main/install.ps1 | iex"
```

또는 이미 uv가 있다면 (v0.8.2-alpha 단계에서는 PyPI가 아니라 git에서 가져옵니다):

```bash
uvx --from "git+https://github.com/metahub-tech/agent-fleet@v0.8.2-alpha#subdirectory=cli" agent-fleet setup
```

> macOS 12 사용자는 먼저 `brew install coreutils`가 필요합니다 (uv 래퍼가 `realpath`를 쓰는데 macOS 12에는 기본 포함되지 않음; [#2](https://github.com/metahub-tech/agent-fleet/issues/2) 참조).

마법사가 안내합니다: 역할 선택 → MCP 서버 설치 → Tailscale 구성 → GUI 권한 / ADB 인가 대화식 안내 → 헬스 체크 → 6개 에이전트 프레임워크용 설정 스니펫 출력.

**숙련자**는 여전히 하위 스크립트를 직접 호출할 수 있습니다 — `docs/install-pattern.md`는 유효합니다("고급 매뉴얼").

| 당신은 | 읽을 문서 |
|---|---|
| **입문자** (마법사에 맡기기) | 위 명령을 실행하고 프롬프트를 따르기 |
| **기기 관리자** (직접 배포를 스크립트화) | [`docs/install-pattern.md`](docs/install-pattern.md) (하위 스크립트 계약) |
| **에이전트 운영자** | 마법사가 출력한 스니펫을 에이전트 설정에 붙여넣기; [`docs/agent-host-setup.md`](docs/agent-host-setup.md) 도 참조 |
| **기여자** (설계 문서) | [`docs/internal/design/2026-05-11-agent-fleet-cli.md`](docs/internal/design/2026-05-11-agent-fleet-cli.md) |

## 아키텍처

모든 플랫폼 브리지는 동일한 3단계 파이프라인입니다:

```
[Agent Host] ── Tailscale ──> [Device Host] ── Native Drivers ──> [Device / App]
                  cross-LAN     MCP server         pywinauto / AppleScript / adb / xcrun
```

도구 인터페이스는 모든 플랫폼에서 의미적으로 일관됩니다 (`take_screenshot` / `click` / `launch_app` / …). 기기 전환은 `~/.claude.json`의 URL만 바꾸면 됩니다.

자세한 내용은 [`docs/architecture.md`](docs/architecture.md).

## 저장소 구조

```
agent-fleet/
├── docs/                          # shared docs
│   ├── install-pattern.md         # developer baseline: two roles / two install paths / directory contract
│   ├── architecture.md            # common bridge architecture
│   ├── agent-host-setup.md        # agent-side config (~/.claude.json + skill symlinks)
│   ├── roadmap.md                 # platform roadmap
│   └── platforms/<name>.md        # per-platform manual (device side)
├── platforms/                     # one self-contained bay per platform
│   ├── windows/
│   │   ├── README.md              # at-a-glance
│   │   ├── server/                # MCP server source + deps
│   │   ├── scripts/               # install / launch / troubleshoot scripts
│   │   ├── skills/using-win/      # skill docs for the agent to use
│   │   └── examples/              # claude-settings.json snippets
│   └── macos/                     # same sub-structure
├── scripts/                       # repo-level scripts
│   └── install-agent-side.py      # one command to install MCP + skill into ~/.claude.json
├── examples/                      # cross-platform examples
│   └── multi-platform-claude-settings.json
└── CHANGELOG.md
```

플랫폼을 추가하려면 → `platforms/<name>/` 아래에 동일한 하위 구조를 두세요. [`docs/install-pattern.md` § Adding a new platform](docs/install-pattern.md) 참조.

## 라이선스

[Apache 2.0](LICENSE)

## 기여

기여를 환영합니다! **agent-fleet는 Apache 2.0 라이선스로 공개되었으며 커뮤니티 기여를 받습니다.**

기여 절차와 코딩 규약은 [`CONTRIBUTING.md`](CONTRIBUTING.md), 행동 강령은 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)를 참조하세요. 보안 취약점은 GitHub Security 탭 → "Report a vulnerability"로 비공개 제보해 주세요.

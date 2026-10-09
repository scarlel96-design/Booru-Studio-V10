# Booru Studio V10 전체 점검 및 보완 보고서 — 2026-10-09

## 이번 변경

- `redact_input_for_storage()`가 HTTP(S) URL의 모든 쿼리와 fragment를 저장 전에 제거한다. 알 수 없는 서명 키도 SQLite/로그/스냅샷에 남기지 않으며, 혼합 대소문자 scheme과 IPv6 호스트를 처리한다.
- `SourceGrantStore`가 잘못된 payload, 경로의 링크·reparse 구성 요소, 기존 grant 파일 덮어쓰기를 거부한다. 임시 파일은 배타적으로 생성하고 파일 동기화 후 원자적으로 연결한다. DPAPI 암호화에는 UI 금지 플래그를 사용한다.
- Windows의 파일 동기화 경로를 쓰기 가능한 핸들로 열어 `os.fsync()` 실패를 바로잡았다. 대상은 해시 유틸리티와 Direct HTTP 체크포인트이다.
- POSIX `StreamConnection`의 fd 수신을 프레임 디코더와 단조 시계 기반 타임아웃으로 정리했다. Windows 수신 경로는 기존 구현을 유지한다.
- Static Web HTML 요청·스트림 읽기의 일시적 연결 실패를 최대 3회 시도하고, 마지막 실패를 `NETWORK_TIMEOUT` 또는 `NETWORK_RESET`으로 분류한다. 중간 실패에서 받은 부분 HTML은 버리고 전체 요청을 다시 읽는다.
- 테스트의 경로 구분자와 파일 인코딩 기대값을 플랫폼 독립적으로 명시했다.

## 검증 결과

- 원본 Sprint 11 소스 기준 전체 테스트 재검증: **15 failed, 220 passed, 13 skipped** (Python 3.12, Windows, 외부 pytest harness). 실패는 Windows 읽기 전용 핸들 동기화, 경로·인코딩 기대값, 로컬 HTTP 연결 문제를 포함한다. 앞선 실행은 **16 failed, 219 passed, 13 skipped**로 로컬 HTTP 결과가 변동했다.
- 수정본 최종 전체 테스트: **1 failed, 239 passed, 13 skipped**. 남은 실패는 gallery direct handoff의 로컬 HTTP 읽기 타임아웃이다. Direct HTTP는 재시도를 수행하지만 이 실행에서는 최종 시도까지 응답을 완료하지 못했다. 전체 테스트는 **NOT PASS**이다.
- 집중 검사: redaction, source grant, 제품 제어, QML 계약 **18 passed**; Static Web 관련 검사 **6 passed**; `compileall` **PASS**.
- 이번 검사는 Python 3.12 소스 테스트다. 프로젝트가 요구하는 Python 3.13 봉인 도구체인, frozen 제품 실행, 설치 프로그램, 실제 사이트·대량 전송은 이번 결과로 통과했다고 보지 않는다.

## 다음 작업 우선순위

1. **P0 — 제품 실행 루프 연결:** `SourceGrantStore`는 현재 제품 코드에서 호출되지 않는다. Core의 입력 수락 → protected source → resolver/classifier → queue → Worker → FileCommit → UI 갱신 → 다음 큐 실행을 한 경로로 연결하고 실제 프로세스 통합 테스트를 추가한다.
2. **P0 — gallery HTTP 실패 재현:** 테스트 서버의 송신 완료·연결 종료와 Direct HTTP의 재시도 횟수·체크포인트를 분리 계측한다. 재현 조건이 확인되면 해당 계층을 수정하고 전체 테스트를 재실행한다.
3. **P1 — Worker 프로세스 관측성:** `core/worker_launcher.py`의 `stderr=subprocess.PIPE`는 수거 루프가 없다. 제한된 버퍼·redaction·종료 회수를 갖춘 로그 처리로 프로세스 정체와 비밀 노출 가능성을 제거한다.
4. **P1 — 릴리스 재현성:** `pyproject.toml`은 Python 3.13을 요구하지만 현재 로컬 검증은 3.12이다. 고정 Python/uv/Rust/PySide6/PyInstaller/Inno 도구체인, lock 검사, frozen QML 및 설치·롤백 검증을 한 빌드에서 묶는다.

이 보고서는 첨부 문서의 작업 목표를 현재 소스와 비교해 작성했다. 문서의 과거 PASS 기록은 현재 수정본의 검증 결과로 승격하지 않았다.

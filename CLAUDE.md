# CLAUDE.md — Claude Code 진입점

> **이 저장소의 공통 규칙은 [`HARNESS.md`](HARNESS.md)에 있다. 먼저 그 파일을 읽고, 그 안의
> `## 0. Required Reading` 순서를 따른다.** 이 파일은 규칙을 복제하지 않는다.

구조·경계·"무엇을 고치려면 어디를 보나"는 [`ARCHITECTURE.md`](ARCHITECTURE.md)를 본다.

## Claude Code 고유 사항

- 이 저장소에는 Skill · hook · MCP 설정이 없다. 필요한 문서는 **직접 열어서 읽는다** (자동으로
  로드되지 않는다).
- 코드를 수정하기 전에 `pytest`를 실행한다. `tests/test_core_purity.py`와
  `tests/test_core_standalone.py`는 아키텍처 경계를 강제하는 테스트이므로, 실패하면 테스트를
  고치는 대신 **코드를 고친다**.
- 새 기능을 추가하기 전에 `HARNESS.md` 10절(MVP 범위 밖)을 확인한다.
- 이 저장소는 Public으로 공개된다. `HARNESS.md` 9절의 금지사항을 커밋 전에 확인한다.

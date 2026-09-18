# GEMINI.md — Gemini CLI / Antigravity 진입점

> **이 저장소의 공통 규칙은 [`HARNESS.md`](HARNESS.md)에 있다. 먼저 그 파일을 읽고, 그 안의
> `## 0. Required Reading` 순서를 따른다.** 이 파일은 규칙을 복제하지 않는다.

구조·경계·"무엇을 고치려면 어디를 보나"는 [`ARCHITECTURE.md`](ARCHITECTURE.md)를 본다.

## Gemini 고유 사항

- 이 저장소에는 Gemini 전용 설정이나 확장이 없다. 공통 문서를 **직접 열어서 읽는다.**
- 이 저장소의 LLM 호출은 전부 `core/interfaces/llm.py`의 `LLMProvider`를 경유한다. Gemini를
  붙이려면 `adapters/llm/google.py`를 추가하고 그 Protocol만 만족시킨다 — `core/`는 수정하지
  않는다.
- 코드를 수정하기 전에 `pytest`를 실행한다. 경계 테스트(`test_core_purity`,
  `test_core_standalone`)가 실패하면 테스트가 아니라 코드를 고친다.
- 이 저장소는 Public으로 공개된다. `HARNESS.md` 9절의 금지사항을 커밋 전에 확인한다.

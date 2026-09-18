# AGENTS.md — GPT / Codex 진입점

> **이 저장소의 공통 규칙은 [`HARNESS.md`](HARNESS.md)에 있다. 먼저 그 파일을 읽고, 그 안의
> `## 0. Required Reading` 순서를 따른다.** 이 파일은 규칙을 복제하지 않는다.

구조·경계·"무엇을 고치려면 어디를 보나"는 [`ARCHITECTURE.md`](ARCHITECTURE.md)를 본다.

## GPT / Codex 고유 사항

- 이 저장소는 특정 AI 플랫폼 전용이 아니다. `HARNESS.md`·`ARCHITECTURE.md`·`docs/`·`prompts/`는
  모든 플랫폼이 공유하는 공통 문서이며, 어느 플랫폼도 이 파일들을 자동 탐색하지 않는다.
  **필요한 파일을 직접 열어서 읽은 뒤** 작업한다.
- `prompts/**/*.md`는 provider 중립으로 작성되어 있다. 특정 모델 이름이나 provider 고유 문법을
  프롬프트 파일에 넣지 않는다 — provider 차이는 `adapters/llm/`이 흡수한다.
- 코드를 수정하기 전에 `pytest`를 실행한다. 경계 테스트(`test_core_purity`,
  `test_core_standalone`)가 실패하면 테스트가 아니라 코드를 고친다.
- 이 저장소는 Public으로 공개된다. `HARNESS.md` 9절의 금지사항을 커밋 전에 확인한다.

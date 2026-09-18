# prompts — 코드와 분리된 Prompt

Prompt를 코드 안에 문자열로 쓰지 않는다. 이 디렉토리의 `.md` 파일이 원본이다.

Phase 1에는 Engine이 없으므로 Prompt도 없다. Stage별 디렉토리는 **해당 Phase에서 처음 파일이
생길 때 만든다** — 빈 디렉토리를 미리 만들어 두지 않는다.

## 레이아웃

```
prompts/
  research/           Phase 3 — Market Research
  diagnosis/          Phase 3 — Master Note Diagnosis, SWOT / Key Issues
  client-discovery/   Phase 4 — Candidate Discovery, Fit Screening, Priority
  client-analysis/    Phase 5 — Top 3 Client Analysis
  proposal/           Phase 6 — Proposal Strategy
```

## 파일 형식

```markdown
---
id: diagnosis/mn03-findings
stage: diagnosis
output_schema: schemas/research_finding.schema.json
requires: [framework, evidence, output_lang]
---

# 목적
...

# 지시
...
```

- `output_schema` — 이 Prompt의 결과를 검증할 스키마. `LLMProvider.generate_structured`에
  그대로 넘긴다.
- `requires` — 렌더링에 필요한 변수. 빠지면 호출 시점에 실패해야 한다.

## 규칙

1. **Provider 중립으로 쓴다.** 파일에 `Claude` · `GPT` · `Gemini` 같은 모델 이름이나
   provider 고유 문법을 넣지 않는다. 차이는 `adapters/llm/`이 흡수한다.
2. **언어별 사본을 만들지 않는다.** `output_lang`을 변수로 받는다. ko/en 프롬프트를 두 벌
   유지하면 한쪽만 고쳐지는 일이 반드시 생긴다.
3. **Evidence를 벗어나지 말라고 명시한다.** 모든 분석 Prompt는 "주어진 Evidence에서만
   답하고, 근거가 없으면 `MISSING_EVIDENCE`로 표시하라"는 지시를 포함한다
   (`HARNESS.md` 6절).
4. **SWOT을 바로 요청하는 Prompt를 만들지 않는다.** Finding을 먼저 만들고, 그 Finding을
   분류하는 Prompt를 따로 둔다.
5. **Master Note 내용을 Prompt에 복사하지 않는다.** `KnowledgeProvider.get_framework()`가
   돌려준 `Framework`를 변수로 주입한다. 복사하면 방법론을 고칠 때 Prompt가 뒤처진다.

# examples — 가상 Sample Project

```bash
python examples/run_example.py
```

API 키도, 네트워크도, 데이터베이스도 필요하지 않다. Memory Storage · Static Knowledge ·
결정적(deterministic) `echo` LLM · Manual Search만 사용한다.

## 여기 있는 데이터는 전부 가상이다

`sample_project/`의 회사 · Client · 시장 정보는 **완전히 만들어낸 것**이다. 실제 기업이나
실제 컨설팅 데이터가 아니다 (`HARNESS.md` 9절). 가상임이 드러나도록 이름에 `(가상)` 또는
`Fictional`을 붙인다.

시나리오: **리버스톤센싱(Riverstone Sensing)** — 다항목 수질센서를 만드는 가상의 국내 중소
기업이 베트남 상수도 사업자를 잠재 Client로 검토한다.

## 파일

| 파일 | 검증 스키마 |
|---|---|
| `project.json` | `schemas/project.schema.json` |
| `source_metadata.json` | `schemas/source_metadata.schema.json` |
| `research_finding.json` | `schemas/research_finding.schema.json` |
| `swot_issue.json` | `schemas/swot_issue.schema.json` |
| `client_candidate.json` | `schemas/client_candidate.schema.json` |
| `client_analysis.json` | `schemas/client_analysis.schema.json` |
| `proposal_strategy.json` | `schemas/proposal_strategy.schema.json` |

**파일명은 검증할 스키마 이름과 같게 둔다.** `tests/test_schemas.py`가 그 규칙으로 파일을
찾아 검증하므로, 이름이 다르면 테스트가 실패한다. 한 파일에 레코드 1개 또는 배열 모두 가능하다.

## 이 예제가 일부러 보여주는 것

- **`evidence_type` 4종이 모두 등장한다** — `FACT` 3 · `INFERENCE` 1 · `ASSUMPTION` 1 ·
  `MISSING_EVIDENCE` 1. 근거 없는 항목을 `FACT`로 올리지 않는 모습이 핵심이다.
- **처리 실패한 source가 하나 있다** (`src_s04`, `EXTRACT_NO_TEXT_LAYER`). 텍스트 레이어가
  없는 스캔 PDF는 실패로 기록하고 넘어간다. OCR은 MVP 범위 밖이다.
- **두 번째 Client 후보가 `DEFERRED`다.** 규제 요건이 확인되지 않아 문제 자체가 성립하는지
  알 수 없다. 이런 경우 점수를 만들어 채우지 않고 `UNKNOWN`으로 남긴다.
- **`missing_evidence`가 5개 항목으로 채워져 있다.** 분석이 비어 있는 것과, 무엇이 비어
  있는지 아는 것은 다르다.
- **제안 대응 논리가 미확인 사항을 숨기지 않는다.** 인증 미보유를 밝히고 확인 일정을 제안에
  포함한다.

## 새 예제를 추가할 때

1. 스키마 이름과 같은 파일명을 쓴다
2. 완전히 가상의 데이터만 쓴다
3. `pytest tests/test_schemas.py`로 검증한다

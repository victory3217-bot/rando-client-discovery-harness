# Product Spec — 단계별 입력과 출력

> 각 단계가 무엇을 받아 무엇을 내놓는지 정의한다. 원칙은 `HARNESS.md`, 구조는
> `ARCHITECTURE.md`, 필드 정의는 `docs/data-model.md`에 있다. 이 문서는 그 사이의 **흐름**을
> 다룬다.
>
> Phase 1 시점에서 구현된 것은 Entity · Interface · 불변식이며, 아래 단계들은 Phase 2–7에
> 걸쳐 구현된다. 각 단계의 Phase를 표시했다.

---

## 입력

### A. Consulting Output
BM As-Is · BM To-Be · 가격전략 · 가격정책 · 기타 컨설팅 결과
→ `source_category = CONSULTING_OUTPUT`

### B. Company Data
회사소개서 · 사업계획서 · 제품·서비스 자료 · 기술자료 · 프로젝트 실적 · 기존 고객자료 ·
기존 제안서 · 가격·원가자료
→ `source_category = COMPANY_DATA`

### C. External Business Data
시장보고서 · 산업자료 · 경쟁사자료 · 고객자료 · 정책자료 · 규제·인증자료
→ `source_category = EXTERNAL_BUSINESS_DATA`

지원 파일 형식: PDF · DOCX · HTML · PPTX · XLSX · CSV · TXT · MD

---

## Stage 1 — File Intake *(Phase 2)*

| | |
|---|---|
| 입력 | 업로드된 파일 + `source_category` |
| 출력 | `SourceMetadata` + 메모리상의 추출 텍스트·표 |
| 규칙 | `docs/privacy.md`의 Upload Flow를 그대로 따른다 |

- `source_id`는 랜덤. 파일명은 즉시 폐기한다.
- 텍스트 레이어가 없는 스캔 PDF는 `processing_status = FAILED` + `error_code`. **OCR은 MVP
  범위 밖이다.**
- 처리 종료 후 `PURGED`.

## Stage 2 — Market Research *(Phase 3)*

| | |
|---|---|
| 입력 | 추출 텍스트 + `SearchProvider` 결과 + `market_scope` / `target_countries` |
| 출력 | Evidence 후보 (아직 Finding이 아니다) |

- MVP 기본 Adapter는 `manual` — 사용자가 제공한 자료만 사용한다. 웹 검색은 선택이다.
- 국내·해외를 같은 Engine으로 처리한다. `market_scope`와 국가 필드로만 구분한다.

## Stage 3 — Master Note Diagnosis *(Phase 3)*

| | |
|---|---|
| 입력 | Evidence + `KnowledgeProvider.get_framework("MN02".."MN07")` |
| 출력 | `ResearchFinding[]` |

각 MN의 dimension이 곧 질문이다. 질문에 답할 Evidence가 없으면 답을 만들지 않고
`evidence_type = MISSING_EVIDENCE`로 남긴다.

`FACT` · `INFERENCE`는 `source_id`가 필수다. 이 규칙은 `core/evidence.check_finding`이
강제한다.

## Stage 4 — SWOT / Key Issues *(Phase 3)*

| | |
|---|---|
| 입력 | `ResearchFinding[]` |
| 출력 | `SWOTIssue[]` (+ `key_issue`, `strategic_implication`) |

**SWOT을 작성하라고 LLM에 바로 요청하지 않는다.** Finding을 분류·압축하는 단계다.
`finding_ids`가 비어 있으면 거부된다.

추가 출력: Missing Evidence 목록 · Additional Research Required 목록.

## Stage 5 — Client Candidate Discovery *(Phase 4)*

| | |
|---|---|
| 입력 | SWOT/Issues + Capability + Product/Solution + Market Opportunity |
| 출력 | `ClientCandidate[]` (`status = CANDIDATE`) |

정합성 기준:

```
Company Capability x Product/Solution x Market Opportunity
                   x Customer Problem x Purchasing Possibility
```

`discovery_rationale`은 "우리 무엇을 그들 어떤 문제에"를 명시한다. 이것이 없으면 산업 내 기업
목록이지 후보가 아니다.

## Stage 6 — Fit Screening & Priority *(Phase 4)*

| | |
|---|---|
| 입력 | `ClientCandidate[]` |
| 출력 | `fit_screening` · `priority` 채워진 `ClientCandidate[]` |

8개 기준 (전부 `FitLevel` 순서형 enum):

| Screening | Priority |
|---|---|
| Problem Fit | Market Attractiveness |
| Solution Fit | Purchasing Potential |
| Capability Fit | Accessibility |
| | Competitive Situation |
| | Evidence Quality |

`sales_priority`(`P1`/`P2`/`P3`/`DEFERRED`)는 **사람이 정한다.** 8개 평가에서 계산하지 않는다.
근거가 없는 항목은 `UNKNOWN` 또는 `EVIDENCE_NEEDED`로 둔다.

## Stage 7 — Top 3 Client Analysis *(Phase 5)*

| | |
|---|---|
| 입력 | 우선순위 상위 후보 + MN03 · MN04 · MN05 · MN06 |
| 출력 | `ClientAnalysis` |

**MN 전체를 반복하지 않는다.** MN02 · MN07은 회사 차원 진단이므로 Client별로 반복하지 않는다.

해외 Client는 `international` 블록을 추가로 채운다: regulation · certification · tariff ·
logistics · exchange_rate · local_partner · distribution_structure · local_price ·
purchasing_power · entry_barrier · local_buyer · local_competitor.

`evidence`가 비면 `missing_evidence`가 필수다.

## Stage 8 — Proposal Strategy *(Phase 6)*

| | |
|---|---|
| 입력 | `ClientAnalysis` |
| 출력 | `ProposalStrategy` |

**제안서를 바로 작성하지 않는다.** 전략이 먼저다.

`proposal_objective`(제안 목표)가 비어 있으면 거부된다. `proposal_storyline` ·
`expected_objection` · `response_logic` · `additional_evidence_required`를 함께 만든다.

확인되지 않은 것을 확인된 것처럼 쓰지 않는다 — `examples/sample_project/proposal_strategy.json`의
`response_logic` 첫 항목이 그 예다(인증 미확인을 밝히고 확인 일정을 제안에 포함).

## Stage 9 — Pricing *(Phase 7)*

| | |
|---|---|
| 입력 | `ProposalStrategy` + 원가·물량·목표마진 |
| 출력 | `PricingResult` |

이 Harness는 **계산하지 않는다.** 두 블록을 만들어 넘긴다.

| 블록 | 내용 |
|---|---|
| `pricing_payload` | Pricing Harness의 `client_input.schema.json` 형태: `schema_version` `client_id` `case_id` `product` `tax` `fx` `costs` (+ `targets`) |
| `commercial_context` | client · country · problem · buyer · value_proposition · competitive_advantage · competitor · channel · expected_quantity · commercial_conditions |

Pricing Harness가 돌려주는 것: `analysis_result` (MODE A 현재가격 진단 / MODE B 목표가격 /
MODE C 허용원가 / BEP), 또는 Scenario Compare 결과. 그대로 `engine_result`에 보관한다.

연결 방식과 `core` 패키지명 충돌 주의사항은 `ARCHITECTURE.md` 6절에 있다.

## Stage 10 — Report Output *(Phase 9)*

| | |
|---|---|
| 입력 | 구조화된 Entity |
| 출력 | HTML · DOCX 초안 |

**HTML/DOCX/PDF는 Output이다. 원본 Data가 아니다.** Report는 항상 Entity를 읽어서 생성하며,
그 반대 방향은 없다.

---

## Reference Dashboard 4화면 *(Phase 8)*

| 화면 | 표시 |
|---|---|
| Project | Company · Target Market · Market Scope · Target Countries · Research Status · SWOT Status · Client Candidate Count · Proposal Status |
| SWOT / Issues | S/W/O/T · Key Issues · Strategic Implications · Evidence · Sources |
| Client Pipeline | Client · Country · Industry · Problem Fit · Solution Fit · Buyer · Priority · Status |
| Proposal Strategy | Client · Problem · Buyer · Solution · Value Proposition · Competitive Advantage · Pricing · Proposal Status |

화면은 4개로 제한한다. 라벨은 `locales/*.json`의 `screens` 섹션에 이미 준비되어 있다.

---

## 단계 사이의 공통 규칙

1. **순서를 건너뛰지 않는다.** Evidence → Finding → SWOT → Client → Analysis → Strategy →
   Pricing.
2. **각 단계는 앞 단계의 id를 참조한다.** 참조가 끊기면 불변식 검사에서 거부된다.
3. **근거가 없으면 `UNKNOWN` / `EVIDENCE_NEEDED` / `MISSING_EVIDENCE`로 남긴다.** 빈칸을
   그럴듯한 값으로 채우지 않는다.
4. **최종 판단은 사람이 한다.** 이 Harness는 판단 재료를 추적 가능한 형태로 만들어 준다.

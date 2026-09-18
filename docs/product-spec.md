# Product Spec — 단계별 입력과 출력

> 각 단계가 무엇을 받아 무엇을 내놓는지 정의한다. 원칙은 `HARNESS.md`, 구조는
> `ARCHITECTURE.md`, 필드 정의는 `docs/data-model.md`에 있다. 이 문서는 그 사이의 **흐름**을
> 다룬다.
>
> Stage 1–4가 구현되어 있다 (Phase 2–3). Stage 5 이후는 Phase 4–9에 걸쳐 구현된다.
> 각 단계에 Phase를 표시했다.

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

## Stage 1 — File Intake *(Phase 2 — 완료)*

| | |
|---|---|
| 입력 | 파일 `bytes` + `file_type` + `source_category` (+ 선택: `display_label`, `source_date`) |
| 출력 | `SourceMetadata` (저장 가능) + `EvidenceCandidate[]` (transient) |
| 규칙 | `docs/privacy.md` 1–5절 |

- `source_id`는 랜덤 UUID. **파일명은 전달 경로 자체가 없다** — 파서와 `IntakeSession.ingest()`
  시그니처에 `filename` 파라미터가 존재하지 않는다.
- 8종 전부 메모리에서 파싱된다. **이 구현은 temp file을 만들지 않는다** (memory-first).
  라이브러리·runtime·OS 내부까지 disk write 0을 보장한다는 뜻은 아니다 — `docs/privacy.md` 1절.
- 성공 시 `PURGED`, 실패 시 `FAILED` + `error_code`. 한 파일의 실패가 배치를 끝내지 않는다.
- 텍스트 레이어가 없는 스캔 PDF → `EXTRACT_NO_TEXT_LAYER`. **OCR은 범위 밖이다.**
- `detected_lang`은 항상 `None`이다 — 언어 판별 엔진을 넣지 않았고, 틀린 태그는 없는 태그보다
  나쁘다.

### Locator 형식

Locator가 `ResearchFinding.page_or_section`이 되어 결론의 추적 경로를 만든다.

| Type | Locator 예 | Segment 단위 |
|---|---|---|
| PDF | `p.7` | 페이지 내 문단 |
| DOCX | `¶12` · `table 2` | 문단, 표 |
| PPTX | `slide 4` · `slide 4 notes` | 슬라이드 본문, 발표자 노트 |
| XLSX | `utilities-ops!A1:C50` | 시트별 50행 블록 |
| CSV | `row 2-51` | 헤더 + 50행 블록 |
| TXT | `line 40-58` | 빈 줄로 구분된 블록 |
| MD | `## 운영 현황` | ATX 제목 구간 |
| HTML | `운영 현황 > p#4` | 블록 요소 (script·style·noscript·주석 제외) |

### 타입 판별

확장자는 주장일 뿐이므로 magic byte로 검증한다. DOCX·PPTX·XLSX는 **전부 ZIP이라 magic byte가
동일**하므로, package를 열어 `word/document.xml` · `ppt/presentation.xml` · `xl/workbook.xml`을
확인한다. 같은 한 번의 central directory 읽기로 zip bomb 상한도 함께 검사한다.

### 상한 (IntakePolicy)

| 항목 | 기본값 |
|---|---|
| `max_file_bytes` | 25 MB |
| `max_uncompressed_bytes` | 200 MB |
| `max_batch_bytes` | 100 MB |
| `max_display_label_chars` | 100 |

Core는 환경변수를 읽지 않는다. 다른 값이 필요하면 App이 `IntakePolicy`를 만들어 주입한다.

### Phase 2가 하지 않는 것

**`evidence_type`을 부여하지 않는다.** 문서에서 뽑은 조각은 `FACT`가 아니라 `FACT`가 될
재료다. FACT / INFERENCE / ASSUMPTION / MISSING_EVIDENCE 판정은 Master Note 질문을 적용하는
Stage 3에서만 일어난다. Phase 2가 보장하는 것은 그 판정이 **출처를 잃지 않는다**는 것이며,
`core.intake.provenance_of()`가 그 인계 지점이다.

## Stage 2 — Market Research *(Phase 3 — 완료)*

| | |
|---|---|
| 입력 | `EvidenceCandidate[]` + `SearchProvider` 결과 + `market_scope` / `target_countries` |
| 출력 | 추가 Evidence 후보 (아직 Finding이 아니다) |

- 기본 Adapter는 `manual` — 사용자가 제공한 자료만 사용한다. Web Search Adapter는 아직 없다.
- `SearchResult`는 **검색 결과 그 자체**이고 해석이 아니다. `core.research.ingest_search_results()`가
  이를 `SourceMetadata`(`source_origin = SEARCH_RESULT`) + `EvidenceCandidate`로 바꾸므로,
  파일에서 왔든 검색에서 왔든 **파이프라인 입력 타입이 하나**가 된다.
- 검색 자료에 가짜 `file_type`·`file_size`를 넣지 않는다. 대신 `title` · `publisher` ·
  `url` · `retrieved_at`을 채운다.
- **snippet 기반 FACT는 `MEDIUM`을 넘지 못한다.** snippet은 검색엔진이 고른 몇 줄이고 이
  Harness는 원문 페이지를 연 적이 없다. publisher·recency·corroboration과 무관하게 적용된다.
  실제 원문을 retrieve 하는 Adapter가 생기면 별도의 verified origin을 추가할지 후속 Phase에서
  검토한다.
- 국내·해외를 같은 Engine으로 처리한다. `market_scope`와 국가 필드로만 구분한다.

## Stage 3 — Master Note Diagnosis *(Phase 3 — 완료)*

| | |
|---|---|
| 입력 | `EvidenceCandidate[]` + `KnowledgeProvider.get_framework("MN02".."MN07")` |
| 출력 | `ResearchFinding[]` |

각 MN의 dimension이 곧 질문이다. 질문에 답할 Evidence가 없으면 답을 만들지 않고
`evidence_type = MISSING_EVIDENCE`로 남긴다.

**2-pass로 동작한다.** Pass 1은 Evidence에서 직접 확인되는 것(`FACT`)과 정직한 비답변
(`ASSUMPTION` · `MISSING_EVIDENCE`)만 만든다. Pass 2는 **Pass 1의 Finding을 인용해서**
`INFERENCE`를 만든다 — 추론이 transient한 `EvidenceCandidate`가 아니라 영속 Finding을
가리키게 하기 위해서다.

출처 규칙은 `docs/data-model.md` 3절의 표를 따른다: `FACT`만 `source_id`를 갖고,
`INFERENCE`는 `supporting_finding_ids`로 추적하며 source 계열 필드를 비워 둔다.

**모델이 만들 수 없는 것**: `mn_basis` · 모든 id · 출처 필드 · 타임스탬프 · `market_scope`.
파이프라인이 이미 아는 값이라 축소 스키마에서 아예 제외했고, 그래서 지어낼 방법이 없다.
모델이 인용한 evidence ref가 실재하지 않으면 그 Finding은 폐기되고 사유가 기록된다.

Framework 선택 기본값은 **MN02–MN07 전부**다. 어느 Framework가 이 자료에 해당하는지 고르는 것
자체가 분석 판단이므로, 키워드로 자동 축소하지 않는다 (`use_keyword_shortlist`는 기본 OFF).

## Stage 4 — SWOT / Key Issues *(Phase 3 — 완료)*

| | |
|---|---|
| 입력 | `ResearchFinding[]` |
| 출력 | `SWOTIssue[]` → `KeyIssue[]` |

**SWOT을 작성하라고 LLM에 바로 요청하지 않는다.** Finding을 분류·압축하는 단계다.
`finding_ids`가 비어 있으면 거부된다.

SWOT은 분류만 담는다. Key Issue는 **별도 Entity**이며 여러 SWOT을 묶는다 —
`KeyIssue.swot_issue_ids`가 최소 1개를 요구하므로 SWOT 없는 Key Issue도 불가능하다.

`strategic_implication`은 **필수**이며 의사결정 **지원**이다. 없는 후보는 필드를 비운 채
저장하지 않고 **통째로 거부**한다 — 반쯤 채워진 레코드는 완성된 것처럼 읽힌다.

의사결정 지원인지는 **어떤 동사를 피했는가가 아니라 무엇으로 구성됐는가**로 판단한다.
Prompt가 4가지를 요구한다: ① 현재 Evidence가 시사하는 내용 ② 조건·제약 ③ 확인되지 않은
Evidence ④ 다음 검증 포인트.

지시문처럼 보이는 표현(`진출한다` `we will` 등)은 **review flag**일 뿐 거부 사유가 아니다.
문자열 blacklist는 언어에 종속되고 양방향으로 틀린다 — "인증 요건을 먼저 확인해야 한다"는
정확히 원하는 산출물인데 순진한 blacklist는 이를 거부한다.

추가 출력: Missing Evidence 목록 · Additional Research Required 목록 · Rejection 목록
(모델이 만들었지만 근거 검증에서 버려진 항목 — 조용히 사라지지 않는다).

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

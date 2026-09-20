# Data Model

> 이 문서는 `core/models.py`와 `schemas/*.schema.json`을 설명한다. **세 곳은 항상 함께
> 고친다** — 필드를 추가하면 dataclass · JSON Schema · 이 문서를 같이 수정한다.
> `tests/test_schemas.py`가 앞의 두 곳이 어긋나면 실패한다.

Entity는 9개다. 전부 `core/models.py`에 정의되어 있고, 워크플로 순서대로 나열한다.

```
Project
  └─ SourceMetadata         업로드 파일 또는 검색 자료의 출처. 원문·파일명 없음
       └─ ResearchFinding   Evidence를 MN 기준으로 해석한 결과
            └─ SWOTIssue    Finding의 압축 (S/W/O/T 분류만)
                 └─ KeyIssue         여러 SWOT을 묶은 의사결정 질문 + 시사점
                      └─ ClientCandidate
                           └─ ClientAnalysis
                                └─ ProposalStrategy
                                     └─ PricingResult
```

---

## 공통 규약

| 항목 | 규칙 |
|---|---|
| ID | `new_id(prefix)` — `prj_` `src_` `fnd_` `swt_` `kis_` `cli_` `cla_` `prp_` `prc_` + UUID4 hex. **원본 파일명에서 파생하지 않는다** |
| 시각 | `utc_now()` — ISO-8601, 초 단위, timezone 포함 |
| `schema_version` | 모든 Entity에 존재. 현재 `"0.1"` |
| `lang` | 자유 텍스트 필드가 어느 언어로 쓰였는지. 번역 추적용 |
| enum | 안정적인 코드. **번역하지 않는다.** 표시 라벨은 `locales/*.json` |
| 직렬화 | `as_dict(entity)` → JSON-ready dict / `from_dict(cls, data)` → Entity (모르는 키는 예외) |

---

## Enum

| Enum | 값 |
|---|---|
| `EvidenceType` | `FACT` `INFERENCE` `ASSUMPTION` `MISSING_EVIDENCE` |
| `Confidence` | `HIGH` `MEDIUM` `LOW` `UNKNOWN` |
| `FitLevel` | `STRONG` `MODERATE` `WEAK` `UNKNOWN` `EVIDENCE_NEEDED` |
| `MarketScope` | `DOMESTIC` `INTERNATIONAL` |
| `SWOTCategory` | `STRENGTH` `WEAKNESS` `OPPORTUNITY` `THREAT` |
| `SalesPriority` | `P1` `P2` `P3` `DEFERRED` `UNKNOWN` |
| `SourceCategory` | `CONSULTING_OUTPUT` `COMPANY_DATA` `EXTERNAL_BUSINESS_DATA` `USER_PROVIDED` |
| `SourceOrigin` | `UPLOADED_FILE` `SEARCH_RESULT` `USER_PROVIDED` — 자료가 **어떻게 들어왔는가** (`SourceCategory`는 **무엇인가**) |
| `FitCriterion` | `PROBLEM_FIT` `SOLUTION_FIT` `CAPABILITY_FIT` `MARKET_ATTRACTIVENESS` `PURCHASING_POTENTIAL` `ACCESSIBILITY` `COMPETITIVE_SITUATION` `EVIDENCE_QUALITY` |
| `AnalysisDimension` | 19개 — MN03 8 · MN04 5 · MN05 2 · MN06 4. `docs/product-spec.md` Stage 7 참조 |
| `InternationalDimension` | 8개 |
| `PurchaseSignal` · `AccessRoute` | closed list. 두 Engine이 공유하므로 `core/models.py`에 있다 |
| `PriorityReasonCode` | `CORE_FIT_POSITIVE` `CORE_FIT_WEAK` `COMMERCIAL_SIGNAL_CONFIRMED` `PURCHASE_EVIDENCE_NEEDED` `ACCESS_EVIDENCE_NEEDED` `COMPETITIVE_BARRIER` `INSUFFICIENT_EVIDENCE` `SNIPPET_ONLY_LIMITATION` `IDENTITY_VERIFICATION_NEEDED` |
| `FileType` | `PDF` `DOCX` `PPTX` `XLSX` `HTML` `CSV` `TXT` `MD` |
| `ProcessingStatus` | `PENDING` `EXTRACTED` `FAILED` `PURGED` |
| `StorageMode` | `EPHEMERAL` `PERSISTENT` |
| `ClientStatus` | `CANDIDATE` `SCREENED` `PRIORITIZED` `ANALYZED` `PROPOSAL_DRAFTED` `DEFERRED` `REJECTED` |
| `ProposalStatus` | `NOT_STARTED` `STRATEGY_DRAFTED` `PRICING_REQUESTED` `PROPOSAL_DRAFTED` |
| `PricingStatus` | `NOT_REQUESTED` `PAYLOAD_READY` `COMPLETED` `FAILED` |

**왜 점수가 아니라 순서형 enum인가.** 근거가 없을 때 숫자를 만들면 그 숫자가 곧 결론처럼
쓰인다. `UNKNOWN`과 `EVIDENCE_NEEDED`를 1급 값으로 두면 "모른다"가 화면에 그대로 남는다.
가중합 총점 필드는 **의도적으로 없다** (`HARNESS.md` 6-3).

---

## 1. Project

`schemas/project.schema.json`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `project_id` | str | ✓ | |
| `company_name` | str | ✓ | 분석 대상 회사 |
| `market_scope` | list[MarketScope] | ✓ | 최소 1개 |
| `target_countries` | list[str] | | ISO 3166-1 alpha-2 |
| `target_industries` | list[str] | | |
| `ui_lang` | str | | 조작 화면 언어 |
| `output_lang` | str | | 산출물 언어 |
| `storage_mode` | StorageMode | ✓ | 기본 `EPHEMERAL` |
| `created_at` | str | | |
| `schema_version` | str | ✓ | |

**4개 언어축**은 서로 독립이다: `ui_lang`(조작) · `SourceMetadata.detected_lang`(원문) ·
`target_countries`(대상 시장) · `output_lang`(산출물). 따라서 "UI 한국어 / 대상국 베트남 /
원문 베트남어·영어 / 출력 영어" 조합이 성립한다.

## 2. SourceMetadata

`schemas/source_metadata.schema.json`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `source_id` | str | ✓ | 랜덤. 파일명에서 파생 금지 |
| `project_id` | str | ✓ | |
| `source_origin` | SourceOrigin | ✓ | `UPLOADED_FILE` / `SEARCH_RESULT` / `USER_PROVIDED` |
| `display_label` | str? | | **사용자가 직접 입력한 표시명.** 파일명과 별개이며 자동 생성하지 않는다. 최대 100자, control character 제거. 로그 allowlist에 **없다** |
| `source_category` | SourceCategory | ✓ | |
| `file_type` | FileType? | | **`UPLOADED_FILE` 전용** |
| `file_size` | int? | | **`UPLOADED_FILE` 전용** |
| `page_count` | int? | | **`UPLOADED_FILE` 전용** |
| `title` | str? | | **`SEARCH_RESULT` 전용** (최대 300자) |
| `publisher` | str? | | **`SEARCH_RESULT` 전용.** 없으면 confidence 상한이 내려간다 |
| `url` | str? | | **`SEARCH_RESULT` 전용** |
| `retrieved_at` | str? | | **`SEARCH_RESULT` 전용.** 발행일과 다른 사실이다 |
| `source_date` | str? | | 자료 자체의 날짜 |
| `detected_lang` | str? | | |
| `processing_status` | ProcessingStatus | ✓ | |
| `error_code` | str? | | **예외 메시지가 아니라 코드** |
| `ingested_at` | str | | |
| `schema_version` | str | ✓ | |

> **`filename`도 `text`도 없다.** 파일명 자체가 민감할 수 있고(고객사명·프로젝트 코드),
> 문서 원문은 ephemeral 모드에서 저장 대상이 아니다. 스키마의 `additionalProperties: false`가
> Adapter가 몰래 추가하는 것도 막고, 파서와 `IntakeSession.ingest()` 시그니처에 `filename`
> 파라미터가 아예 없어서 전달 경로 자체가 없다. `tests/test_privacy.py`가 검사한다.
>
> `display_label`은 파일명이 아니다. **사람이 타이핑한 값**이며, 자료 12개를 올린 분석가가
> 어느 문서에서 나온 근거인지 알아보기 위한 것이다. PERSISTENT 모드에서는 이 값이 조직 DB에
> 저장된다 — 사용자에게 알리는 것은 도입 조직의 책임이다 (`docs/privacy.md` 6절).

### Transient: EvidenceCandidate (Entity 아님)

Intake가 만드는 `EvidenceCandidate`는 문서 텍스트를 담으므로 **영속 Entity가 아니다.**
`core/intake/models.py`에 있고, `schemas/`에 스키마가 없으며, `StorageProvider`에 저장
메서드가 없다. 요청 수명 안에서 Phase 3로 전달되고 끝난다.

```
source_id · locator · text · kind · order
```

`core.intake.provenance_of(candidate, source)`가 이 중 출처 부분을 `ResearchFinding`이
요구하는 형태(`source_id` `source_type` `page_or_section` `source_date`)로 변환한다.

## 3. ResearchFinding

`schemas/research_finding.schema.json`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `finding_id` | str | ✓ | |
| `project_id` | str | ✓ | |
| `finding` | str | ✓ | 발견사항 진술 |
| `evidence_type` | EvidenceType | ✓ | |
| `mn_basis` | list[str] | ✓ | 최소 1개. 어느 MN 질문에서 나왔는가 |
| `confidence` | Confidence | ✓ | |
| `market_scope` | MarketScope | ✓ | |
| `supporting_finding_ids` | list[str] | | **`INFERENCE` 전용.** 추론의 근거가 된 Finding들 |
| `source_id` | str? | | **`FACT`만** 가진다 |
| `source_type` | SourceCategory? | | |
| `page_or_section` | str? | | 출처 내 위치 |
| `source_date` | str? | | |
| `evidence_summary` | str? | | |
| `country` | str? | | |
| `lang` · `created_at` · `schema_version` | | | |

### evidence_type별 provenance 규칙

| type | `source_id` | `supporting_finding_ids` | 비고 |
|---|---|---|---|
| `FACT` | **필수** | 비어 있어야 함 | Evidence 1개에 직접 연결 |
| `INFERENCE` | **None** | **1개 이상 필수** | source 계열 필드 전부 None |
| `ASSUMPTION` | None | 비어 있어야 함 | `evidence_summary`에 가정임을 명시 |
| `MISSING_EVIDENCE` | None | 비어 있어야 함 | `evidence_summary`에 **무엇이 필요한지** 필수 |

> **INFERENCE가 source_id를 빌려오지 않는 이유.** 첫 근거 Finding의 `source_id`를 복사하면
> 추론이 "문서가 말한 것"처럼 보인다. 분석이 사람을 오도하는 가장 설득력 있는 방법이고,
> `core/evidence.py`가 이를 거부한다.

## 4. SWOTIssue

`schemas/swot_issue.schema.json`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `issue_id` · `project_id` | str | ✓ | |
| `category` | SWOTCategory | ✓ | |
| `statement` | str | ✓ | |
| `finding_ids` | list[str] | ✓ | **최소 1개** (스키마 `minItems: 1`) |
| `mn_basis` | list[str] | | 인용한 Finding들의 `mn_basis` 합집합 |

> `key_issue`·`strategic_implication`은 **`SWOTIssue`에 없다.** 실제 이슈는 보통 여러 SWOT에
> 걸쳐 있어서 카드 하나에 붙은 문자열로는 표현되지 않는다. 5절 `KeyIssue` 참조.

## 5. KeyIssue

`schemas/key_issue.schema.json`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `key_issue_id` · `project_id` | str | ✓ | |
| `statement` | str | ✓ | **사람이 답해야 하는 질문.** "어느 시장을 먼저 볼 것인가" |
| `decision_area` | str | ✓ | `market_priority` `buyer_selection` `competitive_position` `pricing_fit` `evidence_gap` 등 |
| `swot_issue_ids` | list[str] | ✓ | **최소 1개** (스키마 `minItems: 1`) |
| `finding_ids` | list[str] | | SWOT 뒤의 Finding들이 자동 포함된다 |
| `strategic_implication` | str | ✓ | **필수. 의사결정 지원.** 없으면 KeyIssue 자체가 생성되지 않는다 |
| `missing_evidence` | list[str] | | 결정 전에 확인해야 할 것 |
| `confidence` | Confidence | ✓ | 근거 Finding 중 최저값을 넘지 못한다 |

> **부분 Entity를 남기지 않는다.** `strategic_implication`이 없는 후보는 필드를 비운 채
> 저장하는 대신 **통째로 거부**한다. 반쯤 채워진 레코드는 나중에 읽는 사람에게 완성된 것처럼
>보이기 때문이다. Storage에 있는 KeyIssue는 항상 `key_issue.schema.json`을 **완전히**
> 만족한다.
>
> 거부는 `ResearchOutcome.rejections`에 남고, 거기에는 **code · stage · reference만** 들어간다
> (원문 없음).

Phase 4 Client Discovery가 **안정적 입력 Entity로 사용**한다.

## 6. ClientCandidate

`schemas/client_candidate.schema.json`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `client_id` · `project_id` | str | ✓ | |
| `client_name` · `country` · `industry` | str | ✓ | |
| `discovery_rationale` | str | ✓ | 우리 무엇을 그들 어떤 문제에 |
| `source_ids` | list[str] | ✓ | **최소 1개.** 아래 참조 |
| `market_scope` | MarketScope | ✓ | |
| `finding_ids` | list[str] | ✓ | 최소 1개 |
| `key_issue_ids` | list[str] | | 어떤 의사결정 때문에 이 조직을 찾았는가 |
| `fit` | list[FitAssessment] | ✓ | **정확히 8개** |
| `priority` | PriorityDecision | ✓ | `band` · `reason_codes[]` · `missing_evidence[]` |
| `identity` | OrganizationIdentity? | | `legal_name` · `domain` · `organization_identifier` |
| `missing_evidence` | list[str] | | |
| `status` | ClientStatus | ✓ | |

### "왜"가 세 가지이고, 답도 세 곳에 있다

| 질문 | 답이 있는 곳 |
|---|---|
| **왜 이 회사가 후보 풀에 들어왔는가** | `ClientCandidate.source_ids` — 이 조직이 **실제로 등장한 자료**. 발굴·식별 provenance 전용이며, 기준별 근거를 모으는 필드가 **아니다** |
| **왜 Problem Fit이 STRONG인가** | 해당 `FitAssessment.source_ids` / `finding_ids` |
| **어떤 KeyIssue 때문에 찾았는가** | `ClientCandidate.key_issue_ids` |

`source_ids`가 필수인 것이 **지어낸 회사명을 저장 불가능하게 만드는 통제**다. 아무 자료도
언급하지 않는 이름에는 인용할 출처가 없다.

### Candidate-level 집계는 파생 필드다

`finding_ids`와 `missing_evidence`는 **모델이 만들지 않고 pipeline이 계산한다.**

```
ClientCandidate.finding_ids      = sorted(set(⋃ FitAssessment.finding_ids))
ClientCandidate.missing_evidence = sorted(set(⋃ FitAssessment.missing_evidence))
PriorityDecision.missing_evidence = 같은 canonical set
```

`core/models.py`의 `aggregate_finding_ids()` · `aggregate_missing_evidence()` 한 곳에서만
계산되고, `check_client_candidate()`가 관계가 깨진 Candidate를 **거부한다.** LLM 출력 스키마에는
candidate-level `finding_ids`·`missing_evidence`가 없다 — 물어보면 두 번째 답이 생기고, 그 둘은
한쪽 assessment가 수정되는 순간 어긋난다.

**canonical evidence relationship은 각 `FitAssessment`에 있다.** 집계는 읽는 사람과 이후
Phase의 편의를 위한 것이며, Phase 5에서 사용해도 되지만 근거의 출처로 취급하지 않는다.

정렬은 삽입 순서가 아니라 사전순이다. 같은 8개 assessment가 조립 순서에 상관없이 같은 목록을
만들어야 재현 가능하다.

### FitAssessment

`criterion` · `level` · `reason`(최대 500자) · `finding_ids[]` · `source_ids[]` ·
`missing_evidence[]`

| 규칙 | |
|---|---|
| 8개 criterion 전부 존재 | 아무도 판단하지 않은 항목은 `UNKNOWN`으로 명시한다. 누락은 "안 봤다"와 "보고도 몰랐다"를 구분 불가능하게 만든다 |
| `STRONG`/`MODERATE` | `finding_ids` 또는 `source_ids` 최소 1개 |
| `EVIDENCE_NEEDED` | `missing_evidence` 최소 1개 |
| `reason` | 해석 요약. 원문 복사 금지 (500자 상한) |

**8개 기준의 방향은 전부 같다.** `STRONG` = 사업개발 관점에서 유리. 특히
`COMPETITIVE_SITUATION`은 **경쟁이 강하면 `WEAK`** 다 — 강한 incumbency와 높은 전환장벽은
불리한 상황이다.

### PriorityDecision

`band`(SalesPriority) · `reason_codes[]`(PriorityReasonCode) · `missing_evidence[]`

숫자 score·weight 필드가 **없다.** band는 `core/client/priority.py`의 규칙표가 계산하며
모델이 관여하지 않는다. `reason_codes`는 코드이고, 사람이 읽는 문장은 `locales/*.json`이
렌더한다.

## 7. ClientAnalysis

`schemas/client_analysis.schema.json` · **사람이 선택한** Client 1개 · MN03/04/05/06만 사용

| 필드 | 타입 | 필수 | |
|---|---|---|---|
| `client_id` | str | ✓ | 선택된 `ClientCandidate` |
| `our_solution` | str | ✓ | **입력값.** 모델 출력이 아니다 |
| `claims` | list[AnalysisClaim] | ✓ | **정확히 19개** |
| `international_claims` | list[InternationalClaim] | ✓ | INTERNATIONAL일 때만 8개 |
| `finding_ids` | list[str] | ✓ | 파생 |
| `missing_evidence` | list[str] | ✓ | 파생 |
| `market_scope` `mn_basis` `lang` `created_at` | | | |

**`sales_priority`가 없다.** Priority의 SSOT는 `ClientCandidate.priority`이고 Phase 4의 규칙표가
정한다. 여기에 두 번째 band를 두면 한 Client에 답이 둘이 되고, 어느 쪽이 현재인지 말해 줄 것이
없다. Phase 5는 band를 읽지도 쓰지도 않는다.

### AnalysisClaim

`dimension` · `statement`(≤500자) · `finding_ids` · `missing_evidence` +
파생 `evidence_type` · `confidence` · `framework_basis` + `organization_name`(named-org 전용) ·
`access_route`(SALES_ACCESS_ROUTE 전용)

평평한 `Optional[str]` 20개와 공용 `evidence` 버킷 하나를 대체한 구조다. 예전 구조로는
**`buyer`의 근거와 `competitive_advantage`의 근거를 구분할 수 없었다** — `ClientCandidate`가
8개 기준마다 참조를 갖기 전과 같은 결함이다.

**`source_ids`를 저장하지 않는다.** SSOT는 `finding_ids`이고 출처는
`core.analysis.source_ids_for(claim, findings_by_id)`로 파생한다. `FitAssessment`가 `source_ids`를
갖는 것은 Phase 4에서 finding 없이 snippet을 직접 인용하는 경로가 있기 때문이고, Phase 5의 claim은
전부 finding을 경유한다 — 의도적 비대칭이다.

### evidence_type은 supporting finding의 복사본이 아니다

FACT 세 개를 엮은 새 결론은 INFERENCE다. 엮는 행위 자체가 claim이고 그것을 수행한 문서는 없다.
그래서 종류는 **질문**이 정한다 (`core/analysis/dimensions.py`).

| kind | 의미 | FACT 가능 |
|---|---|---|
| `DIRECT` | 문서가 말한다 | FACT finding이 있으면 ✓ |
| `MIXED` | 드물게 명시된다 | 해당 dimension의 framework로 읽힌 FACT가 있을 때만 ✓ |
| `SYNTHESIS` | 언제나 결론이다 | ✗ |

`confidence`는 `weakest(supporting) → cap(dimension ceiling)`. 둘 다 모델이 정하지 않는다.

### 파생 집계

```
ClientAnalysis.finding_ids      = sorted(set(⋃ claim.finding_ids))
ClientAnalysis.missing_evidence = sorted(set(⋃ claim.missing_evidence))
```

`ClientCandidate`와 같은 함수(`aggregate_finding_ids` · `aggregate_missing_evidence`)를 쓰고,
`check_client_analysis()`가 어긋나면 거부한다.

### InternationalClaim

같은 필드, **별도 dataclass**다. `core/models.py`의 `_coerce`가 Union을 첫 멤버로 해석하기
때문에 두 dimension enum을 한 dataclass로 합치면 해외 값이 역직렬화에서 깨진다.

8개: `LOCAL_BUYING_STRUCTURE` `REGULATION` `CERTIFICATION` `TARIFF` `LOGISTICS` `CURRENCY_FX`
`ENTRY_BARRIER` `LOCAL_PARTNER_REQUIREMENT`.

기존 `InternationalContext`의 `local_competitor` · `local_price` · `purchasing_power` ·
`distribution_structure`는 공통 dimension이 답하므로 제외했다. `InternationalContext` 타입 자체는
Phase 6/7을 위해 모델에 남아 있다.

`market_scope != INTERNATIONAL`이면 `international_claims`는 비어 있어야 한다. **국가별 별도
Engine을 만들지 않는다** — 같은 pipeline·같은 finding·같은 provenance에 호출 한 번이 붙을 뿐이다.

`EvidenceRef`: `finding_id`(필수) · `source_id` · `note`. `ProposalStrategy`가 계속 사용한다.

## 8. ProposalStrategy

`schemas/proposal_strategy.schema.json`

| 필드 | 타입 | 설명 |
|---|---|---|
| `strategy_id` `project_id` `client_id` `client_name` `country` | str | 필수 |
| `problem` `buyer` `decision_maker` | str? | |
| `proposal_objective` | str? | 이 제안이 무엇을 달성하려는가. 비어 있으면 `check_proposal_strategy`가 거부 |
| `proposed_solution` `value_proposition` `competitive_advantage` `key_message` | str? | |
| `proposal_storyline` | list[str] | 논리 순서 |
| `expected_objection` · `response_logic` | list[str] | |
| `additional_evidence_required` | list[str] | |
| `evidence` | list[EvidenceRef] | |
| `pricing_input` | dict? | Pricing Harness 인계. Phase 7까지 `None` |
| `status` | ProposalStatus | |

**제안서 문서를 먼저 만들지 않는다.** Strategy가 먼저다.

## 9. PricingResult

`schemas/pricing_result.schema.json`

| 필드 | 타입 | 설명 |
|---|---|---|
| `pricing_result_id` `project_id` `client_id` | str | 필수 |
| `pricing_payload` | dict | **Pricing Harness의 `client_input.schema.json`에 맞춘다**: `schema_version` `client_id` `case_id` `product` `tax` `fx` `costs` |
| `commercial_context` | dict | Pricing Engine이 소비하지 않는 영업 컨텍스트 |
| `engine_result` | dict? | Pricing Harness의 `analysis_result` 원본 |
| `engine_version` | str? | |
| `status` | PricingStatus | |
| `error_code` | str? | |

> **두 블록을 분리한 이유.** `client` · `country` · `problem` · `buyer` ·
> `value_proposition` · `competitive_advantage` · `competitor` · `channel` ·
> `commercial_conditions`는 Pricing Engine이 쓰지 않고 제안서가 쓴다. 이걸 한 덩어리로
> 보내면 Pricing Harness 스키마를 고쳐야 하고, 두 저장소가 서로를 붙잡는다.
> 자세한 내용은 `ARCHITECTURE.md` 6절.

---

## 필드를 추가할 때

1. `core/models.py`의 dataclass에 추가
2. 해당 `schemas/*.schema.json`의 `properties`에 추가 (필수면 `required`에도)
3. 이 문서의 표에 추가
4. 사용자에게 보이는 값이면 `locales/ko.json` · `locales/en.json`의 `fields`에 라벨 추가
5. `pytest` — `test_schemas.py`가 1·2의 일치를, `test_locales.py`가 4를 검사한다

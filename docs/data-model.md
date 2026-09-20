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

`schemas/proposal_strategy.schema.json` · **전략이지 문서가 아니다**

| 필드 | | |
|---|---|---|
| `analysis_id` | ✓ | 이 전략이 읽은 `ClientAnalysis`. 모든 dimension 참조가 여기서 해석된다 |
| `objective` · `objective_source` | | **기본값 없음.** 둘은 함께 설정되거나 함께 비어 있다 |
| `selected_solution_elements` | ✓ | `list[SelectedSolutionElement]` — 호출자의 **ref + 원문 text**. 모델이 쓴 것이 아니다 |
| `value_proposition` · `key_message` | | `StrategyStatement` |
| `storyline` | ✓ | `list[StoryStep]` |
| `objections` | ✓ | `list[ProposalObjection]` — 반론과 대응이 **한 객체** |
| `evidence_needs` | ✓ | `list[EvidenceNeed]` |

### 삭제된 것과 그 이유

| | |
|---|---|
| `problem` `buyer` `decision_maker` `competitive_advantage` | Phase 5 claim의 사본이었다. 사본은 원본에서 어긋나고, 어느 쪽이 현재인지 말해 줄 것이 없다 |
| `expected_objection` + `response_logic` | **위치로만 짝지어진 병렬 리스트.** 반론 하나를 지우면 그 뒤의 모든 대응이 조용히 재배치된다 — 정보를 잃는 것이 아니라 **틀린 정보를 만드는** 구조다 |
| `evidence: list[EvidenceRef]` | 공용 버킷. 근거는 각 부분이 갖는다 |
| `pricing_input: Optional[dict]` | opaque라 검증이 없었고, `PricingResult`가 이미 `pricing_payload`·`commercial_context`를 갖는다. 세 번째 사본이자 유일하게 검사되지 않는 사본이었다 |

`EvidenceRef` 타입 자체는 public schema 호환성 때문에 모델에 남겨 둔다 (Phase 9에서 정리 검토).

### 중첩 value object 4개

```
SelectedSolutionElement   ref · text
StrategyStatement   text · dimensions · solution_element_refs · missing_evidence
StoryStep           step_type · message · dimensions · missing_evidence
ProposalObjection   objection · basis · dimensions
                    · response · response_dimensions · missing_evidence
EvidenceNeed        need · timing · dimension
```

전부 `AnalysisDimension`으로 Phase 5 claim을 가리킨다. claim은 id가 없는 value object이고
`(analysis_id, dimension)`이 곧 주소이므로 새 id 체계가 필요 없다. **원문도 finding_ids도
복제하지 않는다** — 필요하면 `ClientAnalysis`에서 파생한다.

### ref와 text를 분리한다

```
SelectedSolutionElement   ref = 안정적 참조 id   ·   text = 호출자의 정확한 원문
StrategyStatement.solution_element_refs         →  selected_solution_elements[*].ref
```

| | |
|---|---|
| `ref` | 다른 부분이 가리키는 **식별자**. Phase 7의 관계 키, Phase 9의 데이터 참조 |
| `text` | 사람에게 **보여주는 내용**. 호출자의 원문 그대로이며 모델이 쓰지 않는다 |

**text를 식별자로 쓰지 않는다.** 산문을 자연키로 쓰면 우연히 같은 문구를 가진 서로 다른
element가 하나로 합쳐지고, 문구를 다듬는 순간 그것을 가리키던 모든 statement가 조용히 끊어진다.
중복 제거도 text가 아니라 `ref` 기준이다 — 같은 문구의 두 element는 여전히 두 개다.

`value_proposition`과 `key_message`는 **둘 다 무언가를 제안하기 위해 존재하므로** 각각 최소
1개의 ref를 가리켜야 하고, 그 ref는 `selected_solution_elements[*].ref`에 있어야 한다. 이
검사는 호출자 목록 없이 레코드만으로 수행된다.

`proposed_solution`은 `selected_solution_elements[*].text`만 이어 붙여 만든다.

*"Solution을 언급하는 경우"*를 구조적으로 감지하려면 semantic verifier가 필요하므로, 두
statement 모두에 **무조건** 요구하는 쪽으로 구현했다. 제안할 것을 가리키지 않는 value
proposition은 value proposition이 아니라 관찰이다.

**이것이 문장의 정확성을 보장하지는 않는다.** 제안된 것이 우리가 받은 목록에서 나왔다는 것만
보장하고, 산문이 그 element를 정확히 서술하는지는 판정하지 않는다. `value_proposition` ·
`key_message` · `storyline` · `response`의 의미적 정확성은 현재 **best-effort**이며
`docs/development-guide.md`의 semantic relevance validation backlog 대상이다. 그 판정을 위한
verifier를 만들지 않았다.

### 새 enum 5개

| | |
|---|---|
| `ProposalObjective` | 8개. `POC`(기술 입증)와 `PILOT`(실제 운영 배치)은 승인 주체가 달라 분리했다 |
| `ObjectiveSource` | `HUMAN` · `AI_SUGGESTED` |
| `StoryStepType` | 6개. `IMPLEMENTATION`은 만들지 않았다 |
| `ObjectionBasis` | `EVIDENCE_BACKED` · `ANTICIPATED` |
| `EvidenceTiming` | 5개. 순서 4개 + `UNCLASSIFIED`. 점수가 아니다 |

### 불변식

`objective`와 `objective_source`는 함께 있거나 함께 없다 · objective 없이
`STRATEGY_DRAFTED`가 될 수 없다 · `proposed_solution`은 `selected_solution_elements` 없이 존재할
수 없다 · 두 statement는 element를 최소 1개 가리켜야 하고 그것은 선택된 element여야 한다 ·
`EVIDENCE_BACKED` 반론은 dimension 필수 · 근거도 gap도 없는 response는 거부 · 참조된 dimension은
analysis에서 **확정된** 것이어야 한다.

### 분류되지 않은 gap은 승격시키지 않는다

Phase 5의 gap은 전부 전달되고, 아무도 시점을 정하지 않은 것은 `UNCLASSIFIED`로 남는다.
가장 이른 시점으로 자동 승격하면 분석이 주장한 적 없는 긴급성을 만들어내고, 일단 기록되고 나면
**"누군가 제안 전 필수라고 판단했다"와 "아무도 안 봤다"를 구분할 수 없다.**

## 9. PricingResult

`schemas/pricing_result.schema.json`

| 필드 | 타입 | 설명 |
|---|---|---|
| `pricing_result_id` `project_id` `client_id` | str | 필수 |
| `strategy_id` | str | 이 case가 가격을 매기는 `ProposalStrategy` |
| `analysis_id` | str | 그 전략이 읽은 `ClientAnalysis`. `commercial_context`는 저장소 경계를 넘어온 복사본이고, 출처 없는 복사본은 다시 대조할 수 없다 |
| `pricing_case_id` | str | **이 case.** 외부 payload의 `case_id`가 된다 |
| `pricing_payload` | dict | **Pricing Harness의 `client_input.schema.json`에 맞춘다**: `schema_version` `client_id` `case_id` `product` `tax` `fx` `costs` (+ `targets` `meta`) |
| `commercial_context` | dict | 이 case를 설명하는 확정 context. **전송하지 않는다** |
| `engine_result` | dict? | Pricing Harness의 `analysis_result` 원본. 재해석하지 않는다 |
| `engine_version` | str? | `engine_result.source.engine_version`에서 온다 |
| `status` | PricingStatus | |
| `error_code` | str? | `FAILED`일 때만 |

### `case_id`는 `strategy_id`가 아니다

한 `ProposalStrategy`에서 여러 pricing case가 나온다 — 범위를 바꾼 견적, 물량을 바꾼 견적,
원가표를 고친 재산출. 전략 id를 case id로 쓰면 두 번째 case가 그쪽 기록에서 첫 번째를
덮어쓴다. 같은 case를 다시 만드는 것이 의도라면 `pricing_case_id`를 그대로 넘긴다.

### 두 블록

`pricing_payload`만 저장소 경계를 넘는다. `commercial_context`는 **보내지 않는다** —
그쪽 스키마에 필드가 없고 최상위가 닫혀 있다. 열린 `meta`에는 `strategy_id` · `analysis_id`
두 개만 들어간다.

`commercial_context`에 담기는 것:

```
pricing_case_id · strategy_id · analysis_id · client_id · client_name · country · market_scope
objective · objective_source
offered[]            ref · text · component_id        (payload가 못 싣는 결속)
claims{}             MN06 4개는 항상, 미확정이면 established:false
                     확정된 PROBLEM · KBF · COMPETITIVE_ADVANTAGE
international_claims{}  INTERNATIONAL일 때 TARIFF · CURRENCY_FX
evidence_needs[]     BEFORE_PRICING · BEFORE_CONTRACT
                     각 항목: gap_ref · need · timing · dimension
open_gap_counts{}    모든 timing의 건수
expected_quantity · commercial_conditions[]
```

복사되는 claim은 `statement` · `evidence_type` · `confidence` · `finding_ids` ·
`framework_basis`를 함께 싣는다. 경계를 넘으면 `analysis_id`를 해석할 수 없으므로, 문장만
복사하면 `PRICE_SENSITIVITY`가 LOW ceiling의 SYNTHESIS라는 사실이 사라진다. **근거 원문은
복사하지 않는다** — `finding_ids`로 도달한다.

분석 전체를 복제하지 않는 것은 data minimization이다. 나머지 14개 dimension은
`analysis_id` 하나 건너에 있다.

### PricingStatus

| 값 | 의미 |
|---|---|
| `NOT_REQUESTED` | 아직 pricing을 요청하지 않았다 |
| `HANDOFF_BLOCKED` | payload는 있으나 `BEFORE_PRICING` 선행조건이 열려 있다 |
| `PAYLOAD_READY` | 전달 가능 |
| `COMPLETED` | `engine_result` 보관됨 |
| `FAILED` | `error_code` 필수 |

`NOT_REQUESTED`와 `HANDOFF_BLOCKED`를 합치지 않는 이유는 `EvidenceTiming.UNCLASSIFIED`를
따로 둔 이유와 같다 — 기록된 뒤에 "아무도 요청 안 함"과 "요청했는데 선행조건이 열려 있음"을
구분할 수 없게 된다.

### gap은 ref와 display text를 분리한다

`commercial_context.evidence_needs[*]`는 `gap_ref`(machine reference)와 `need`(사람이 읽는
문장)를 **둘 다** 싣는다. Phase 8 UI는 `need`를 표시하고 `gap_ref`를 되돌려 보낸다.
`SelectedSolutionElement`의 `ref`/`text`와 같은 장치이고 같은 이유다 — 산문은 식별자가 아니다.

`PricingGap`은 `core/pricing_bridge/gaps.py`의 transient value object다. Entity가 아니고
`schemas/`에 스키마가 없다. gap의 정본은 `ProposalStrategy.evidence_needs`이며, `gap_ref`는
거기서 결정적으로 파생된다 — 저장하면 같은 관계의 두 번째 사본이 된다. 파생 규칙은
`docs/product-spec.md` Stage 9에 있다.

---

## 필드를 추가할 때

1. `core/models.py`의 dataclass에 추가
2. 해당 `schemas/*.schema.json`의 `properties`에 추가 (필수면 `required`에도)
3. 이 문서의 표에 추가
4. 사용자에게 보이는 값이면 `locales/ko.json` · `locales/en.json`의 `fields`에 라벨 추가
5. `pytest` — `test_schemas.py`가 1·2의 일치를, `test_locales.py`가 4를 검사한다

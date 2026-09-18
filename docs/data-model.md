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
| `market_scope` | MarketScope | ✓ | |
| `finding_ids` | list[str] | ✓ | 최소 1개 |
| `fit_screening` | FitScreening | ✓ | `problem_fit` `solution_fit` `capability_fit` |
| `priority` | PriorityEvaluation | ✓ | 아래 참조 |
| `status` | ClientStatus | ✓ | |

`PriorityEvaluation`: `market_attractiveness` · `purchasing_potential` · `accessibility` ·
`competitive_situation` · `evidence_quality` (전부 `FitLevel`) + `sales_priority`
(`SalesPriority`) + `rationale`.

`fit_screening` 3개 + `priority` 5개 = `HARNESS.md` 7절의 **8개 기준**. `sales_priority`는
**사람의 결정**이며 5개 평가에서 자동 계산하지 않는다.

## 7. ClientAnalysis

`schemas/client_analysis.schema.json` · MN03/04/05/06만 사용

| 그룹 | 필드 |
|---|---|
| 식별 | `analysis_id` `project_id` `client_id` `client_name` `country` `industry` |
| MN03 | `company_summary` `business_issue` `user` `buyer` `decision_maker` `problem` `problem_severity` |
| MN04 | `current_solution` `competitor` `substitute` `kbf` `our_solution` `value_proposition` `competitive_advantage` |
| MN05 | `sales_access_route` `potential_partner` |
| MN06 | `pricing_implication` |
| 근거 | `evidence` (list[EvidenceRef]) · `missing_evidence` (list[str]) |
| 판단 | `sales_priority` `market_scope` |
| 해외 | `international` (InternationalContext?) |

`EvidenceRef`: `finding_id`(필수) · `source_id` · `note`.

`InternationalContext` (해외일 때만): `local_buyer` `local_competitor` `regulation`
`certification` `tariff` `logistics` `exchange_rate` `local_partner`
`distribution_structure` `local_price` `purchasing_power` `entry_barrier`.

> 별도 객체로 둔 이유: 국내 프로젝트가 빈 해외 필드 12개를 끌고 다니지 않게 한다.
> **국가별 별도 Engine을 만들지 않는다** — `market_scope`와 이 객체로만 구분한다.

`evidence == []`이면 `missing_evidence`가 비어 있을 수 없다 (`core/evidence.py`).

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

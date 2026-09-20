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

## Stage 5 — Client Candidate Discovery *(Phase 4 — 완료)*

| | |
|---|---|
| 입력 | `EvidenceCandidate[]` + `ResearchFinding[]` + `KeyIssue[]` + Capability/Solution |
| 출력 | `ClientCandidate[]` + `DiscoveryHypothesis[]`(transient) |

**회사부터 찾지 않는다.** 먼저 `ClientDiscoveryCriteria`(transient DTO)로 "어떤 기업을 찾아야
하는가"를 구조화한 뒤, Evidence에서 조직명을 추출한다.

### 지어낸 회사명이 후보가 될 수 없는 이유

```
모델 출력   {name, evidence_ref}  ← 이 두 개만
   ↓
검증 1      evidence_ref가 블록에 존재하는가
검증 2      name이 그 구절 텍스트에 **문자 그대로** 존재하는가
   ↓
VerifiedOrganization → ClientCandidate (source_ids 필수)
```

매칭은 **Unicode 정규화(NFKC) · casefold · 공백 정규화 · 토큰 단위 비교 · 제한적 법인격
접미사 · 닫힌 한국어 조사 목록**까지만 허용한다.

### 허용/금지 매트릭스

| Evidence | Model | | 이유 |
|---|---|---|---|
| `Mekong Aqua Utilities` | `Mekong Aqua Utilities` | 허용 | 같은 토큰 |
| `Mekong Aqua Utilities Co., Ltd.` | `Mekong Aqua Utilities` | 허용 | 승인된 법인격 차이 |
| `Mekong Aqua Utilities가 사업을 발표했다.` | `Mekong Aqua Utilities` | 허용 | 조사는 단어가 아니다 |
| `Mekong Aqua Utilities` | `Mekong Aqua` | **거부** | `Utilities`는 이름의 일부다 |
| `AlphaBeta Industrial` | `Alpha` | **거부** | 토큰조차 아니다 |

아래 두 줄이 핵심이다. 단순 substring 검사는 둘 다 통과시키고 **검증이 성공한 것으로 보인다** —
잘못된 조직이 출처까지 붙은 채로 내려가고, 의심스럽다는 표시가 아무데도 없다.

**규칙은 "이름이 본문의 이름 전체를 설명해야 한다"다.** `Utilities`(이름의 일부)와
`announced`(다음 단어)를 구분하는 데 세상에 대한 지식은 필요 없다 — 철자법만 있으면 된다.
라틴 문자는 고유명사의 연속을 대문자로 표시하고, 한국어는 그 끝을 조사로 표시한다. 두 표시가
모두 없는 문자(한글·CJK 본문)에서는 이름이 계속되는 것으로 가정하므로 **추측하지 않고 거부**한다.
모든 판단은 "잘못된 조직"이 아니라 "놓친 조직" 방향으로 해소한다.

fuzzy matching · embedding similarity · LLM 기반 entity resolution은 만들지 않았다. alias는
실제 Evidence에 등장하거나 사용자가 mapping을 제공할 때만 인정한다.

`ABC Corporation`과 `ABC Holdings`를 잇지 않는다 — 세상에 대한 주장이지 문자열 연산이 아니다.
단일 토큰으로 줄어드는 이름은 전체 일치만 인정하고, 모델이 접미사를 준 이름이 본문에서 **다른**
접미사를 달고 있으면 거부한다.

검증을 통과하지 못한 이름은 `NAME_NOT_IN_EVIDENCE`로 기록되고 저장되지 않는다.

`DiscoveryHypothesis`는 **조직의 유형**만 표현한다. `name` 필드가 아예 없어서 특정 회사를
제안할 자리가 없고, Candidate로 승격하는 함수도 없다.

## Stage 6 — Fit Screening & Priority *(Phase 4 — 완료)*

| | |
|---|---|
| 입력 | `VerifiedOrganization` + framework별로 선별된 `ResearchFinding[]` |
| 출력 | `fit`(8개) · `priority` 채워진 `ClientCandidate[]` |

8개 기준 전부 `FitLevel` 순서형 enum이며, 각각 `reason` · `finding_ids` · `source_ids` ·
`missing_evidence`를 동반한다. **방향은 전부 동일**하다 — `STRONG`은 언제나 사업개발에
유리하다는 뜻이고, 경쟁이 강하면 `COMPETITIVE_SITUATION`은 `WEAK`다.

### 판단이 근거를 대체하기 쉬운 두 기준

| 기준 | 막는 것 | 요구 |
|---|---|---|
| Purchasing Potential | "대기업이라 돈이 많다" | `PurchaseSignal` closed list 중 하나 + 참조 + 직접 근거 |
| Accessibility | "공공기관이라 연락 가능하다" | `AccessRoute` closed list 중 하나 + 참조 + 직접 근거 |

signal이 있다는 것만으로 자동 `STRONG`이 되지 않는다. snippet-only면 최대 `MODERATE`로
내려가고 review flag가 남는다.

### 계약을 위반한 출력은 잘라내지 않는다

`reason`이 500자를 넘으면 **조용히 자르지 않는다.** 출력 스키마에 `maxLength: 500`이 명시되어
있으므로 초과는 provider의 계약 위반이다. 500자에서 자르면 아무도 쓰지 않은 문장이 저장되고,
잘린 절에 부정이 들어 있었다면 의미가 뒤집힌다. 그것도 조용히.

| | |
|---|---|
| 해당 assessment | 전체 폐기 (level까지) |
| 해당 criterion | `UNKNOWN`으로 degrade |
| 기록 | `REASON_TOO_LONG` rejection code + criterion 값 |
| `missing_evidence` | 비워 둔다 — provider 결함은 사람이 조사할 수 있는 gap이 아니다 |

`discovery_rationale`이 초과하면 degrade할 대상이 없다. rationale 없는 Candidate는 Candidate가
아니므로 `RATIONALE_TOO_LONG`으로 **통째로 거부**한다. retry engine은 만들지 않았다.

### Priority 규칙표

숫자 가중합을 쓰지 않는다. band는 `core/client/priority.py`가 계산하고 모델은 관여하지 않는다.

| band | 조건 |
|---|---|
| `DEFERRED` | 핵심 3개(문제·솔루션·역량) 중 `WEAK` 존재, 또는 경쟁상황 `WEAK` |
| `P1` | 핵심 3개 전부 긍정 + 미확정 없음 + 구매/접근 중 ≥1 긍정 **+ Problem Fit과 그 commercial signal 모두 직접 근거** |
| `P2` | 핵심 3개는 긍정이나 구매/접근이 미확정이거나 snippet 한정 |
| `P3` | 결격은 없으나 여러 항목이 미확정 |
| `UNKNOWN` | 핵심 3개 중 2개 이상이 미확정 |

**검색 snippet만으로는 P1이 될 수 없다.** Candidate로 저장되고 P2/P3/UNKNOWN까지는 가능하되,
최우선에 두려면 원문 확인이 필요하다. 이유는 `SNIPPET_ONLY_LIMITATION` 코드로 남는다.

band는 **영업 지시가 아니라 검토 순서**다 (`HARNESS.md` Human Decision First).

## Stage 7 — Client Deep Analysis *(Phase 5 — 완료)*

| | |
|---|---|
| 입력 | **사람이 고른** `client_ids` + `ClientCandidate` + `ResearchFinding[]` + `our_solution` + MN03–06 |
| 출력 | `ClientAnalysis` (claim 19개 + 해외일 때 8개) |

**MN 전체를 반복하지 않는다.** MN02 · MN07은 회사 차원 진단이므로 Client별로 반복하지 않는다.

### 사람이 고른다

```python
run_client_analysis(client_ids=[...], ...)   # keyword-only 필수, default 없음
```

자동 Top 3 없음 · priority 정렬 없음 · ranking 없음. 후보에 없는 id는 건너뛰지 않고 **거부**하고,
`max_clients_per_run`을 넘으면 앞 N개를 쓰는 대신 **요청 전체를 거부**한다 — 앞부분을 조용히 쓰는
것이 곧 자동 선정이고, 그것도 성공한 실행처럼 보인다.

숫자 3은 Core에 없다. "최대 3개 비교"는 Application Layer의 UX다.

### 19개 dimension, MN별 4회

| MN03 (8) | MN04 (5) | MN05 (2) | MN06 (4) |
|---|---|---|---|
| USER · BUYER · DECISION_MAKER · BUDGET_OWNER · PROBLEM · PROBLEM_SEVERITY · CURRENT_WORKAROUND · KBF | CURRENT_SOLUTION · COMPETITOR · SUBSTITUTE · VALUE_PROPOSITION · COMPETITIVE_ADVANTAGE | SALES_ACCESS_ROUTE · PARTNER | VALUE_DRIVER · PRICE_SENSITIVITY · BUDGET_EVIDENCE · PROCUREMENT_CONTEXT |

한 응답에 19개를 요구하면 뒷부분이 성의 없이 채워진다. framework별로 네 번 묻고, 교차 의존은
네 번이 모두 끝난 뒤 판정한다.

MN05는 `channel` · `customer_relationship` · `partner`만, MN06은 `price` · `revenue_model` ·
`pricing_structure`만 렌즈로 쓴다. `resource` · `activity` · `bm_alignment`와 `cost` · `margin` ·
`channel_cost`는 **우리** 쪽 진단이라 Client별로 다시 묻지 않는다.

### 두 개의 교차 dimension 규칙

**Competitive Advantage — 4조건.** 하나라도 빠지면 `EVIDENCE_NEEDED` + `NO_COMPARISON_BASIS`.

```
① KBF가 확정되어 있다
② CURRENT_SOLUTION / COMPETITOR / SUBSTITUTE 중 ≥1 확정
③ ①②에 쓰이지 않은 자기 자신의 finding ≥1
④ 그 finding이 MN04로 읽혔다
```

③이 핵심이다. KBF와 경쟁사 이름을 다시 인용하는 것은 둘이 존재한다는 증명일 뿐, 우리와의 차이에
대해서는 아무 말도 하지 않는다. 우리 제품에 특징이 있다는 것만으로는 우위가 아니라 사양서다.

**Value Proposition — 완화.** `PROBLEM` 확정 + `our_solution`이 있으면 INFERENCE 가설을 허용한다.
KBF가 있으면 ceiling MEDIUM, 없으면 LOW + missing evidence. `PROBLEM`이 없으면 만들지 않는다.

### our_solution은 묻지 않는다

출력 스키마에 필드가 없다. 모델에게 "우리 Solution이 무엇인가"를 묻는 것은 제품을 지어내라는
뜻이고, 실제로 지어낸다. 호출자가 넘긴 값을 그대로 기록한다.

### 해외

같은 pipeline · 같은 finding · 같은 provenance · 같은 transmission에 호출 한 번이 붙는다.
`market_scope != INTERNATIONAL`이면 `international_claims`는 비어 있다.

### Phase 5가 하지 않는 것

가격 숫자 · 견적 · WTP · 예산 추측 · margin · revenue model 결정 (Phase 7) ·
`key_message` · `proposal_storyline` · `expected_objection` · `response_logic` (Phase 6).

## Stage 8 — Proposal Strategy *(Phase 6 — 완료)*

| | |
|---|---|
| 입력 | `ClientAnalysis` 1건 + 호출자가 제공한 `solution_elements` + (선택) `objective` |
| 출력 | `ProposalStrategy` |

### Proposal Strategy ≠ Proposal Document

| | |
|---|---|
| **Proposal Strategy** | 무엇을 왜 어떻게 제안할지에 대한 **구조화된 의사결정 데이터** |
| **Proposal Document** | 그 전략으로 만드는 실제 문서 — Phase 9 |

Phase 6는 PPT·DOCX·PDF·제안서 본문·견적서를 만들지 않는다. `core/proposal/`에 렌더링
라이브러리 import가 없음을 테스트가 확인한다.

### 목표에는 기본값이 없다

```
objective = None, objective_source = None      ← 아무도 고르지 않았을 때
사람이 지정  → HUMAN,        status = STRATEGY_DRAFTED
AI가 제안    → AI_SUGGESTED, 근거가 받쳐줄 때만
```

**근거를 앞지르는 목표에 대해 자동 fallback을 두지 않는다.** AI 제안이 요건을 못 채우면
목표는 `None`이 되고 **아무것도 대신 들어가지 않는다** — 조용한 대체는 파이프라인이 제안의
목적을 정하는 것이다. 사람이 고른 목표는 요건을 못 채워도 **덮어쓰지 않고** flag만 남긴다.
사람은 Harness가 모르는 것을 알 수 있고, 기계는 자기가 인용한 근거 이상을 알 수 없다.

| 목표 | 요구 근거 |
|---|---|
| `DISCOVERY_MEETING` · `TECHNICAL_REVIEW` · `PARTNERSHIP_DISCUSSION` | 없음 |
| `POC` | `PROBLEM` |
| `PILOT` | `PROBLEM` + (`BUYER` 또는 `DECISION_MAKER`) |
| `SUPPLIER_REGISTRATION` | `PROCUREMENT_CONTEXT` |
| `FORMAL_PROPOSAL` | `PROBLEM` + (`BUYER` 또는 `DECISION_MAKER`) |
| `PROCUREMENT_RESPONSE` | `PROCUREMENT_CONTEXT` + (`BUYER` 또는 `DECISION_MAKER`) |

초기 목표에 요건이 없는 것은 의도다. **탐색 미팅은 구매자를 찾는 방법**이고, 그 전에 구매자
근거를 요구하면 대부분의 후보가 실제로 서 있는 단계에서 Harness가 쓸모없어진다.

### 제안할 Solution은 고르는 것이지 쓰는 것이 아니다

```
호출자 → solution_elements [S1, S2, ...]
모델   → element ref 선택만
pipeline → 호출자의 원문으로 조립
```

출력 스키마에 **제품을 서술할 자유 텍스트 필드가 없다.** 없는 인증·지원체계·현지망·통합
기능이 들어갈 자리가 없다. 모르는 ref는 거부한다.

### Phase 5 게이트를 다시 판정하지 않는다

| Phase 5 | Phase 6 |
|---|---|
| `VALUE_PROPOSITION` 확정 | proposal-specific 재서술 허용 |
| 미확정 | `value_proposition = None` + `EvidenceNeed(BEFORE_PROPOSAL)` |
| `COMPETITIVE_ADVANTAGE` 확정 | `DIFFERENTIATION` step 허용 |
| 미확정 | step 생성 금지 + `COMPETITIVE_POSITION_UNKNOWN` |

규칙을 복제하지 않고 claim의 확정 여부만 읽으므로 두 Phase가 어긋날 수 없다.

### 제안 문장은 무엇을 제안하는지 ref로 가리킨다

```
호출자 whitelist   SolutionElement(ref="S1", text="...")
       ↓ 모델은 ref만 고른다        ["S1", "S3"]
       ↓ deterministic resolution
레코드             SelectedSolutionElement(ref="S1", text=<호출자 원문>)
       ↑
문장               solution_element_refs = ["S1"]
```

`ref`는 안정적 참조 id, `text`는 표시 내용이다. **산문을 식별자로 쓰지 않는다** — 같은 문구의
두 element가 합쳐지고, 문구를 다듬으면 가리키던 문장이 끊어진다.

`value_proposition`·`key_message`는 각각 ref 최소 1개를 요구하고, 그 ref는 선택된 것이어야
한다. `proposed_solution`은 선택된 `text`만 이어 붙인다.

문장의 정확성을 보장하지는 않는다 — 제안된 것의 **출처**를 보장할 뿐이다. 의미적 정확성은
best-effort이며 semantic relevance validation backlog 대상이다.

### 분류되지 않은 gap

Phase 5 gap은 전부 전달된다. 시점을 판정할 수 없으면 `UNCLASSIFIED`이고, **가장 이른 시점으로
승격하지 않는다.** 승격은 분석이 주장한 적 없는 긴급성을 만들고, 기록된 뒤에는 판단과 기본값을
구분할 수 없게 만든다.

### 근거 없는 숫자

`key_message`·`value_proposition`의 숫자가 인용된 claim에 없으면 **그 문장을 확정하지 않는다**
(`UNSOURCED_FIGURE`). storyline·response에서는 flag만 남긴다 — 고객에게 하는 약속과 내부 논리는
틀렸을 때 비용이 다르다.

검사는 숫자 토큰에 대한 문자 대조이며 NER이 아니다. 모델명이나 연도에서 오탐이 날 수 있고,
그 대가는 문장 하나이지 고객이 아니다.

### 반론과 대응은 한 객체다

`EVIDENCE_BACKED`는 확정된 claim 인용이 필수이고, 인용이 없으면 `ANTICIPATED`로 **강등**된다 —
우려 자체는 진짜일 수 있고, 잃는 것은 "고객이 그렇게 말했다"는 주장이다. 근거도 gap도 없는
대응은 거부한다.

빈 반론 목록은 flag만 남긴다. 최소 개수를 강제하면 지어내게 되고, 그것이 침묵보다 나쁘다.

### 한계

인용된 dimension이 존재한다는 것과 고객이 **그 반론을** 실제로 제기했다는 것은 같지 않다.
의미적 적합성 검증은 `docs/development-guide.md`의 backlog 항목이며, 이를 가리기 위한 verifier·
embedding·NER을 Phase 6에서 도입하지 않았다.

## Stage 9 — Pricing Hand-off *(Phase 7)*

| | |
|---|---|
| 입력 | `ClientAnalysis` + `ProposalStrategy` + `CommercialInput` (호출자 숫자) |
| 출력 | `PricingResult` |

이 Harness는 **계산하지 않는다.** 결정적 변환만 한다 — LLM 없음, 산술 없음.

```
core/pricing_bridge.run_pricing_handoff(
    analysis=..., strategy=..., commercial=...,
    acknowledged_gap_refs=(), pricing_case_id=None, policy=DEFAULT_PRICING_POLICY)
```

signature에 `llm`도 `prompts`도 `project`도 없다. 보낼 것이 없으니 보낼 도구도 없다.

| 블록 | 내용 | 전송 |
|---|---|---|
| `pricing_payload` | `client_input.schema.json` 형태: `schema_version` `client_id` `case_id` `product` `tax` `fx` `costs` (+ `targets` `meta`) | **간다** |
| `commercial_context` | 이 case를 설명하는 확정 context (`docs/data-model.md` 9절) | **안 간다** |

### 숫자의 출처는 `CommercialInput` 하나다

`CommercialInput`은 transient DTO다 — 저장하지 않고 스키마도 없다. 실제로 쓰인 숫자는
`pricing_payload`에 이미 보존되므로, 두 번째 사본은 두 번째 SSOT일 뿐이다.

```
CommercialInput.vat_rate                      → tax.vat_rate
CommercialInput.rate_base_per_reporting       → fx.rate_base_per_reporting
PriceComponentInput.actual_price              → product.price_components[*].actual_price
CostItemInput.amount / rate                   → costs.items[*].amount / rate
```

한 필드 → 한 필드. `None`은 `null`이 되고 **`0`이 되지 않는다.**

### Solution 결속

```
Phase 6 selected_solution_elements[*].ref
        ↑ PriceComponentInput.solution_element_ref (필수, 이 목록 안에서만)
        ↓
payload  product.price_components[*].component_id      ← ref는 넣지 않는다 (닫힌 객체)
context  offered[*] = {ref, text, component_id}        ← 결속의 canonical 위치
```

선택되지 않은 ref → **전체 거부** (`UNKNOWN_SOLUTION_ELEMENT`). component 하나를 조용히
빼면 제안보다 적게 견적하고, 그것이 원래 의도였던 것처럼 보인다.
선택되었는데 가격이 없으면 `ELEMENT_NOT_PRICED` **flag**다 — 부분 견적은 정당한 판단이다.

### Gate

`BEFORE_PRICING` gap이 열려 있으면 `HANDOFF_BLOCKED`. payload는 만들어서 보여준다 — 막히는
것은 전달이다. 사람이 **gap을 하나씩 지목해** 확인하면 통과하고 `GAPS_ACKNOWLEDGED`가 남는다.
`UNCLASSIFIED` · `OPTIONAL`은 막지 않는다.

#### 지목은 `gap_ref`로 한다 — 문장으로 하지 않는다

```python
@dataclass(frozen=True)
class PricingGap:          # transient. Entity도 아니고 schema도 없다
    gap_ref: str           # machine reference — 불투명, 결정적
    need: str              # display text — 사람이 읽는 문장
    timing: EvidenceTiming
    dimension: Optional[AnalysisDimension]
```

`gap_ref = "gap_" + sha256(strategy_id ␟ need ␟ timing ␟ dimension)[:16]`

- **불투명하다** — need 원문이 ref에 실리지 않는다
- **결정적이다** — 같은 gap 상태면 프로세스·머신과 무관하게 같은 ref
- **gap이 바뀌면 ref가 바뀐다** — 승인은 *그 시점에 그렇게 쓰여 있던 그 gap*에 대한 것이고,
  문구·시점·dimension이 달라지면 자동으로 유효하지 않다
- **strategy를 넘어 전이되지 않는다** — 두 고객이 똑같이 읽히는 gap을 가질 수 있고, 한쪽의
  승인이 다른 쪽의 승인은 아니다
- 정규화는 **공백뿐이다.** 대소문자·문장부호·어휘는 건드리지 않는다 — 그것을 접으면 "다르게
  쓰인 두 문장이 같은 뜻"이라는 의미 판단이 되고, 이 저장소는 그 판단을 하지 않는다

이것은 `HARNESS.md` 7절의 *산문을 식별자로 쓰지 않는다*가 Phase 7에 적용된 것이다. 문장을
키로 쓰면 같은 문구의 두 gap이 합쳐지고, 문구를 다듬는 순간 그것을 가리키던 승인이 끊어진다.

| 보낸 ref | 처리 |
|---|---|
| 이 strategy의 blocking gap | 해제 대상 |
| 이 strategy의 non-blocking gap | `NON_BLOCKING_GAP_ACKNOWLEDGED` **flag**. 아무것도 해제하지 않는다 |
| 이 strategy에 없는 ref (stale · 오타 · 타 strategy) | `UNKNOWN_GAP_REF` **rejection — run 전체 거부** |

마지막 줄이 중요하다. 조용히 무시하면 caller가 준 승인과 기록된 승인이 달라진다. stale ref는
"gap을 닫아라"가 아니라 **"당신이 보고 있는 화면이 낡았다"**이므로, 거부하고 다시 읽게 한다.

`commercial_context.evidence_needs[*]`가 `gap_ref` · `need` · `timing` · `dimension`을 함께
싣는다 — Phase 8 UI는 `need`를 표시하고 `gap_ref`를 round-trip한다.

`adapters/pricing/file.py`의 `write_payload()`가 `HANDOFF_BLOCKED`를 거부한다 — 파일을 쓰는
것이 곧 전달이므로, gate가 거기서 물지 않으면 권고에 불과하다.

### 그쪽 규칙은 그쪽이 판정한다

`shared` + `direct`, `amount`와 `rate` 동시 입력, component type과 어긋난 `pricing_model` —
`dependency_rules.md`가 오류로 규정하는 조합들이다. 우리는 `DEPENDENCY_RULE_RISK` flag를
남기고 **값을 그대로 통과시킨다.** 자동 수정도, 값 제거도, allocation 변경도 하지 않는다.

### 돌아오는 것

`analysis_result` (MODE A 현재가격 진단 / MODE B 목표가격 / MODE C 허용원가 / BEP).
`attach_engine_result()`가 `source.case_id` · `source.client_id`를 대조하고, 일치하면
**원문 그대로** `engine_result`에 넣는다. 불일치는 `ENGINE_RESULT_MISMATCH` + `FAILED`이고
문서는 보관하지 않는다 — 파일 계약에서는 엉뚱한 파일이 돌아올 수 있고, 모양이 맞는 틀린
답이 가장 위험하다. 모듈 status(`OK` `INCOMPLETE` `UNKNOWN` `ERROR`)는 그쪽 어휘이며
재해석하지 않는다.

Scenario Compare는 Phase 7 범위 밖이다. 한 번에 계약 하나.

연결 방식과 `core` 패키지명 충돌 주의사항은 `ARCHITECTURE.md` 6절에 있다.

## Stage 10 — Report Output *(Phase 9)*

| | |
|---|---|
| 입력 | 구조화된 Entity |
| 출력 | HTML · DOCX 초안 |

**HTML/DOCX/PDF는 Output이다. 원본 Data가 아니다.** Report는 항상 Entity를 읽어서 생성하며,
그 반대 방향은 없다.

---

## Web Application Integration *(Phase 8)*

```
Web Application Integration  +  Mobile-first Reference UI  +  Training UX Validation
```

배포 대상의 실제 구조를 확인한 뒤 설계를 확정했다. 확인 결과와 그에 따른 결정은 아래와 같다.

### 확인된 배포 대상

`magisglobal.co.kr`은 **Astro 정적 사이트**다 (`rando-knowledge-web`).

| | 확인된 사실 |
|---|---|
| output | 정적 빌드. `adapter`도 `output: 'server'`도 없다 |
| UI framework | 없다. 의존성은 `astro` 하나 |
| client-side JS | 없다. `client:*` 지시자도 `<script>`도 0건 |
| API route · auth · DB | 없다 |
| 기존 Harness 3종 | 설명 페이지이며 GitHub으로 link out |

**결론: 사이트에는 런타임이 없다.** Phase 8은 사이트에 얹는 것이 아니라 별도 런타임을 만들고
사이트가 그것을 가리키게 한다.

### Decision 1 — 사이트와 App을 분리한다

```
magisglobal.co.kr           Astro 정적 마케팅 사이트. 설명 페이지 + CTA/link만
Client Discovery App        별도 런타임. 실행·세션·저장은 전부 여기
```

사이트에 Python 런타임·세션·인증 표면을 만들지 않는다. 기존 Harness 3종이 이미 쓰는 패턴
(설명 → link out)을 그대로 따른다.

### Decision 2 — 단일 Python 런타임

Application Service + JSON endpoint + 서버 렌더 mobile HTML을 **하나의 Python 런타임**이
제공한다. 런타임을 둘로 나누면 언어 2개·배포 2개·계약 1개가 늘고, MVP가 필요로 하는 UI는
"한 화면 한 판단 + 폼 제출"이라 SPA가 필요할 상태가 없다.

**Web framework는 확정하지 않는다.** runtime spike 결과(아래)로 고른다.

### Decision 3 — locale 경계

| | 소유 | 내용 |
|---|---|---|
| Harness locale | 이 저장소 | `enums` · `fields` — **canonical domain code label** |
| | | `screens` · `actions` · `messages` — legacy. 유지하되 **신규 추가 금지** |
| App locale | App 저장소 | nav · button · screen copy · help · error · training instruction |

Phase 8에서 새로 생기는 UI 문구는 Harness locale에 **추가하지 않는다.** 기존 세 섹션의 정리는
별도 refactor로 처리한다 — 이번 Phase에서 Core를 바꾸지 않기 위해서다.

### Decision 4 — 첫 실행 작업은 Runtime Spike

프레임워크나 호스트를 고르기 전에 **측정한다.** 결과는 아래 "Runtime spike 결과"에 있다.

### Bootstrap Analysis Run

**화면의 step과 Core pipeline 호출을 1:1로 대응시키지 않는다.**

`EvidenceCandidate`는 문서 원문을 담는 transient DTO이고 `StorageProvider`에 저장 메서드가
없다 (`docs/privacy.md` 3절). `run_research`와 `run_discovery`는 **둘 다** 그것을 읽는다.
따라서 둘은 candidate가 살아 있는 **하나의 Application operation** 안에서 끝나야 한다.

```
회사·시장·역량·솔루션 입력  +  문서 업로드
        ↓
ephemeral EvidenceCandidate 생성          ← 메모리에만 존재
        ↓
run_research()      → Finding · SWOT · KeyIssue        저장
        ↓
run_discovery()     → ClientCandidate · Fit · Priority 저장
        ↓
EvidenceCandidate 즉시 폐기
```

이것을 **Bootstrap Analysis Run**이라 부른다. UI는 그 뒤에 Diagnosis → Key Issue →
Client Candidate → Fit → Priority를 단계적으로 공개한다.

> **계산 순서와 공개 순서는 같을 필요가 없다.** 이 구분이 Phase 8 UX의 전제다.

### Bootstrap은 all-or-nothing이 아니다

Research는 성공하고 Discovery만 실패할 수 있다. 그 경우 Finding · SWOT · KeyIssue는 **이미
저장되어 있으므로** Diagnosis / Key Issue review는 재개된다. 하지만 `EvidenceCandidate`는
저장되지 않으므로 **Discovery 재실행에는 문서 재업로드가 필요하다.**

Application이 관리하는 상태 — **Core enum으로 추가하지 않는다:**

| 상태 | 저장된 것 | 재개 가능 | 재업로드 필요 |
|---|---|---|---|
| `NOT_STARTED` | 없음 | — | — |
| `RUNNING_RESEARCH` | 없음 | — | 프로세스 종료 시 ○ |
| `RESEARCH_COMPLETED` | Finding · SWOT · KeyIssue | STEP 3–4 | Discovery 위해 ○ |
| `RUNNING_DISCOVERY` | Finding · SWOT · KeyIssue | STEP 3–4 | 프로세스 종료 시 ○ |
| `COMPLETED` | 위 + ClientCandidate · Fit · Priority | STEP 3–7 | ✗ |
| `RESEARCH_FAILED` | 없음 | — | **○** |
| `DISCOVERY_FAILED_REUPLOAD_REQUIRED` | Finding · SWOT · KeyIssue | STEP 3–4 | **○** |

마지막 상태의 이름이 긴 것은 의도다. 화면이 "실패"라고만 쓰면 사용자는 재시도 버튼을 찾고,
그 버튼은 존재할 수 없다.

UX 문구는 상태마다 다르다.

| 상태 | 사용자에게 |
|---|---|
| `COMPLETED` | *"업로드한 문서는 삭제되었습니다. 분석 결과는 남아 있습니다."* |
| `DISCOVERY_FAILED_REUPLOAD_REQUIRED` | *"진단 결과는 남아 있습니다. 고객 발굴을 다시 하려면 자료를 다시 올려야 합니다 — 원본 문서는 보관하지 않습니다."* |
| `RESEARCH_FAILED` | *"분석을 완료하지 못했습니다. 자료를 다시 올려주세요."* |
| 프로세스 종료로 중단 | *"분석이 중단되었습니다. 자동으로 다시 시작되지 않습니다."* (`HARNESS.md` 10절) |

**재개할 수 없는 것은 언제나 같다:** 원본 문서와 `EvidenceCandidate`.

### Runtime spike 결과

`scripts/spikes/phase8_runtime_spike.py`, 볼륨당 5회. Provider는 `EchoLLM`(오프라인)이므로
**실제 provider latency는 NOT_MEASURED**다 — 이 환경에 credential이 없고 만들지 않는다.

| 볼륨 | 업로드 | candidate | 측정된 호출 | Harness 자체 연산 (median) | peak Python |
|---|---|---|---|---|---|
| small | 872 B | 8 | 7 | 1.3 ms | 27 KB |
| medium | 3,623 B | 29 | 19 | 2.7 ms | 41 KB |
| large | 13,055 B | 101 | 55 | 8.4 ms | 109 KB |

- **외부 search 호출 0건** — `run_research`·`run_discovery`는 `SearchProvider`를 받지 않는다.
  검색은 Phase 5 `run_client_analysis(search=...)`에서만 시작되고 client당 6 query × 5 result로
  상한이 걸려 있다.
- **Harness 자체 연산은 무시할 수준이다.** 시간은 전부 provider 왕복이다.
- 측정된 호출 수는 **하한**이다. `EchoLLM`이 "확인되지 않음"을 반환하므로 inference·SWOT
  분류·key issue 종합·조직 추출·fit 평가 경로를 걷지 않는다.

코드 구조와 policy 상수에서 유도한 **populated upper bound** (측정 아님):

| 볼륨 | batch | 측정 | 모델 상한 |
|---|---|---|---|
| small | 1 | 7 | 36 |
| medium | 3 | 19 | 62 |
| large | 9 | 55 | **140** |

```
research  extract      B x F         discovery  criteria       1
research  infer        B x F         discovery  organizations  B
research  classify     ceil(K/40)    discovery  fit            min(M, 20)
research  key issues   ceil(S/40)
B=batch(12 candidate) F=framework(6) K=finding S=SWOT M=organization
```

### 결론: Bootstrap Run은 한 HTTP 요청에 들어가지 않는다

large의 모델 상한 140 호출에 대해:

| 호출당 지연 | Bootstrap 총 대기 |
|---|---|
| 2 s | 4.7 분 |
| 4 s | 9.3 분 |
| 8 s | **18.7 분** |

따라서 Phase 8 MVP는:

1. **Bootstrap Run을 in-process background run으로 실행하고 상태를 폴링**한다. 허용 범위와
   제외 범위는 `HARNESS.md` 10절 "in-process background run은 Job Queue가 아니다"에 표로
   고정되어 있다 — broker · worker fleet · durable queue · 자동 재시도 · 분산 스케줄링 없음.
   따라서 **persistent process가 필요하고**(serverless로는 불가능하다), **프로세스가 종료되면
   진행 중이던 Bootstrap은 소실된다.** 재시도도 재개도 없다.
2. **framework 범위는 교육 설계가 정한다 — 런타임이 정하지 않는다.** 아래 참조.

### framework subset은 Training Mode의 선택이다

`run_research(frameworks=[...])`는 "operator가 의도적으로 분석을 좁히는 것이며, 파이프라인이
조용히 좁히는 것과 다르다"는 이유로 존재한다 (`core/research/pipeline.py`). Phase 8도 그
구분을 지킨다.

| | framework 범위 |
|---|---|
| **Training Mode** | 교육목표에 따라 **명시적으로** subset을 고를 수 있다. 화면이 어떤 MN을 돌렸는지 보여준다 |
| **Work Mode** | 호출 수·비용·호스팅 최적화를 이유로 **silent downgrade하지 않는다.** 좁히려면 사람이 고른다 |

런타임 제약을 근거로 분석 범위를 줄이는 것은 Application이 분석의 깊이를 결정하는 것이다.
느리면 느리다고 말하고 기다리게 하거나, 사람이 범위를 줄이게 한다.

### 호스팅 제약

수치는 **공식 문서를 2026-09-20에 확인**한 것이다. 플랫폼 제약은 바뀌므로, 호스트를 최종
결정할 때 다시 확인한다.

| 호스트 | 요청 상한 | 영속 디스크 | 요청 본문 상한 | 확인일 |
|---|---|---|---|---|
| Vercel Functions | Hobby 300s / Pro 800s (1800s beta) | 없음 (Lambda 기반) | **4.5 MB** | 2026-09-20 |
| Google Cloud Run | 기본 300s, 최대 3600s | 컨테이너 임시 | 미확인 | 2026-09-20 |
| Fly.io Machines | 플랫폼 상한 문서에 명시 없음 | **Fly Volumes** (최대 500 GB) | 미확인 | 2026-09-20 |
| Render Web Service | 문서에 명시 없음 | **Persistent Disk** (인스턴스 1개 제약) | 미확인 | 2026-09-20 |

#### Vercel을 App 호스트로 보지 않는 이유

실행시간 하나로 배제하는 것이 아니다. 세 가지가 함께 작용한다.

1. **요청 본문 상한과 intake 계약의 충돌.** Vercel Functions의 본문 상한 4.5 MB는
   `IntakePolicy.max_file_bytes = 25 MiB`보다 작다. Harness가 허용하는 문서 **한 개**조차
   직접 업로드로는 받을 수 없다. 우회(서명 URL로 객체 스토리지에 직접 업로드)는 가능하지만
   그 순간 "메모리에서만 파싱하고 디스크에 남기지 않는다"는 intake 보장을 다시 설계해야 한다.
2. **persistence 모델 불일치.** MVP는 SQLite + persistent process를 전제로 한다. Vercel
   Functions에는 요청 간 유지되는 파일시스템이 없고, 외부 관리형 DB를 도입하면 G절의
   "DB 제품을 먼저 고르지 않는다"를 뒤집게 된다.
3. **long-running Bootstrap 수명주기의 운영 복잡성.** in-process background run은 프로세스가
   요청보다 오래 살아 있어야 한다. 요청 단위로 동결·해제되는 실행 모델에서는 상태 폴링과
   중단 감지를 플랫폼 밖에서 다시 만들어야 한다.

정적 사이트가 Vercel에 있다는 것과 App이 Vercel이어야 한다는 것은 별개다 — 둘은 독립적으로
배포된다.

### 데스크톱 4화면

| 화면 | 표시 |
|---|---|
| Project | Company · Target Market · Market Scope · Target Countries · Research Status · SWOT Status · Client Candidate Count · Proposal Status |
| SWOT / Issues | S/W/O/T · Key Issues · Strategic Implications · Evidence · Sources |
| Client Pipeline | Client · Country · Industry · Problem Fit · Solution Fit · Buyer · Priority · Status |
| Proposal Strategy | Client · Problem · Buyer · Solution · Value Proposition · Competitive Advantage · Pricing · Proposal Status |

화면은 4개로 제한한다. 라벨은 `locales/*.json`의 `screens` 섹션에 이미 준비되어 있다.

### Mobile-first 원칙

교육생이 **개인 스마트폰으로 직접** 접속해 실습한다는 것이 이 UI의 전제다. 세로 화면이 기본이다.

한 화면에 대형 표를 넣는 대신 **card · step · progressive disclosure · simple comparison ·
expandable evidence**를 우선 검토한다.

모바일 화면 후보 9개:

```
1 Project / Training Session   4 Client Candidates   7 Priority
2 Evidence / Research          5 Client Detail       8 Missing Evidence
3 Key Issues                   6 Fit Assessment      9 Result Summary
```

**Fit Assessment 8개는 카드로 본다.** 8열 표는 스마트폰에서 읽을 수 없고, 읽을 수 없는 표는
근거를 감춘다. 카드마다 다음을 **구분해서** 보여준다.

```
Fit Criterion · Fit Level · Reason · Evidence · Missing Evidence
```

### Evidence와 AI Interpretation은 시각적으로 갈라야 한다

이것이 이 UI의 가장 중요한 요구사항이다.

| | |
|---|---|
| **Evidence** | 자료에서 실제로 확인된 내용 |
| **AI Interpretation** | 그 Evidence를 근거로 한 분석·해석 |

스마트폰 화면에서도 `Evidence` · `Finding` · `Inference` · `Missing Evidence`가 서로
구분되어야 한다. 둘이 같은 서체·같은 색으로 섞여 나오는 순간, 교육생은 추론을 사실로 읽는다 —
이 Harness가 `EvidenceType`을 enum으로 들고 다니는 이유가 화면에서 무효가 된다.

구체적인 디자인은 Phase 8에서 정한다. 요구사항만 여기 고정한다.

### Training UX는 Application Layer의 책임이다

Mobile-first · touch-friendly · short-step · evidence-visible은 **UI 요구사항이다.** Core
business logic에 넣지 않는다. Core는 화면 크기도, 교육 세션도, 접속한 사람이 강사인지
교육생인지도 모른다 (`HARNESS.md` 12절).

### Work Mode와 Training Mode

한 Core, 한 API, 두 view.

| | Work Mode | Training Mode |
|---|---|---|
| 목적 | 결과 | 과정 |
| REVIEW 단계 | 접힌 요약으로 통과 | 펼쳐서 설명 |
| provenance | 한 탭 뒤, 기본 접힘 | 기본 노출 |
| 멈추는 곳 | Human decision 6개 | 6개 + 학습 단계 |

**Human decision 6개** — 어느 mode에서도 UI가 대신 결정하지 않는다:
Client 선택 · Proposal Objective · Solution selection · Pricing gap acknowledgement ·
원가·가격 입력 · 제안 실행 여부. API에 이들의 default 경로를 만들지 않는다.

### computed ≠ revealed

predict-then-reveal에서 **AI 결과를 미리 계산하는 것은 허용한다.** Bootstrap Run이 한 번에
끝나므로 오히려 그래야 한다. 금지되는 것은 learner가 자기 판단을 제출하기 전에 **공개**하는
것이다.

```
computed   Bootstrap Run이 끝난 시점
revealed   learner가 prediction을 제출한 시점
```

reveal state는 **Application Layer가 관리한다.** Core에 training·reveal 개념을 넣지 않는다.

### Persistence ownership

| | 소유 | 저장 대상 |
|---|---|---|
| Harness `StorageProvider` | 이 저장소 | Core 9 entity **만** |
| Application persistence | App 저장소 | `training_session` · `participant` · `prediction` · reveal state · session expiry · application metadata |

`TrainingSession`을 Core Entity로 만들지 않고 `StorageProvider`에 메서드를 추가하지 않는다.
같은 SQLite 파일을 쓰더라도 **table ownership과 repository module은 분리한다.**

세 가지 persistence mode:

| | Ephemeral Demo | Training Session | Authenticated Work |
|---|---|---|---|
| storage adapter | `null` / `memory` | `sqlite` | 조직이 연결 |
| 원본 문서 | 저장 안 함 | **저장 안 함** | 조직 정책 |
| `EvidenceCandidate` | 요청 후 소멸 | **소멸** | 소멸 |
| 저장 대상 | 없음 | structured entity만 | 동일 + 조직 확장 |
| 수명 | 요청 | 세션 종료 + N시간 | 조직이 정함 |

**세 모드 모두 raw document를 저장하지 않는다.**

### Provider adapter는 config가 고른다

Phase 8은 production provider를 붙여야 하지만, **특정 vendor를 architecture에 고정하지
않는다.** Core는 `LLMProvider`·`SearchProvider` Protocol만 안다. 첫 production provider가
무엇이든 `adapters/llm/<provider>.py`로 추가되고, **선택은 Application wiring이 config/env로
한다.**

### Phase 9와의 경계

Phase 8은 **interactive structured UI까지**다. PDF · DOCX · PPTX · formal proposal ·
report renderer는 Phase 9다. Phase 8에서 report generation을 끌어오지 않는다.

---

## 영업조직 교육 실습 *(Phase 8 이후, 미구현)*

이 Harness는 영업조직 교육의 실습 도구로 사용할 예정이다. 아래는 **미래 UX 요구사항**이며,
지금 Core에 권한 모델이나 세션 개념을 추가하는 근거가 아니다.

### 예상 흐름

```
Instructor                              Learner
  교육 세션 생성
  실습 자료 선택
  QR / URL 공유          ────────────▶   스마트폰 접속
                                        실습 Project 선택 또는 생성
                                        회사 / 시장 / 제공 자료 확인
                                        Research Finding 확인
                                        Key Issue 확인
                                        Client Candidate 확인
                                        Fit Assessment × 8 확인
                                        Priority 비교
                                        Missing Evidence 확인
  팀별 결과 확인         ◀────────────   자신의 판단 정리
  결과 비교 · 토론 진행
```

### Harness는 정답을 알려주는 도구가 아니다

교육 목적은 교육생이 **설명하게** 만드는 것이다.

- 왜 이 Client가 후보인가?
- 어떤 Evidence가 있는가? 어떤 Evidence가 부족한가?
- Problem Fit은 왜 높은가?
- Purchasing Potential은 실제로 확인됐는가?
- 왜 P1인가, 왜 P3인가?

교육생이 화면의 band를 읽고 그대로 옮겨 적는다면 그 수업은 실패한 것이다. Training Mode도
Human Decision First를 유지한다 — band는 검토 순서이지 영업 지시가 아니고, 그 사실을 교육이
가장 먼저 무너뜨리기 쉽다.

### 훈련할 사고방식 10가지

| | |
|---|---|
| 1 | 유명한 기업과 좋은 고객을 구분한다 |
| 2 | 추측과 Evidence를 구분한다 |
| 3 | User · Buyer · Decision Maker를 구분한다 |
| 4 | 고객 Problem과 우리 Solution의 정합성을 검토한다 |
| 5 | Purchasing Potential을 회사 규모로 추측하지 않는다 |
| 6 | Accessibility를 실제 접근 경로로 판단한다 |
| 7 | 경쟁상황을 Evidence로 확인한다 |
| 8 | Missing Evidence를 영업 준비과제로 인식한다 |
| 9 | Priority를 느낌이나 숫자 점수만으로 결정하지 않는다 |
| 10 | AI의 결과를 최종 판단이 아니라 의사결정 지원자료로 사용한다 |

5·6·7은 Harness가 이미 코드로 강제하는 것과 같다 (`PurchaseSignal` closed list ·
`AccessRoute` closed list · 경쟁상황의 Evidence 요구). 교육은 그 제약이 왜 있는지를 설명하는
자리다.

### 교육용 Sample Data

**항상 완전히 가상의 기업과 시장 사례를 쓴다.** 실제 고객사 · 기업 내부자료 · 개인정보 ·
실제 영업대상 정보를 Public Repository의 교육 예제에 넣지 않는다 (`HARNESS.md` 9절).

교육 중 실제 회사자료를 다루는 경우는 사용 조직이 자체 환경의 privacy 정책에 따라 처리한다.
이 저장소는 그 경로를 제공하지 않는다.

---

## 배포 대상과의 관계

| | |
|---|---|
| `rando-client-discovery-harness` | 재사용 가능한 **Public Core** |
| Web 배포 대상 (예: `magisglobal.co.kr`) | Core를 **사용하는** Web Application / Host |

배포 대상은 Core의 dependency가 **아니다.** Public Core는 어떤 사이트 없이도 완전히 독립적으로
실행된다 — `python examples/run_example.py`가 지금 그렇게 동작한다.

따라서 Public Core 코드에 넣지 않는 것:

```
특정 사이트의 URL 하드코딩 · site-specific route · site-specific auth
site-specific database · site-specific UI logic · site-specific business rule
```

사이트 연결은 Application / API / Adapter Layer에서 처리한다. 이 구분이 무너지면 Core는 한
사이트의 백엔드가 되고, 다른 조직이 재사용할 수 없게 된다.

---

## 단계 사이의 공통 규칙

1. **순서를 건너뛰지 않는다.** Evidence → Finding → SWOT → Client → Analysis → Strategy →
   Pricing.
2. **각 단계는 앞 단계의 id를 참조한다.** 참조가 끊기면 불변식 검사에서 거부된다.
3. **근거가 없으면 `UNKNOWN` / `EVIDENCE_NEEDED` / `MISSING_EVIDENCE`로 남긴다.** 빈칸을
   그럴듯한 값으로 채우지 않는다.
4. **최종 판단은 사람이 한다.** 이 Harness는 판단 재료를 추적 가능한 형태로 만들어 준다.

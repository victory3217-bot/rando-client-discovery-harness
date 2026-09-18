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

## Web Application Integration *(Phase 8)*

Phase 8은 원래 "Reference Dashboard 4화면"이었다. 범위를 다음으로 넓혀서 검토한다.

```
Web Application Integration  +  Mobile-first Reference UI  +  Training UX Validation
```

**지금 구현하지 않는다.** Phase 8에 도달했을 때 그 시점의 배포 대상 기술구조를 실제로 확인한
뒤 API 방식 · frontend · deployment · session · mobile UX를 정한다. 지금 특정 기술을
선결정하지 않는다 — 2026년에 고른 framework로 Phase 8을 시작하게 되는 것이 이 결정을 미루는
이유다.

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

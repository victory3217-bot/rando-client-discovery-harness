# HARNESS.md — Client Discovery Harness 공통 규칙 (SSOT)

> **이 파일이 이 저장소의 Single Source of Truth다.**
> `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`는 이 파일을 가리키는 얇은 진입점일 뿐이며, 이 파일의
> 내용을 복제하지 않는다. 규칙이 바뀌면 **이 파일만** 고친다.
>
> Canonical language is Korean. Key terms are given in English so that any AI coding agent
> (Claude Code, Codex, Gemini CLI, Antigravity, …) can follow the same rules.

---

## 0. Required Reading

세션 시작 시 아래 순서로 읽는다. 작업 유형에 따라 4번 이후는 선택이다.

1. **`HARNESS.md`** (이 파일) — 목적 · 원칙 · 워크플로 · Evidence 규칙 · 금지사항
2. **`ARCHITECTURE.md`** — 디렉토리 구조 · Core/App 경계 · Interface 목록 · 어디를 고칠지 안내
3. **`docs/data-model.md`** — Entity 8개와 필드 정의 (코드를 만지기 전에 반드시)
4. `docs/privacy.md` — 업로드·로깅·전송 규칙 (Intake / Reference App을 만질 때 **필수**)
5. `docs/product-spec.md` — 각 단계의 입력·출력 정의 (Engine을 만질 때)
6. `docs/development-guide.md` — 개발 순서 · 테스트 · 새 Adapter 추가 방법

---

## 1. 목적

기업의 사업자료 · 컨설팅 결과 · 시장자료를 분석하여, 국내·외에서 **실제 영업할 잠재 Client를
발굴**하고, 우선순위 Client에 대한 **제안전략**까지 도출하는 재사용 가능한 Modular AI Harness.

한 문장으로:

> **우리가 무엇을 가지고, 어느 시장의 누구에게, 무엇을 제안할 것인가를 찾아주는 Harness**

이 프로젝트는 완성형 CRM이나 Business Development Platform이 **아니다.** 기능 수가 아니라
단순성 · 재사용성 · 이식성 · 근거추적성으로 성공을 판단한다.

---

## 2. 원칙 9개

이 9개는 기능 요구사항보다 우선한다. 충돌하면 원칙이 이긴다.

| 원칙 | 실무적 의미 |
|---|---|
| **Modular Core** | Core는 Interface만 알고 구현을 모른다. Core → Adapter 방향 import 금지 |
| **Database Agnostic** | Core에 SQL · ORM · 커넥션 · 트랜잭션이 등장하지 않는다 |
| **Bilingual by Design** | UI 문구를 코드에 쓰지 않는다. Core는 enum·code만 반환한다 |
| **Privacy by Default** | 기본 `storage_mode = EPHEMERAL`. 원본은 처리 후 삭제한다 |
| **AI Platform Agnostic** | 공통 규칙은 이 파일에. AI별 파일은 포인터만 |
| **Evidence First** | 근거 없는 Finding · SWOT · Client를 만들지 않는다 |
| **Structured Data First** | HTML/DOCX/PDF는 Output이다. 원본 Data가 아니다 |
| **Embeddable** | Reference App을 삭제해도 Core가 동작해야 한다 |
| **Human Decision First** | 최종 판단은 사람이 한다. 점수 총합으로 결론을 대신하지 않는다 |

---

## 3. 용어 (Glossary)

| 용어 | 정의 |
|---|---|
| **Evidence** | 업로드된 회사·시장·외부 자료에서 확인된 사실. 출처(`source_id`)를 갖는다 |
| **Finding** | Evidence를 Master Note 기준으로 해석한 결과. 반드시 Evidence를 참조한다 |
| **Master Note (MN)** | **분석 프레임워크.** 사실 데이터베이스가 **아니다.** 5절 참조 |
| **SWOT Issue** | Finding들을 S/W/O/T로 분류하고 Key Issue · Strategic Implication까지 압축한 것 |
| **Client Candidate** | 정합성 기준으로 발굴된 영업 대상 후보. 산업 내 기업 목록이 아니다 |
| **Market Scope** | `DOMESTIC` 또는 `INTERNATIONAL`. 국가별 별도 Engine을 만들지 않는다 |
| **Harness** | Core + Interfaces + Adapters. Reference App은 Harness가 아니다 |

---

## 4. 전체 Workflow

```
Business Data (Consulting Output / Company Data / External Business Data)
        |
        v
  +------------------- ENGINE 1: Research & Diagnosis -------------------+
  |  Evidence -> Finding -> Master Note Basis -> SWOT Classification     |
  |           -> Key Issue -> Strategic Implication                      |
  |  (+ Missing Evidence / Additional Research Required)                 |
  +------------------------------+---------------------------------------+
                                 v
  +------------------- ENGINE 2: Client & Proposal ----------------------+
  |  Client Candidate Discovery -> Fit Screening -> Priority Evaluation  |
  |           -> Top Candidates -> Top 3 Deep Analysis                   |
  |           -> Proposal Strategy                                       |
  +------------------------------+---------------------------------------+
                                 v
              Pricing Interface  ->  기존 Pricing Harness (별도 저장소)
                                 v
                        견적 및 제안작업
```

**Core는 이 2개 Engine으로 끝난다.** Pricing Engine을 새로 만들지 않는다 (8절 참조).

---

## 5. Master Note 사용 규칙

**Master Note는 Analysis Framework이고, 업로드된 자료가 Evidence다.** 이 구분이 무너지면
Harness 전체가 신뢰를 잃는다.

```
Company / Market / External Data  =  Evidence
Master Note                       =  Analysis Framework
```

### 절대 규칙

1. **Master Note만으로 시장·Client의 사실을 생성하지 않는다.** MN은 무엇을 확인해야 하는지를
   알려주고, 답은 Evidence에서만 나온다.
2. **Master Note를 코드에 하드코딩하지 않는다.** `KnowledgeProvider.get_framework("MN02")`로만
   접근한다.
3. 이 저장소의 `knowledge/master-notes/`에는 **공개용 framework card만** 둔다. 비공개 Master Note
   전문은 별도 Knowledge Adapter로 마운트한다 (9절 참조).

### Research & Diagnosis에서 사용하는 MN

| MN | 영역 | 확인 항목 |
|---|---|---|
| MN02 | 역량·아이템·산업·시장 | Capability, Product/Solution, Industry, Market Opportunity, TPM Alignment, Market/Product/Route Risk |
| MN03 | 고객·구매자·문제 | User, Buyer, Customer, Problem, Problem Severity, KBF, Customer Touchpoint |
| MN04 | 가치제안·경쟁우위·포지셔닝 | Competitor, Substitute, Comparison Criteria, Competitive Advantage, Value Proposition, Positioning |
| MN05 | 비즈니스모델 | Channel, Customer Relationship, Resource, Activity, Partner, BM Alignment |
| MN06 | 원가·가격·수익모델 | Cost, Price, Margin, Channel Cost, Revenue Model, Pricing Structure |
| MN07 | 사업타당성·유효시장·추정재무 | Feasibility, Sales Quantity, P x Qty, Estimated Profit, Valid Market, Scalability |

필요한 경우 **MN01**의 Business Purpose / Target Return / Growth Target / Risk Tolerance를
상위 판단기준으로 참조한다. **MN08**(실행 → 데이터 → 수정 → 재실행)은 MVP 범위 밖이다.

### Client Analysis에서는 MN 전체를 반복하지 않는다

Top 3 Client 분석은 **MN03 · MN04 · MN05 · MN06만** 사용한다. MN02 · MN07은 회사 차원의
진단이므로 Client별로 반복하지 않는다.

---

## 6. Evidence 규칙 (가장 중요한 실행 규칙)

### 6-1. 처리 순서를 건너뛰지 않는다

```
Evidence -> Finding -> Master Note Basis -> SWOT Classification
         -> Key Issue -> Strategic Implication
```

SWOT을 작성하라고 LLM에 **바로 요청하지 않는다.** SWOT은 분석의 시작점이 아니라 Master Note
기반 분석의 **압축 결과**다. Finding 없이 만들어진 SWOT은 `core.evidence`의 불변식 검사에서
거부된다.

### 6-2. Fact와 추론을 섞지 않는다

모든 Finding은 `evidence_type`을 갖는다.

| `evidence_type` | 의미 |
|---|---|
| `FACT` | 출처에서 직접 확인된 사실. `source_id` 필수 |
| `INFERENCE` | Evidence로부터의 추론. 근거 Evidence를 참조해야 한다 |
| `ASSUMPTION` | 근거가 없는 가정. 반드시 이 값으로 표시한다 |
| `MISSING_EVIDENCE` | 확인이 필요한데 자료가 없는 항목. 추가 조사 대상 |

### 6-3. 근거가 없으면 숫자를 만들지 않는다

`Confidence`는 `HIGH` / `MEDIUM` / `LOW` / `UNKNOWN`, Fit 평가는 `STRONG` / `MODERATE` /
`WEAK` / `UNKNOWN` / `EVIDENCE_NEEDED`. **임의의 점수·가중합·백분율을 생성하지 않는다.**
모르면 `UNKNOWN`, 확인이 필요하면 `EVIDENCE_NEEDED`로 남기고 사람이 판단한다.

### 6-4. 불변식 (코드로 강제됨)

`core/evidence.py`가 검사하고, 위반 시 `EvidenceRuleViolation`을 발생시킨다.

```
SWOTIssue.finding_ids                 != []
ResearchFinding.source_id 존재  또는   evidence_type in {ASSUMPTION, MISSING_EVIDENCE}
ClientAnalysis.evidence == []   ->     missing_evidence != []  필수
ClientCandidate                 ->     최소 1개의 finding_id 참조
ProposalStrategy                ->     client_id 참조 필수
```

---

## 7. Client Discovery 규칙

Client 후보를 **이 산업의 주요 기업 목록으로 생성하지 않는다.** 다음 정합성으로 찾는다.

```
Company Capability x Product/Solution x Market Opportunity
                   x Customer Problem x Purchasing Possibility
```

핵심 질문:

> **우리 회사가 가진 무엇을, 어느 시장의 어떤 기업이 가진 어떤 문제에 판매할 수 있는가?**

우선순위 평가 기준 8개 (전부 순서형 enum, 점수 아님):
Problem Fit · Solution Fit · Capability Fit · Market Attractiveness ·
Purchasing Potential · Accessibility · Competitive Situation · Evidence Quality

조직명에 대한 두 가지 규칙:

| 규칙 | |
|---|---|
| **근거에 없는 이름은 후보가 아니다** | 조직명은 인용된 구절에 **토큰 단위로**, **본문의 이름 전체를 설명하며** 존재해야 한다. Unicode·공백 정규화, 제한적 법인격 접미사, 닫힌 조사 목록까지만 허용하고, alias·fuzzy·embedding·LLM entity resolution은 쓰지 않는다. 모델의 일반지식은 여기서 근거가 아니다 |
| **검색 snippet만으로는 최우선이 되지 못한다** | 후보로 남고 P2까지 갈 수 있으나, P1에는 원문 확인이 필요하다 |

`sales_priority`는 **숫자 가중합이 아니라 규칙표**로 정한다 (`core/client/priority.py`). Band는
**영업 지시가 아니라 검토 순서**이며, 접근 여부는 사람이 결정한다.

Entity-level 집계 필드(`finding_ids` · `missing_evidence`)는 **pipeline이 파생**시킨다. 같은
관계를 두 곳에 따로 쓰면 어긋나므로, canonical 관계는 하위 구조에 한 번만 둔다.

모델 출력이 스키마의 길이 계약을 위반하면 **잘라서 저장하지 않는다.** 잘린 문장은 아무도 쓰지
않은 주장이다. 해당 출력을 폐기하고 safe code를 기록한 뒤 안전한 값으로 degrade한다.

국내·외는 **같은 Engine**을 쓴다. `market_scope`와 국가 필드로 구분하고, International일 때만
regulation · certification · tariff · logistics · exchange_rate · local_partner ·
distribution_structure · local_price · purchasing_power · entry_barrier 필드를 추가로 채운다.

---

## 8. 외부 저장소와의 계약

이 Harness는 다음 2개 외부 저장소에 의존하는 **계약**을 갖는다. 둘 다 **런타임 의존성이 아니다.**

| 외부 저장소 | 계약의 성격 | 이 저장소에서의 위치 |
|---|---|---|
| `pricing-harness-public` | `client_input.schema.json` 형태의 **JSON 파일 계약**. import 하지 않는다 | Phase 7 `adapters/pricing/file.py` |
| `business-planning-handbook` | MN01–MN08 ↔ CH01–CH08 매핑. 경로를 주입받아 읽는다 | `adapters/knowledge/handbook.py` |

**Pricing Engine을 이 저장소에 만들지 않는다.** Client Discovery는 `PricingResult.pricing_payload`
(Pricing Harness 스키마에 맞는 JSON)와 `commercial_context`(영업 컨텍스트)를 산출하는 데서
멈춘다. 계산은 Pricing Harness가 한다.

---

## 9. Public Repository 금지사항

이 저장소는 **GitHub와 웹사이트에 Public으로 공개**된다. 다음은 절대 커밋하지 않는다.

- 실제 Client 정보 · 실제 기업 내부자료 · 실제 컨설팅 데이터
- 개인정보 · API Key · Secret · Credential
- 비공개 제안서 · 비공개 Master Note 전문
- 특정 조직의 Production 정보 · Credential · 내부 설정

`examples/`의 Sample Data와 `tests/`의 Fixture는 **완전히 가상의 정보만** 사용한다. 거부되는
쪽의 예시도 마찬가지다 — hallucination 테스트에 실제 기업명을 쓸 이유가 없고, 검증은 그 이름이
유명한지가 아니라 구절에 있는지만 본다. `.gitignore`가 업로드 확장자와
`clients/` · `uploads/`를 선제적으로 차단하지만, 최종 책임은 커밋하는 사람에게 있다.

---

## 10. MVP 범위 밖 (만들지 않는다)

완성형 CRM · 자동 이메일 영업 · Sales Automation · 자동 Win/Loss 학습 ·
자동 Master Note 수정 · Knowledge Manager Agent · 대규모 Vector DB ·
국가별 별도 Engine · 복잡한 Multi-Agent Architecture · Microservice ·
Enterprise SSO · 복잡한 권한관리

추가로 Phase 1–8에서 제외:
인증·계정·멀티테넌시 · 비동기 Job Queue · LLM Streaming · PDF OCR ·
enum 값 번역 · Finding 자동 중복제거 · Priority 가중합 총점 · PyPI 배포

기능을 추가하고 싶으면 먼저 **이 목록에 들어 있지 않은지** 확인한다.

---

## 11. 성공기준

기능 수로 판단하지 않는다. 다음을 만족해야 한다.

- [ ] 실제 영업 대상 Client를 발견하는 데 도움이 된다
- [ ] 분석의 Evidence를 추적할 수 있다
- [ ] Public Server에 기업 원본자료가 불필요하게 남지 않는다
- [ ] 기업이 자체 Database를 연결할 수 있다
- [ ] 기업이 자체 Knowledge Framework를 연결할 수 있다
- [ ] 동일한 Core를 다른 조직의 내부 Engine으로 재사용할 수 있다
- [ ] 한국어와 영어를 모두 지원한다
- [ ] Claude Code · Codex · Gemini 등에서 동일 저장소를 이해할 수 있다
- [ ] LLM Provider를 교체해도 Core Workflow가 유지된다
- [ ] Reference Web App을 제거해도 Harness Core가 독립적으로 동작한다

마지막 두 항목은 `tests/test_core_purity.py`와 `tests/test_core_standalone.py`가 자동 검증한다.

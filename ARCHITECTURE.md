# ARCHITECTURE.md — 구조와 경계

> 이 저장소의 **규칙**은 [`HARNESS.md`](HARNESS.md)에 있다. 이 문서는 **구조**만 다룬다:
> 무엇이 어디에 있고, 무엇을 고치려면 어느 파일을 보는가.

---

## 1. 레이어

```
  +------------------- Web UI  (Phase 8, 별도 저장소) -----------------------+
  |  브라우저 · 화면 · 입력. Harness가 아니라 Harness를 쓰는 Interface다     |
  |  서버 렌더 mobile HTML. magisglobal.co.kr(정적 Astro)와는 분리된다       |
  +--------------------------------+---------------------------------------+
                                   | HTTP 등 (Core는 모른다)
  +--------------------------------v---------------------------------------+
  |  Application / API Layer  (Phase 8, 별도 저장소)                        |
  |  라우팅 · 인증 · 세션 · Bootstrap Analysis Run · training session        |
  |  환경변수를 읽어 Adapter를 생성하고 create_harness()에 주입한다          |
  |  provider 선택은 여기서 config/env로 한다. Core는 provider agnostic      |
  +--------------------------------+---------------------------------------+
                                   | 주입 (injection)
  +--------------------------------v---------------------------------------+
  |  core/   순수 로직. 파일 I/O · 환경변수 · HTTP · print 없음              |
  |                                                                        |
  |    models.py     Entity 8개 + enum                                     |
  |    evidence.py   Evidence 불변식 검사                                  |
  |    harness.py    create_harness() — Adapter 조립 지점                  |
  |    errors.py     예외 계층 + Intake error code                         |
  |    interfaces/   Protocol (Core가 소유하는 계약)                       |
  |                                                                        |
  |    intake/       policy · models(전송객체) · extract   (순수)          |
  |    research/     policy · select · extract · classify · synthesize     |
  |                  · confidence · transmission · pipeline   (ENGINE 1)   |
  |    client/       criteria · verify · fit · priority · pipeline         |
  |                  (ENGINE 2, 전반부 — 발굴)                             |
  |    analysis/     dimensions · claims · research · pipeline             |
  |                  (ENGINE 2, 후반부 — 사람이 고른 Client 심층분석)      |
  |    proposal/     objectives · strategy · objections · pipeline         |
  |                  (ENGINE 3 — 제안전략. 문서는 만들지 않는다)           |
  |    transmission.py  LLM 전송 단일 게이트웨이 (core 전체)                |
  |    pricing_bridge/ contract · payload · context · gaps(PricingGap)       |
  |                  · codes · policy · pipeline   (Phase 7 — LLM 없음)     |
  +--------+------------+------------+------------+------------------------+
           |            |            |            |
  +--------v------------v------------v------------v------------------------+
  |  adapters/   Interface 구현체. core를 import하지만 그 반대는 없다       |
  |    storage/  null · memory · sqlite                                   |
  |    knowledge/ static · handbook                                       |
  |    llm/      echo · anthropic       (이 저장소의 유일한 network 경로)    |
  |    search/   manual                   (+ web → 예정)                 |
  |    intake/   text · html · pdf · office · session · registry          |
  |    prompts/  prompt 파일 로딩 (core는 파일을 읽지 않는다)              |
  |    pricing/  file — pricing-harness-public와의 JSON 파일 교환          |
  +-----------------------------------------------------------------------+
```

**import 방향은 한 방향이다.** `adapters/` → `core/` 는 허용, `core/` → `adapters/` 는 **금지**.
`tests/test_core_purity.py`가 이를 검사한다.

---

## 2. Core vs Application Layer 경계

규칙의 원본은 `HARNESS.md` 12절(Web-ready, UI-independent)이다. 여기서는 그 경계가 파일
수준에서 어떻게 갈리는지만 적는다.

| | `core/` | Application Layer (`reference-app/` 등) |
|---|---|---|
| 파일 시스템 접근 | **금지** | tempdir 소유·삭제 |
| 환경변수 / secret | **금지** | 읽어서 Adapter 생성 |
| HTTP · route · 세션 · 쿠키 | **모름** | 소유 |
| Browser · HTML rendering | **모름** | 소유 |
| 인증 · 계정 · 권한 | **모름** | 소유 |
| 배포 대상 (URL · 도메인) | **모름** | 소유 |
| 교육 세션 · QR · 팀 편성 | **모름** | 소유 |
| Adapter **선택** | 금지 (주입만 받음) | wiring 담당 |
| 사용자 표시 문구 | 금지 (enum·code만 반환) | `locales/*.json`으로 렌더 |
| LLM 호출 | `LLMProvider` 경유만 | 직접 호출 금지 |
| `print` / logging | 금지 (예외·결과 반환) | allowlist 로깅 |

아래 절반은 Phase 8에서 처음 생긴다. 지금 `core/`가 그것들을 모른다는 사실이 중요한 이유는,
Phase 8에 가서야 알게 되면 이미 늦기 때문이다.

### Phase 8 Application은 별도 저장소다

`magisglobal.co.kr`(`rando-knowledge-web`)은 **런타임이 없는 Astro 정적 사이트**다 —
adapter 없음, UI framework 없음, client JS 없음, API route 없음. 따라서 Application은 그
사이트 안이 아니라 **별도 저장소·별도 배포**로 만들고, 사이트는 설명 페이지와 CTA만 제공한다.
근거와 측정치는 `docs/product-spec.md`의 Phase 8 절에 있다.

Application이 소유하는 것 중 Core에 **절대 들어오지 않는** 것:

```
Bootstrap Analysis Run 오케스트레이션 · background task · 폴링 상태
training session · participant · prediction · reveal state
StepStatus 같은 화면 상태 enum · view model · UI chrome locale
provider 선택 · session · auth · QR · 배포 대상
```

`EvidenceCandidate`가 저장 불가라는 사실이 이 경계를 강제한다: research와 discovery는 한
operation 안에서 끝나야 하고, 그 오케스트레이션은 Core가 아니라 Application의 일이다.

### 경계를 강제하는 테스트 4개

| 테스트 | 검사 내용 |
|---|---|
| `tests/test_core_purity.py` | `core/` 전체를 AST로 스캔해 금지된 import(`os`, `pathlib`, `requests`, `httpx`, `anthropic`, `openai`, `sqlite3`, …)와 `open(`/`print(` 호출을 찾는다 |
| `tests/test_core_standalone.py` | `reference-app/`과 `adapters/`가 없는 상태를 가정하고 `core`만 import해 Entity·불변식이 동작하는지 확인한다 |
| `tests/test_docs_no_duplication.py` | `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`가 얇은 포인터로 유지되는지 (길이·복제 여부) 확인한다 |
| `tests/test_llm_anthropic.py` | `core/`와 `adapters/` 전체를 AST로 스캔해 network·provider SDK import(`urllib`, `socket`, `ssl`, `httpx`, `anthropic`, `openai`, …)가 **`adapters/llm/` 밖에 없음**을 확인한다. 오늘 이 저장소에서 소켓을 열 수 있는 모듈은 정확히 하나다 |

`core/`가 `dataclasses`, `enum`, `typing`, `datetime`, `uuid`, `re`, `hashlib`을 쓰는 것은 허용한다.
표준 라이브러리 중 **부수효과를 갖는 것만** 금지된다.

---

## 3. Interface

Core가 소유하는 계약이다. **4개가 harness로 조립되고**, `DocumentParser`는 계약이지만
provider가 아니다. 나머지 2개는 이 문서에 정의만 둔다 (구현 시점에 코드로 옮긴다).

| Interface | 상태 | 주요 메서드 | 파일 |
|---|---|---|---|
| **StorageProvider** | 구현 | `save_project` `get_project` `save_source_metadata` `get_source_metadata` `save_finding` `get_findings` `save_swot_issue` `get_swot_issues` `save_client` `get_clients` `save_client_analysis` `get_client_analyses` `save_proposal_strategy` `get_proposal_strategies` `save_pricing_result` `get_pricing_results` | `core/interfaces/storage.py` |
| **KnowledgeProvider** | 구현 | `get_framework(framework_id)` `list_frameworks()` | `core/interfaces/knowledge.py` |
| **LLMProvider** | 구현 | `generate` `generate_structured` `analyze` `summarize` | `core/interfaces/llm.py` |
| **SearchProvider** | 구현 | `search(query, scope, country, limit)` | `core/interfaces/search.py` |
| **DocumentParser** | 구현 | `parse(data: bytes, *, file_type)` | `core/interfaces/intake.py` |
| ~~PricingProvider~~ | **만들지 않음** | Core가 Pricing Harness를 호출하지 않으므로 provider가 아니다 — 아래 | |
| ReportProvider | Phase 9 | `render(entity, lang, output_format)` | — |

### DocumentParser는 provider가 아니다

`create_harness()`는 여전히 **4개 provider**만 받는다. Intake는 request-scoped다 — 파일마다
파서를 골라 쓰고 버린다. Harness 수명에 묶으면 있지도 않은 지속성을 암시하게 된다. 파서 선택은
`adapters/intake/registry.py`가 담당한다.

계약의 경계가 **경로가 아니라 `bytes`인 것**도 의도적이다. Core는 `bytes` 타입을 언급할 뿐
아무것도 열지 않으며, 8종 전부 메모리에서 파싱되므로 이 구현이 임시 파일을 만들지 않는다.
파서 시그니처에 `filename` 파라미터가 없어서 **원본 파일명이 구조적으로 유입 불가능**하다.

### PricingProvider는 만들지 않았다

Phase 7 계획에는 `PricingProvider` Protocol이 있었다. 구현하면서 취소했다 — **Core가
Pricing Harness를 호출하지 않기 때문이다.** provider는 Core가 부르는 것이고, 부르지 않는
것에 Protocol을 씌우면 계약이 아니라 추측이 된다 (`docs/development-guide.md`).

```
core/pricing_bridge      payload 조립. 여기서 멈춘다
adapters/pricing/file    파일로 내보내고 결과 파일을 읽는다
Pricing Harness          별도 프로세스에서 계산한다
core/pricing_bridge      attach_engine_result()로 결과를 기록한다
```

`create_harness()`는 그대로 **provider 4개**를 받는다. `FilePricingBridge`는 그 디렉토리를
소유하는 Application Layer가 직접 조립한다.

### Protocol을 쓰는 이유

`typing.Protocol`은 **구조적 타이핑**이다. 기업이 자체 Adapter를 만들 때 우리 base class를
상속할 필요가 없다 — 메서드 시그니처만 맞으면 된다. ABC를 쓰면 그 순간 기업 코드가 이
저장소에 상속으로 묶이고 Database Agnostic 원칙이 깨진다.

### Auth는 Interface가 아니다

인증은 **Reference App의 관심사**다. Core에 Auth Interface를 두면 Core가 "누가 호출하는가"를
알게 되어 Embeddable 원칙이 깨진다. 기업 SSO는 App 레이어에서 붙인다.

---

## 4. Adapter 목록

| Adapter | Interface | Phase | 설명 |
|---|---|---|---|
| `adapters/storage/null.py` | Storage | 1 | **기본값.** 모든 save가 no-op, 모든 get이 빈 결과. Public Web의 EPHEMERAL 모드 |
| `adapters/storage/memory.py` | Storage | 1 | 프로세스 메모리. 한 세션 안에서 파이프라인을 연결할 때만 |
| `adapters/knowledge/static.py` | Knowledge | 1 | `knowledge/master-notes/*.json`을 읽는다 (경로 주입) |
| `adapters/knowledge/handbook.py` | Knowledge | 1 | `business-planning-handbook` 경로를 주입받아 CH 매핑을 덧붙인다 |
| `adapters/llm/echo.py` | LLM | 1 | **결정적**. API 키·네트워크 없이 CI에서 전체 파이프라인을 돌린다 |
| `adapters/search/manual.py` | Search | 1 | 사용자가 직접 붙여넣은 자료만 반환. 웹 검색을 하지 않는다 |
| `adapters/intake/text.py` | DocumentParser | 2 | TXT · MD · CSV. stdlib만 사용 |
| `adapters/intake/html.py` | DocumentParser | 2 | stdlib `html.parser`. script·style·noscript·주석 제외 |
| `adapters/intake/pdf.py` | DocumentParser | 2 | pypdf. 텍스트 레이어만, OCR 없음 |
| `adapters/intake/office.py` | DocumentParser | 2 | DOCX · PPTX · XLSX. package 내부로 타입 판별 + zip bomb 방어 |
| `adapters/intake/session.py` | — | 2 | request 수명 · batch 상한 · 버퍼 해제 |
| `adapters/llm/anthropic.py` | LLM | 8 | **완료.** 첫 production provider. Messages API · key·model 주입 · transport 주입 · 기본 재시도 없음 · 로그 없음 |
| `adapters/search/web.py` | Search | 3 | 예정 |
| `adapters/pricing/file.py` | — (provider 아님) | 7 | `pricing-harness-public`와의 JSON 파일 교환. 스키마 경로를 주입받으면 실제 계약으로 검증한다 |
| `adapters/storage/sqlite.py` | Storage | 8 | **완료.** Core 9 entity를 table 1개 + payload JSON으로. 경로 주입 · WAL · schema version · `clear()` 없음 |

### 첫 production LLM Adapter가 Anthropic인 것은 architecture 결정이 아니다

`adapters/llm/anthropic.py`가 Phase 8에서 먼저 생겼을 뿐이고, **Core·prompts·pipeline
어디에도 provider 개념이 없다.** 고르는 주체는 Application wiring이다
(`docs/product-spec.md` "Provider adapter는 config가 고른다").

세 가지가 그것을 구조로 붙잡는다.

1. **`prompts/`에 vendor 이름이 없다** — `test_research.py`·`test_client_discovery.py`가 검사한다.
2. **`core/`가 provider SDK를 import하지 못한다** — `test_core_purity.py`.
3. **network 모듈이 `adapters/llm/` 밖에 없다** — `test_llm_anthropic.py`.

### policy selection ≠ provider transport

같은 경계가 **generation budget**에도 적용된다. `max_tokens`는 `api_key`·`model`과 마찬가지로
`AnthropicLLM` 생성 시 **필수 인자이고 기본값이 없다.**

| | |
|---|---|
| **Application wiring** | 배포·용도에 맞는 budget을 고른다. 필요하면 config/env에 기본 정책을 갖는다. 고른 값을 adapter에 **명시적으로** 전달한다 |
| **Adapter** | 고르지 않는다 · model에서 추론하지 않는다 · prompt 길이에서 계산하지 않는다 · provider별 heuristic 없다 · **받은 값을 그대로 request body에 넣는다** |

adapter가 model별 token ceiling을 알고 있다고 가정하지 않는다. 한도를 넘으면 provider가
거부하고 `LLM_INVALID_REQUEST`로 온다 — 실제로 아는 쪽이 답한다. sampling control과
`thinking`도 같은 이유로 보내지 않는다: 그것들은 전부 정책이고, 정책은 이 층의 것이 아니다.

그리고 `tests/test_llm_contract.py`는 `LLMProvider` 계약을 **echo와 anthropic 양쪽에 같이**
돌린다 — research pipeline 전체를 두 provider로 각각 실행하는 것까지 포함한다. "LLM Provider를
교체해도 Core Workflow가 유지된다"는 성공기준이 주장에서 **실행되는 테스트**로 바뀌는 지점이다.

---

### `echo` LLM Adapter를 Phase 1에 먼저 만드는 이유

1. API 키·비용·네트워크 없이 전체 파이프라인을 CI에서 실행할 수 있다.
2. "LLM Provider를 교체해도 Core Workflow가 유지된다"는 성공기준을 **처음부터** 증명한다.
3. `generate_structured()`가 우리 JSON Schema로부터 유효한 인스턴스를 합성하므로, **스키마가
   실제로 충족 가능한지** 검증된다.

---

## 5. 무엇을 고치려면 어디를 보는가

| 하고 싶은 일 | 보는 파일 |
|---|---|
| 원칙·규칙을 바꾼다 | `HARNESS.md` (**다른 곳에 복제하지 않는다**) |
| Entity에 필드를 추가한다 | `core/models.py` + `schemas/<entity>.schema.json` + `docs/data-model.md` (**3개 동시에**) |
| Evidence 규칙을 바꾼다 | `core/evidence.py` + `HARNESS.md` 6절 |
| 새 DB를 연결한다 | `adapters/storage/` 에 모듈 추가. `core/`는 건드리지 않는다. `sqlite.py`가 참고 구현 |
| 저장 의미를 바꾼다 | 바꾸지 않는다. append/replace·순서는 `MemoryStorage`가 정본이고 adapter는 복제한다 |
| 다른 LLM을 붙인다 | `adapters/llm/` 에 모듈 추가 |
| 자체 방법론을 붙인다 | `adapters/knowledge/` 에 모듈 추가 |
| 새 파일 형식을 지원한다 | `adapters/intake/` 에 파서 추가 + `registry.py` 등록 |
| Prompt를 고친다 | `prompts/**/*.md`. 코드에 프롬프트 문자열을 쓰지 않는다 |
| LLM 호출을 추가한다 | **`core/transmission.send()`를 거친다.** `core/` 안 어디서든 provider를 직접 호출하면 `test_transmission_boundary.py`가 실패한다 |
| Client 우선순위 규칙을 바꾼다 | `core/client/priority.py`의 규칙표. 숫자를 도입하지 않는다 |
| 조직명 매칭을 손본다 | `core/client/verify.py`. 토큰 경계를 풀지 않고, semantic alias를 들이지 않는다. Phase 5도 이 모듈을 그대로 쓴다 |
| Client 심층분석 규칙을 바꾼다 | `core/analysis/dimensions.py`의 kind·ceiling 표. 교차 의존은 `claims.py` |
| 제안 목표 규칙을 바꾼다 | `core/proposal/objectives.py`의 요건표. 자동 fallback을 만들지 않는다 |
| Entity에 집계 필드를 추가한다 | 파생 함수를 `core/models.py`에 두고 `core/evidence.py`가 관계를 검증한다 |
| Web·API를 붙인다 | `core/`가 아니라 **별도 Application 저장소.** 경계는 2절, 규칙은 `HARNESS.md` 12절 |
| Training session을 만든다 | Application. Core Entity도 `StorageProvider` 메서드도 추가하지 않는다 |
| 화면 상태를 추가한다 | Application view model에서 합성한다. Core에 universal status enum을 만들지 않는다 |
| 업로드 상한을 바꾼다 | `IntakePolicy`를 만들어 주입한다. `core/`는 환경변수를 읽지 않는다 |
| UI 문구를 바꾼다 | `locales/ko.json` · `locales/en.json` |
| MN 프레임워크 항목을 바꾼다 | `knowledge/master-notes/MN0*.json` |
| Prompt를 바꾼다 | `prompts/<stage>/*.md` (코드에 프롬프트를 쓰지 않는다) |
| Pricing 연계를 바꾼다 | 계약 이름·enum은 `core/pricing_bridge/contract.py` **한 파일**. 파일 I/O는 `adapters/pricing/file.py` |
| Pricing gate 규칙을 바꾼다 | `core/pricing_bridge/gaps.py`. 막는 timing을 늘리지 않고, `gap_ref` 파생 규칙을 바꾸면 기존 승인이 전부 무효화된다 |
| Pricing에 숫자를 추가한다 | `CommercialInput`에 필드를 추가한다. claim에서 유도하지 않는다 |
| 개발 순서를 확인한다 | `docs/development-guide.md` |

---

## 6. 외부 저장소 계약

### 6-1. Pricing Harness (`pricing-harness-public`)

**연결 방식: JSON 파일 계약. import 하지 않는다.**

```
Client Discovery Harness                          Pricing Harness
------------------------                          ---------------
ClientAnalysis  +  ProposalStrategy
        +  CommercialInput (호출자 숫자, transient)
        |
        v  core/pricing_bridge      (결정적. LLM 없음)
PricingResult
  ├─ pricing_payload   --(JSON 파일)-->  client_input.schema.json 검증
  │                     adapters/pricing/file.py    build_analysis_result(...)
  │                                                          |
  │                    <--(JSON 파일)---  analysis_result.schema.json
  │                     attach_engine_result()  → engine_result (원문 보관)
  │
  └─ commercial_context   여기 남는다. 보내지 않는다
```

`pricing_payload`는 Pricing Harness의 `client_input.schema.json` **필수 필드에 정확히
맞춘다**: `schema_version`, `client_id`, `case_id`, `product`, `tax`, `fx`, `costs`.
`schema_version`은 **그쪽 계약 version**이고 (`CommercialInput.contract_version`, 기본값 없음),
`case_id`는 `pricing_case_id`다 — `strategy_id`가 아니다. 한 전략에서 여러 case가 나온다.

`commercial_context`는 **보내지 않는다.** 그쪽 스키마에 그런 필드가 없고 최상위가
`additionalProperties: false`다. 열려 있는 `meta`에 밀어넣지도 않는다 — 거기 들어가는 것은
`strategy_id` · `analysis_id` 두 개뿐이다. context는 `PricingResult` 안에 남아 UI · Phase 9 ·
audit이 읽는다. 담기는 것은 MN06 claim 4개(provenance 포함) · 확정된 PROBLEM · KBF ·
COMPETITIVE_ADVANTAGE · offered 결속 · objective · 상업적 gap이며, **분석 전체를 복제하지
않는다.** 근거 원문은 어느 쪽에도 복사되지 않는다 (`finding_ids`로 도달한다).

`price_component`도 닫혀 있으므로 `solution_element_ref`는 payload에 넣지 않는다. 결속의
canonical 위치는 `commercial_context.offered`다.

Phase 7은 숫자를 만들지 않는다. 규칙은 `HARNESS.md` 8절에 있다.

> **알려진 제약 — `core` 패키지 이름 충돌**
> `pricing-harness-public`은 pip-installable이 아니며(`pyproject.toml`/`setup.py` 없음),
> `from core.engine...` 형태로 import하므로 저장소 루트를 `sys.path`에 넣어야 동작한다.
> 이 저장소도 top-level 패키지명이 `core`이므로 **두 저장소를 같은 프로세스에서 import하면
> 충돌한다.** 그래서 Pricing Adapter는 in-process import를 하지 않고 JSON 파일로 교환한다.
> 이 결정을 되돌리려면 이 저장소의 패키지명을 먼저 바꿔야 한다.
>
> 이 제약은 **Python import에만** 적용된다. 그쪽 스키마 *파일*을 읽는 것은 충돌하지 않으므로,
> `FilePricingBridge.from_repository(path)`는 실제 `client_input.schema.json`으로 검증한다.
> 경로가 없으면 자체 contract 검사만 하고 `EXTERNAL_CONTRACT_NOT_CHECKED`로 표시한다.

### 6-2. Business Planning Handbook (`business-planning-handbook`)

MN01–MN08 ↔ CH01–CH08 매핑이 그 저장소의 `source-map.md`에 이미 있고, `ko/` · `en/` 양쪽에
chapters와 worksheet이 존재한다. `adapters/knowledge/handbook.py`는 그 **경로를 주입받아**
읽는다. 내용을 이 저장소로 복사하지 않는다 (복사하면 두 곳이 drift 한다).

---

## 7. Phase별로 추가될 디렉토리

**실제로 동작하는 것만** 만든다. 빈 패키지를 미리 만들어 두지 않는다.

| Phase | 추가 | 상태 |
|---|---|---|
| 2 | `core/intake/` · `adapters/intake/` | **완료** |
| 3 | `core/research/` · `adapters/prompts/` | **완료** |
| 3+ | `adapters/search/web.py` | 예정 |
| 4 | `core/client/` · `prompts/discovery/` | **완료** |
| 5 | `core/analysis/` · `prompts/analysis/` | **완료** |
| 6 | `core/proposal/` · `prompts/proposal/` | **완료** |
| 7 | `core/pricing_bridge/` · `adapters/pricing/` | **완료** |
| 8 | `adapters/storage/sqlite.py` **완료** · `adapters/llm/anthropic.py` **완료** · production Search adapter는 미구현. Application·UI는 **별도 저장소** | 진행 중 |
| 9 | `core/interfaces/reporting.py` · `adapters/reporting/` | 예정 |

# ARCHITECTURE.md — 구조와 경계

> 이 저장소의 **규칙**은 [`HARNESS.md`](HARNESS.md)에 있다. 이 문서는 **구조**만 다룬다:
> 무엇이 어디에 있고, 무엇을 고치려면 어느 파일을 보는가.

---

## 1. 레이어

```
  +------------------- reference-app/  (Phase 8, 삭제 가능) -----------------+
  |  Upload -> tempdir -> 4 Screens -> i18n render -> cleanup               |
  |  환경변수를 읽어 Adapter를 생성하고 create_harness()에 주입한다          |
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
  |                  (ENGINE 2, 전반부)                                    |
  |    transmission.py  LLM 전송 단일 게이트웨이 (core 전체)                |
  |    pricing_bridge/ Phase 7 예정                                        |
  +--------+------------+------------+------------+------------------------+
           |            |            |            |
  +--------v------------v------------v------------v------------------------+
  |  adapters/   Interface 구현체. core를 import하지만 그 반대는 없다       |
  |    storage/  null · memory            (+ sqlite → Phase 8)            |
  |    knowledge/ static · handbook                                       |
  |    llm/      echo                     (+ anthropic → Phase 3)         |
  |    search/   manual                   (+ web → Phase 3)               |
  |    intake/   text · html · pdf · office · session · registry          |
  |    prompts/  prompt 파일 로딩 (core는 파일을 읽지 않는다)              |
  |                                       (+ pricing/ → Phase 7)          |
  +-----------------------------------------------------------------------+
```

**import 방향은 한 방향이다.** `adapters/` → `core/` 는 허용, `core/` → `adapters/` 는 **금지**.
`tests/test_core_purity.py`가 이를 검사한다.

---

## 2. Core vs Reference App 경계

| | `core/` | `reference-app/` |
|---|---|---|
| 파일 시스템 접근 | **금지** | tempdir 소유·삭제 |
| 환경변수 / secret | **금지** | 읽어서 Adapter 생성 |
| HTTP · 세션 · 쿠키 | **모름** | 소유 |
| Adapter **선택** | 금지 (주입만 받음) | wiring 담당 |
| 사용자 표시 문구 | 금지 (enum·code만 반환) | `locales/*.json`으로 렌더 |
| LLM 호출 | `LLMProvider` 경유만 | 직접 호출 금지 |
| `print` / logging | 금지 (예외·결과 반환) | allowlist 로깅 |

### 경계를 강제하는 테스트 3개

| 테스트 | 검사 내용 |
|---|---|
| `tests/test_core_purity.py` | `core/` 전체를 AST로 스캔해 금지된 import(`os`, `pathlib`, `requests`, `httpx`, `anthropic`, `openai`, `sqlite3`, …)와 `open(`/`print(` 호출을 찾는다 |
| `tests/test_core_standalone.py` | `reference-app/`과 `adapters/`가 없는 상태를 가정하고 `core`만 import해 Entity·불변식이 동작하는지 확인한다 |
| `tests/test_docs_no_duplication.py` | `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`가 얇은 포인터로 유지되는지 (길이·복제 여부) 확인한다 |

`core/`가 `dataclasses`, `enum`, `typing`, `datetime`, `uuid`, `re`를 쓰는 것은 허용한다.
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
| PricingProvider | Phase 7 | `to_pricing_input(strategy, cost_input)` `run_pricing(pricing_input)` | — |
| ReportProvider | Phase 9 | `render(entity, lang, output_format)` | — |

### DocumentParser는 provider가 아니다

`create_harness()`는 여전히 **4개 provider**만 받는다. Intake는 request-scoped다 — 파일마다
파서를 골라 쓰고 버린다. Harness 수명에 묶으면 있지도 않은 지속성을 암시하게 된다. 파서 선택은
`adapters/intake/registry.py`가 담당한다.

계약의 경계가 **경로가 아니라 `bytes`인 것**도 의도적이다. Core는 `bytes` 타입을 언급할 뿐
아무것도 열지 않으며, 8종 전부 메모리에서 파싱되므로 이 구현이 임시 파일을 만들지 않는다.
파서 시그니처에 `filename` 파라미터가 없어서 **원본 파일명이 구조적으로 유입 불가능**하다.

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
| `adapters/llm/anthropic.py` | LLM | 3 | 예정 |
| `adapters/search/web.py` | Search | 3 | 예정 |
| `adapters/pricing/file.py` | Pricing | 7 | 예정. JSON 파일 계약 |
| `adapters/storage/sqlite.py` | Storage | 8 | 예정. Dashboard와 함께 |

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
| 새 DB를 연결한다 | `adapters/storage/` 에 모듈 추가. `core/`는 건드리지 않는다 |
| 다른 LLM을 붙인다 | `adapters/llm/` 에 모듈 추가 |
| 자체 방법론을 붙인다 | `adapters/knowledge/` 에 모듈 추가 |
| 새 파일 형식을 지원한다 | `adapters/intake/` 에 파서 추가 + `registry.py` 등록 |
| Prompt를 고친다 | `prompts/**/*.md`. 코드에 프롬프트 문자열을 쓰지 않는다 |
| LLM 호출을 추가한다 | **`core/transmission.send()`를 거친다.** `core/` 안 어디서든 provider를 직접 호출하면 `test_transmission_boundary.py`가 실패한다 |
| Client 우선순위 규칙을 바꾼다 | `core/client/priority.py`의 규칙표. 숫자를 도입하지 않는다 |
| 조직명 매칭을 손본다 | `core/client/verify.py`. 토큰 경계를 풀지 않고, semantic alias를 들이지 않는다 |
| Entity에 집계 필드를 추가한다 | 파생 함수를 `core/models.py`에 두고 `core/evidence.py`가 관계를 검증한다 |
| 업로드 상한을 바꾼다 | `IntakePolicy`를 만들어 주입한다. `core/`는 환경변수를 읽지 않는다 |
| UI 문구를 바꾼다 | `locales/ko.json` · `locales/en.json` |
| MN 프레임워크 항목을 바꾼다 | `knowledge/master-notes/MN0*.json` |
| Prompt를 바꾼다 | `prompts/<stage>/*.md` (코드에 프롬프트를 쓰지 않는다) |
| Pricing 연계를 바꾼다 | `adapters/pricing/` + `docs/product-spec.md` |
| 개발 순서를 확인한다 | `docs/development-guide.md` |

---

## 6. 외부 저장소 계약

### 6-1. Pricing Harness (`pricing-harness-public`)

**연결 방식: JSON 파일 계약. import 하지 않는다.**

```
Client Discovery Harness                    Pricing Harness
------------------------                    ---------------
ProposalStrategy.pricing_input
        |
        v
PricingResult.pricing_payload   --(JSON)-->  client_input.schema.json 검증
PricingResult.commercial_context             build_analysis_result(...)
                                                     |
                                <--(JSON)---  analysis_result.schema.json
```

`pricing_payload`는 Pricing Harness의 `client_input.schema.json` **필수 필드에 정확히
맞춘다**: `schema_version`, `client_id`, `case_id`, `product`, `tax`, `fx`, `costs`.

`commercial_context`는 Pricing Engine이 소비하지 않는 영업 컨텍스트(client · country ·
problem · buyer · value_proposition · competitive_advantage · competitor · channel ·
commercial_conditions)를 담는다. 제안서 작성에만 쓰인다.

> **알려진 제약 — `core` 패키지 이름 충돌**
> `pricing-harness-public`은 pip-installable이 아니며(`pyproject.toml`/`setup.py` 없음),
> `from core.engine...` 형태로 import하므로 저장소 루트를 `sys.path`에 넣어야 동작한다.
> 이 저장소도 top-level 패키지명이 `core`이므로 **두 저장소를 같은 프로세스에서 import하면
> 충돌한다.** 그래서 Pricing Adapter는 in-process import를 하지 않고 JSON 파일로 교환한다.
> 이 결정을 되돌리려면 이 저장소의 패키지명을 먼저 바꿔야 한다.

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
| 3+ | `adapters/llm/anthropic.py` · `adapters/search/web.py` | 예정 |
| 4 | `core/client/` · `prompts/discovery/` | **완료** |
| 5–6 | `core/client/` 확장 (Top 3 분석 · 제안전략) | 예정 |
| 7 | `core/pricing_bridge/` · `adapters/pricing/` | 예정 |
| 8 | `reference-app/` · `adapters/storage/sqlite.py` | 예정 |
| 9 | `core/interfaces/reporting.py` · `adapters/reporting/` | 예정 |

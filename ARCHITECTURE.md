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
  |    errors.py     예외 계층                                             |
  |    interfaces/   Protocol (Core가 소유하는 계약)                       |
  |                                                                        |
  |    intake/       Phase 2 예정                                          |
  |    research/     Phase 3 예정  (ENGINE 1)                              |
  |    client/       Phase 4-6 예정 (ENGINE 2)                             |
  |    pricing_bridge/ Phase 7 예정                                        |
  +--------+------------+------------+------------+------------------------+
           |            |            |            |
  +--------v------------v------------v------------v------------------------+
  |  adapters/   Interface 구현체. core를 import하지만 그 반대는 없다       |
  |    storage/  null · memory            (+ sqlite → Phase 8)            |
  |    knowledge/ static · handbook                                       |
  |    llm/      echo                     (+ anthropic → Phase 3)         |
  |    search/   manual                   (+ web → Phase 3)               |
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

## 3. Interface 6개

Core가 소유하는 계약이다. **Phase 1에서는 4개를 Protocol로 확정**하고, 나머지 2개는 이 문서에
정의만 둔다 (구현 시점에 코드로 옮긴다).

| Interface | 상태 | 주요 메서드 | 파일 |
|---|---|---|---|
| **StorageProvider** | 구현 | `save_project` `get_project` `save_source_metadata` `get_source_metadata` `save_finding` `get_findings` `save_swot_issue` `get_swot_issues` `save_client` `get_clients` `save_client_analysis` `get_client_analysis` `save_proposal_strategy` `get_proposal_strategies` `save_pricing_result` `get_pricing_results` | `core/interfaces/storage.py` |
| **KnowledgeProvider** | 구현 | `get_framework(framework_id)` `list_frameworks()` | `core/interfaces/knowledge.py` |
| **LLMProvider** | 구현 | `generate` `generate_structured` `analyze` `summarize` | `core/interfaces/llm.py` |
| **SearchProvider** | 구현 | `search(query, scope, country, limit)` | `core/interfaces/search.py` |
| PricingProvider | Phase 7 | `to_pricing_input(strategy, cost_input)` `run_pricing(pricing_input)` | — |
| ReportProvider | Phase 9 | `render(entity, lang, output_format)` | — |

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

Phase 1은 **실제로 동작하는 것만** 만든다. 빈 패키지를 미리 만들어 두지 않는다.

| Phase | 추가 |
|---|---|
| 2 | `core/intake/` · `adapters/` 파일 파서 의존성 |
| 3 | `core/research/` · `adapters/llm/anthropic.py` · `adapters/search/web.py` |
| 4–6 | `core/client/` |
| 7 | `core/pricing_bridge/` · `adapters/pricing/` |
| 8 | `reference-app/` · `adapters/storage/sqlite.py` |
| 9 | `core/interfaces/reporting.py` · `adapters/reporting/` |

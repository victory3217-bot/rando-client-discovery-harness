# Privacy

> `core/intake/`나 `adapters/intake/`, Reference App을 만질 때 **반드시** 먼저 읽는다.
> 규칙의 원본은 `HARNESS.md` 9절이고, 이 문서는 그 규칙이 코드에서 어떻게 지켜지는지를 다룬다.

---

## 0. 먼저 알아야 할 것: Zero-persistence ≠ Zero-transmission

이 Harness는 업로드된 원본을 **저장하지 않는다.** 그러나 분석을 위해 추출된 텍스트는
**설정된 LLM Provider로 전송된다.** 다른 문제이고, 둘 다 사용자에게 알려야 한다.

| | 기본 동작 |
|---|---|
| 원본을 서버에 영구 저장 | **하지 않는다** (`storage_mode = EPHEMERAL`) |
| Intake 구현이 temp file 생성 | **하지 않는다** — 8종 전부 메모리에서 파싱 (1절) |
| 로그·캐시·백업·Vector DB에 원문 기록 | **하지 않는다** |
| 외부 LLM API로 추출 텍스트 전송 | **한다** — 설정한 Provider에 따라 |

전송이 일어나는 지점은 `core/transmission.py`의 **`send()` 한 곳뿐**이다. Intake는 전송하지
않는다 — 문서 텍스트가 외부로 나가는 것은 분석 단계(Phase 3·4)가 처음이다.

`tests/test_transmission_boundary.py`가 **`core/` 전체**를 AST로 스캔해, `transmission.py`
외의 모듈이 `analyze` · `generate_structured` · `generate` · `summarize`를 직접 호출하면
실패시킨다. 규약이 아니라 통과 불가능한 경계이며, 한 패키지가 아니라 core 전체를 보기 때문에
새 Engine이 두 번째 통로를 조용히 열 수 없다.

전송 기록(`TransmissionRecord`)에는 **개수·문자수·stage·framework id·provider 이름만** 남는다.
본문은 없다.

거부 기록(`Rejection`)과 검토 플래그(`ReviewFlag`)도 마찬가지다 — **code · stage · reference**
만 담고, reference는 `safe_reference()`가 식별자 형태가 아니면 `<omitted>`로 바꾼다. 진단
기록이 문서를 인용하면 나머지 로깅 규칙이 무의미해진다.

### 외부 Provider의 정책은 이 Harness가 보장하지 않는다

받은 데이터를 provider가 어떻게 취급하는지는 이 코드의 통제 밖이다. 도입 시 **provider별로
직접 확인해야 하는 항목**:

| 항목 | 확인 내용 |
|---|---|
| retention | 요청·응답을 얼마나 보관하는가 |
| training usage | 입력이 모델 학습에 쓰이는가, 옵트아웃이 가능한가 |
| data residency | 어느 리전에서 처리되는가 |
| enterprise privacy | 조직 계정에서 위 항목이 달라지는가 |

특정 vendor의 정책을 코드에 하드코딩하지 않는다. 정책은 배포의 속성이지 이 코드의 속성이
아니며, 하드코딩하면 바뀌었을 때 거짓말이 된다.

`locales/*.json`의 `messages.ephemeral_notice`와 `messages.transmission_notice`가 이 두 가지를
각각 알린다. **둘 중 하나만 표시하지 않는다** — `tests/test_locales.py`가 두 문구의 존재를
검사한다.

원본이 조직 밖으로 나가는 것 자체가 허용되지 않는 환경에서는 Local Model Adapter를 연결한다.
`LLMProvider` Interface가 그것을 위해 존재한다.

---

## 1. Intake Flow — memory-first

```
bytes (bytearray)
  │
  ├─ 1. source_id = new_id("src")      랜덤 UUID. 파일명은 애초에 전달되지 않는다
  ├─ 2. 크기 게이트                     IntakePolicy 상한 초과 → FILE_TOO_LARGE (파싱 안 함)
  ├─ 3. magic byte 검사                 선언 타입 ≠ 실제 시그니처 → TYPE_MISMATCH
  ├─ 4. OOXML이면 package 내부 확인      zip bomb 상한 + word//ppt//xl/ 판별 → TYPE_MISMATCH
  ├─ 5. parse(BytesIO)                 메모리에서 파싱. 파일을 만들지 않는다
  ├─ 6. EvidenceCandidate[]            transient. 저장 대상 아님
  ├─ 7. SourceMetadata                 저장 가능한 유일한 산출물
  └─ finally: 버퍼 해제 → status = PURGED
```

**이 Harness의 intake 구현은 temp 파일을 만들지 않는다.** 8종(PDF·DOCX·PPTX·XLSX·CSV·TXT·MD·
HTML) 전부 `BytesIO`로 파싱 가능하므로 디스크에 쓸 이유가 없다. 지우지 못할 파일이 애초에
존재하지 않는 것이 cleanup을 처리하는 가장 확실한 방법이다.

그래서 `IntakeSession`에는 temp registry도 `atexit` 훅도 없다. 실제로 디스크 파일이 필요한
파서가 생기는 시점에 그때 추가한다 (Simple First).

두 개의 테스트가 이를 강제한다:

- `test_intake_leaves_no_file_in_the_temp_directory` — 8종 전부 처리 후 temp 디렉토리에 남은
  새 파일이 없음
- `test_intake_adapters_do_not_open_files` — `adapters/intake/**`를 AST 스캔해
  `open()`·`tempfile`·`shutil` 사용 금지

> **범위**: 위 두 가지는 **이 저장소의 코드**에 대한 보장이다. third-party 라이브러리 ·
> Python runtime · OS가 내부적으로 무엇을 하는지까지 통제하지 않으며, **disk write가
> 절대적으로 0이라고 주장하지 않는다.** 예를 들어 프로세스가 스왑되면 메모리 내용이 디스크에
> 남을 수 있다 (2절).

---

## 2. 메모리에 대해 보장하는 것과 보장하지 않는 것

**정확히 적는 것이 중요하다.** 과장된 보장은 그것을 믿고 설계한 사람을 위험에 빠뜨린다.

`IntakeSession`은 전달받은 `bytearray`를 `finally`에서 0으로 덮어쓴다. 이것은
**best-effort buffer clearing이며, RAM에서 원문이 제거된다는 보장이 아니다.**

보장하지 못하는 이유:

- Python의 `bytes`와 `str`은 불변이라 덮어쓸 수 없다. 참조를 버리고 GC에 맡기는 것뿐이다.
- 디코딩·파싱 과정에서 런타임과 파서 라이브러리가 내부 복사본을 만든다.
- 할당자가 해제된 페이지를 OS에 즉시 반납하지 않는다.
- 프로세스가 스왑되면 디스크에 남을 수 있다.

**이 Harness가 실제로 보장하는 Privacy 특성은 다음 세 가지다.**

1. 업로드된 원본을 **의도적으로 디스크에 영구 저장하지 않는다**
2. Intake 구현이 **temp file을 생성하지 않는 memory-first 구조다**
3. 원문을 로그에 남기지 않는다

세 가지 모두 **이 저장소의 코드 범위**에 대한 보장이며 테스트로 검증된다. 메모리 잔존과,
third-party 라이브러리 · runtime · OS의 내부 disk write는 검증 대상이 아니고 보장하지도
않는다.

---

## 3. 영구 저장 금지 목록

- 원본 PDF · DOCX · PPTX · XLSX · HTML · CSV 등 업로드 파일 전체
- Raw binary
- 문서 전체 raw text
- 원문 cache
- **업로드 파일 기반 Vector DB / Embedding**
- 원본 파일명

마지막 항목이 자주 누락된다. 파일명은 그 자체로 고객사명·프로젝트 코드·담당자명을 담는다.
그래서 `SourceMetadata`에 `filename` 필드가 없고, 스키마가 `additionalProperties: false`이고,
**파서와 `IntakeSession.ingest()` 시그니처에 filename 파라미터 자체가 없다** — 구조적으로 전달
불가능하다. `tests/test_intake.py::test_display_label_is_never_derived_from_anything`이 검사한다.

`EvidenceCandidate`는 문서 텍스트를 담으므로 **transient DTO**다. `schemas/`에 스키마가 없고,
`StorageProvider`에 저장 메서드가 없다. 메서드의 부재 자체가 통제이며
`test_storage_has_no_way_to_persist_a_candidate`가 이를 확인한다.

`.gitignore`가 `*.pdf` `*.docx` `*.pptx` `*.xlsx` `clients/` `uploads/` `tmp/` `.env`를 선제
차단한다. 커밋이 원본이 도달할 수 있는 가장 영구적인 장소다. 같은 이유로 **테스트 fixture도
커밋하지 않는다** — `tests/intake_fixtures.py`가 8종을 메모리에서 생성한다.

---

## 4. Logging — allowlist

`adapters/intake/safe_logging.py`의 `ALLOWED_LOG_FIELDS`가 전부다.

```
source_id · project_id · file_type · file_size · page_count
processing_status · error_code · ingested_at
parser · exception_type · segment_count · duration_ms
```

**deny-list가 아니라 allow-list다.** deny-list는 새 필드가 추가될 때마다 조용히 누출된다.

### `client_name`도 allowlist에 없다

공개 기업명일 수도 있고 업로드된 비공개 고객 정보일 수도 있는데, 로그에서 그 둘을 구분할 방법이
없다. Core가 추측해서 분류하는 기능은 만들지 않는다 — 출처는 `source_origin` ·
`source_category` · provenance로 유지한다.

Client discovery·analysis 단계에서 기록 가능한 것: `project_id` · `client_id` ·
`analysis_id` · `source_origin` · `source_category` · `fit_criterion` · `fit_level` ·
`priority_band` · `dimension` · `evidence_type` · `confidence` · counts · rejection code.

길이 상한을 넘긴 `reason`은 **잘라서 저장하지도, 로그에 남기지도 않는다.** 남는 것은
`REASON_TOO_LONG` 코드와 criterion 값뿐이다. 잘린 앞부분을 진단용으로 남기는 것은 문서 텍스트를
로그로 옮기는 가장 흔한 경로다.
`OrganizationMention.verbatim`(원문 조각) · `FitAssessment.reason` · `discovery_rationale`은
남기지 않는다. 전송·거부·플래그 객체는 전부 redacting `__repr__`를 정의한다.

### 보장되는 것과 노력하는 것 (Phase 5)

Deep Analysis는 이 Harness에서 가장 민감한 텍스트를 다룬다 — 누가 사고, 문제의 비용이 얼마이며,
조달이 어떻게 돌아가는가. 그래서 **구조가 보장하는 것**과 **prompt·policy가 요청할 뿐인 것**을
구분해 적는다.

| 구조적 보장 | |
|---|---|
| `contact_name` · `email` · `phone` · `person_title` 필드가 **없다** | schema `additionalProperties: false`. 그 이름으로 저장할 자리가 없다 |
| `statement` 500자 초과는 **거부**(잘라내지 않음) | 잘린 문장은 아무도 쓰지 않은 주장이다 |
| 검증 실패한 조직명은 statement까지 폐기 | 근거에 없는 조직에 대한 문장은 보여줄 수 없는 내용이다 |
| log·repr·rejection에 statement 부재 | canary 6표면 테스트 |
| 모델이 못 만드는 것 | `our_solution` · `evidence_type` · `confidence` · `source_ids` · priority — 출력 스키마에 필드가 없다 |

| prompt / policy 수준 (보장 아님) | |
|---|---|
| `BUYER` · `DECISION_MAKER` · `BUDGET_OWNER`가 역할·부서·기능일 것 | `statement`는 free text이므로 개인 실명이 들어갈 수 있다. prompt가 요구할 뿐이다 |
| 근거에 실제로 존재하는 개인명 | 저장될 수 있다. 이것은 공개 근거에 있는 정보이고, 이 Harness는 그것을 제거한다고 주장하지 않는다 |

**"개인 이름이 절대 저장되지 않는다"고 쓰지 않는다.** 실제로 보장할 수 없는 문장이다.

CRM 연결은 별도 기능이며 이 저장소는 그 경로를 제공하지 않는다.

### Proposal Strategy (Phase 6)

가장 상업적으로 민감한 텍스트다 — 고객에게 할 말, 예상되는 반론, 그에 대한 대응. 여기서의
누출은 문서 유출이 아니라 **협상 포지션이 로그 파일에 남는 일**이다.

| 구조적 보장 | |
|---|---|
| 연락처 필드 부재 | `ProposalStrategy`·`StrategyStatement`·`StoryStep`·`ProposalObjection` 어디에도 없다 |
| 제품 서술 필드 부재 | 출력 스키마에 없다. 없는 역량이 들어갈 자리가 없다 |
| 제안 문장의 출처 추적 | `solution_element_refs`(ref) → `selected_solution_elements[*].ref` → 호출자 목록. 단, 문장의 **정확성**은 보장하지 않는다 — best-effort이며 backlog 대상 |
| 가격 구조 부재 | `pricing_input` 삭제. Phase 6는 숫자를 만들지 않는다. 숫자는 Phase 7의 `CommercialInput`으로만 들어온다 |
| Phase 5 claim 원문 미복제 | dimension 참조만 저장한다 |
| 길이 초과 거부 | 잘라서 저장하지 않는다 |
| draft의 redacting `__repr__` | canary 6표면 |

| prompt / policy 수준 (보장 아님) | |
|---|---|
| `key_message`·반론·대응에 개인명이 없을 것 | free text이므로 보장하지 않는다 |

로그 가능: `strategy_id` · `analysis_id` · `client_id` · `objective` · `objective_source` ·
`step_type` · `basis` · `timing` · counts · rejection/flag code.
로그 금지: 위 모든 free text · `objective_detail` · `selected_solution_elements` 원문.

### Pricing Hand-off (Phase 7) — 유일하게 프로세스를 나가는 산출물

앞의 모든 Phase는 결과가 메모리·storage에 머문다. Phase 7은 **파일을 쓴다.** 그 파일에는
고객 원가구조가 들어 있고, 그것은 경쟁사가 돈을 주고 살 자료이자 고객이 봐서는 안 되는
자료다. 그래서 여기서는 export 표면을 따로 본다.

| 구조적 보장 | |
|---|---|
| `source_ref`·`source_type`은 불투명 식별자만 | allowlist 정규식 `^[A-Za-z0-9_-]{1,64}$`. 파일명·경로·URL·공백·점이 포함되면 `UNSAFE_SOURCE_REF`로 **거부**한다. 잘라내지 않는다 |
| 외부 스키마가 `source_ref`를 "File name, URL, or citation"으로 규정해도 따르지 않는다 | 원본 파일명은 3절 영구저장 금지목록에 있다. 계약이 허용한다는 것과 우리가 보낼 수 있다는 것은 다르다 |
| 파일명은 `<pricing_case_id>.client_input.json` | 불투명 id다. 디렉토리 목록도 표면이다 — 고객사명·제품명이 파일명에 들어가지 않는다 |
| 출력 디렉토리는 필수 인자 | 기본값이 없다. 원가표가 담긴 파일이 아무도 고르지 않은 위치에 생기지 않는다 |
| `HANDOFF_BLOCKED`는 파일을 쓰지 않는다 | 파일을 쓰는 것이 곧 전달이다. `PricingHandoffBlocked` 예외 |
| Phase 5 claim 원문 미전송 | `commercial_context`에만 남고 payload에는 가지 않는다 |
| 연락처 필드 부재 | `CommercialInput`·`PriceComponentInput`·`CostItemInput`·`CommercialSourceRef`·`PricingResult` 어디에도 없다 |
| 거부가 원인을 되풀이하지 않는다 | 파일명을 거부하면서 파일명을 기록하지 않는다 (`safe_reference`) |
| `CommercialInput` 미저장 | transient DTO다. `StorageProvider`에 저장 메서드가 없다 |
| `gap_ref`에 gap 원문 부재 | SHA-256 digest의 앞 16자다. gap 문장이 ref에 실리지 않으므로, ref는 로그·URL·API 경로에 남겨도 되는 값이다 |

| prompt / policy 수준 (보장 아님) | |
|---|---|
| `cost_item.label`·`product.name`에 문서명이 없을 것 | 호출자가 자기 원가표에 붙인 이름이며 자유 텍스트다. 검증하지 않는다 |

로그 가능: `pricing_case_id` · `strategy_id` · `analysis_id` · `client_id` · `status` ·
`component_id` · `item_id` · `gap_ref` · counts · rejection/flag code.
로그 금지: 모든 금액·요율·환율 · `product.name` · `cost_item.label` · `PricingGap.need` · `commercial_context`.

`tests/test_pricing_canary.py`가 6표면에 더해 payload 자체를 문서형 패턴(확장자·경로
구분자·URL)으로 스캔한다.

### `display_label`은 allowlist에 없다

사용자가 직접 입력한 자유 텍스트이며 고객사명을 담을 수 있다. 사용자가 보관하기로 한 레코드에
있는 것은 괜찮지만, 로그 파일에 쌓이는 것은 괜찮지 않다.
`test_display_label_is_not_in_the_logging_allowlist`가 검사한다.

### 예외 메시지를 기록하지 않는다

문서 원문이 로그에 도달하는 가장 흔한 경로다. 파서가 던지는 예외 메시지에는 그 파서를
혼란시킨 텍스트가 그대로 들어 있다.

```
ValueError: invalid literal for int() with base 10: '매출 1,240백만원'
```

`adapters/intake/guard.py`의 `parser_guard`가 모든 예외를 `IntakeError(code)`로 변환한다.
남기는 것은 **code와 예외 클래스명**(`PdfReadError`)뿐이고 메시지는 **버린다.**
`raise ... from None`도 함께 쓴다 — 이것이 없으면 원본 예외가 `__cause__`로 붙어
`traceback.format_exc()`에 메시지가 그대로 출력된다.

`UnicodeDecodeError`도 같은 이유로 전파하지 않는다. 디코드 실패는 `TEXT_DECODE_FAILED`로만
보고한다.

Core는 아예 로그를 남기지 않는다 (`test_core_purity`가 `logging` import를 금지). 무엇을
기록할지는 전적으로 App이 정한다.

---

## 5. APM · 디버거 · 에러 추적 도구 — 저장소 밖의 위험

`ExtractedDocument` · `DocumentSegment` · `EvidenceCandidate`는 텍스트를 노출하지 않는
`__repr__`를 정의한다.

```
<EvidenceCandidate evc_3f2a source=src_91b locator='p.7' kind=PARAGRAPH chars=412>
```

**이것은 보조 방어수단이다.** `repr` 재정의만으로 원문 노출이 방지된다고 주장하지 않는다.
일부 APM·디버거는 `repr`를 거치지 않고 **local variable 자체를 capture**한다.

**Production 배포 시 반드시 비활성화해야 하는 것:**

| 항목 | 이유 |
|---|---|
| request body capture | 업로드 원본이 그대로 전송된다 |
| exception locals / local variable capture | 파서 프레임의 텍스트 버퍼가 잡힌다 |
| raw payload capture | 위와 동일 |
| 프레임워크의 debug 모드 | 예외 페이지가 local 변수를 렌더링한다 |
| profiler·heap dump 자동 수집 | 메모리 내용이 그대로 나간다 |

Sentry의 경우 `with_locals=False`, `request_bodies="never"`, `send_default_pii=False`에
해당한다. 도구마다 이름이 다르므로 도입 시 개별 확인한다.

**테스트로 검증 가능한 범위는 이 저장소 내부로 한정된다** — logging · exception ·
traceback · `repr` · storage. 외부 도구의 설정은 검증할 수 없고, 그래서 여기에 적어 둔다.

---

## 6. Storage Mode 와 `display_label`

| Mode | 기본값 | 사용처 |
|---|---|---|
| `EPHEMERAL` | ✓ | Public Reference Web App. `adapters/storage/null.py` 또는 `memory.py` |
| `PERSISTENT` | | 기업·Self-host. 도입 조직이 연결한 Storage Adapter |

**Persistence 정책은 Core가 아니라 도입 조직이 결정한다.**

### `display_label` 취급

`SourceMetadata.display_label`은 **사용자가 업로드 시 직접 입력한 표시명**이다. 원본 파일명과
완전히 별개의 개념이며, 파일명에서 자동 생성되지 않는다 (구조적으로 불가능하다 — 3절 참조).

| 항목 | 처리 |
|---|---|
| 자동 생성 | **하지 않는다.** 사용자가 명시적으로 입력한 경우에만 값이 생긴다 |
| 최대 길이 | 100자 (`IntakePolicy.max_display_label_chars`). 초과 시 거부가 아니라 절단 |
| control character | 제거한다. 단어가 붙지 않도록 공백으로 치환 후 공백 축약 |
| 로그 | **남기지 않는다** (4절) |
| **PERSISTENT 모드** | **`SourceMetadata`의 일부로 저장된다.** 사용자가 고객사명을 입력하면 그 문자열이 조직 DB에 남는다 |

마지막 항목을 사용자에게 알리는 것은 도입 조직의 책임이다. 입력이 없으면 Application이
`Source 01` · `Source 02` 같은 임시 표시명을 쓸 수 있다 — 이 값은 저장하지 않는다.

`MemoryStorage`를 쓰는 장기 실행 프로세스는 세션 종료 시 `clear()`를 호출한다.

---

## 7. Canary 검증 (구현됨)

`tests/test_intake_canary.py`가 8종 각각에 고유 문자열을 심고 전체 intake를 통과시킨 뒤,
그 문자열이 **다음 6개 표면 어디에도 없음**을 검사한다.

| # | 표면 | 검사 |
|---|---|---|
| 1 | 로그 레코드 | `caplog` 전체 + allowlist 헬퍼 출력 |
| 2 | 파일시스템 | temp 디렉토리 신규 파일 0 + AST로 `open()`/`tempfile` 금지 |
| 3 | Storage | `MemoryStorage` 저장 레코드 직렬화 |
| 4 | `repr` | 모든 intake 객체 |
| 5 | **예외 · traceback** | 파서 예외를 강제 발생 → `str(exc)` + `traceback.format_exc()` |
| 6 | `SourceMetadata` | `as_dict()` 결과 |

대조군도 함께 검사한다 — canary가 **EvidenceCandidate에는 반드시 존재해야** 한다. 이것이
없으면 나머지 5개는 아무것도 증명하지 못한다.

---

## 8. Public Repository

`HARNESS.md` 9절이 원본 규칙이다. 요약하면: 실제 Client 정보 · 기업 내부자료 · 컨설팅 데이터 ·
개인정보 · API Key · Secret · 비공개 제안서 · 비공개 Master Note 전문 · 특정 조직의 Production
정보와 내부 설정은 커밋하지 않는다.

`examples/`의 데이터는 전부 가상이다. 가상임을 이름에도 표시한다 (`(가상)`, `Fictional`).

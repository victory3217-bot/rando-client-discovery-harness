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

## 4-0. SQLite Storage Adapter *(Phase 8)*

`adapters/storage/sqlite.py`는 이 저장소에서 **실제로 파일에 쓰는 유일한 adapter**다.
`PERSISTENT` 모드를 고른 조직이 쓰며, 공개 빌드의 기본값은 여전히 `null`이다 (6절).

| 구조적 보장 | |
|---|---|
| `EvidenceCandidate` 저장 메서드 부재 | Protocol에 없고 adapter에도 없다. 문서 원문을 담을 자리가 없다 |
| 문서를 담을 column 부재 | table은 `harness_entity` 하나, column은 `row_id` `entity_type` `entity_id` `project_id` `payload_json` 다섯 개뿐. 테스트가 이 목록을 정확히 검사한다 |
| 원본 파일명 column 신설 없음 | `SourceMetadata`에 filename 필드가 없으므로 payload에도 없다 |
| 에러에 SQL·경로·payload 부재 | `sqlite3` 메시지는 버리고 stable code + 예외 클래스명만 남긴다 |
| DB path는 호출자 지정 | home·cwd·temp를 고르지 않는다. 부모 디렉토리도 만들지 않는다 |
| import 부수효과 0 | 파일·디렉토리·temp 아무것도 만들지 않는다. subprocess로 검사한다 |
| DB 파일 canary | 실제 intake를 통과시킨 문서의 원문·연락처·파일명이 **DB 파일과 WAL sidecar 양쪽에** 없음을 검사한다 |

| 저장되는 것 (정상) | |
|---|---|
| Core 9 entity의 structured 내용 | `ResearchFinding.finding` 같은 해석 문장은 **저장이 목적**이다. 문서 원문이 아니다 |
| `display_label` | 사용자가 직접 입력한 경우에만 (6절) |

**구분이 핵심이다.** 사람이 남기기로 한 해석은 저장되고, 문서 원문은 저장되지 않는다. 둘 다
문자열이고, 누출인 것은 두 번째뿐이다. canary 테스트는 이 구분을 양방향으로 확인한다 —
원문 canary가 없을 것, 그리고 정상 statement는 있을 것.

**WAL 주의.** 갓 커밋된 행은 checkpoint 전까지 `<db>-wal`에 있다. DB 파일만 검사하는 점검은
잘못된 이유로 통과한다.

**한계.** SQLite는 동시 쓰기가 많은 부하에 맞지 않는다. 교육 세션 규모를 전제로 한다.

---

## 4-2. Anthropic LLM Adapter *(Phase 8)*

0절이 "추출된 텍스트는 설정된 LLM Provider로 **전송된다**"고 적어 온 그 provider가
`adapters/llm/anthropic.py`로 처음 실재하게 됐다. **이 저장소에서 네트워크로 나가는 유일한
adapter**이며, SQLite adapter와 위험의 성격이 다르다 — 저쪽은 남기면 안 되는 것을 남기는
것이고, 이쪽은 **보낸 사실과 보낸 내용이 로그·에러·파일에 남는 것**이다.

### 전송되는 것과 누출인 것은 다르다

| | |
|---|---|
| **전송 (계약대로)** | 선택된 evidence · prompt · system · JSON Schema가 요청 본문에 담겨 provider로 간다. 이것은 분석의 전제이지 사고가 아니다 (0절) |
| **누출 (있으면 안 됨)** | 같은 텍스트가 로그 · 예외 · traceback · repr · stdout/stderr · 디스크에 남는 것 |

`tests/test_llm_anthropic.py`의 canary 테스트가 **양방향으로** 확인한다 — 가상 파일명·이메일·
전화번호·문서 원문·키 형태 문자열이 위 6표면에 0이고, **동시에 요청 본문에는 반드시 존재**할
것. positive half가 없는 canary는 빈 요청을 보내는 adapter에서도 통과한다.

### 구조적 보장

| | |
|---|---|
| **logger 부재** | 이 모듈에 `logging` import도 `print`도 없다. AST로 검사한다. prompt를 로그에 안 남기는 가장 확실한 방법은 남길 곳을 두지 않는 것이다 |
| **provider 메시지 폐기** | 4xx 본문은 그것을 유발한 요청을 인용한다. stable code + HTTP status + 예외 **클래스명**만 남기고 원문은 버린다. `raise ... from None`도 함께 쓴다 |
| **schema 검증 오류에 instance 부재** | `jsonschema` 메시지는 instance(= 모델 답변, 곧 문서에서 파생된 텍스트)를 인용한다. **JSON pointer 경로만** 남기고, 경로 성분이 필드명 형태가 아니면 `<omitted>`다 |
| **API key는 헤더에만** | `repr` · `str` · 예외 · traceback · 요청 본문 · URL 어디에도 없다 |
| **env 미독** | adapter는 `os`를 import하지 않는다. 키는 Application이 읽어 생성자로 주입한다 |
| **저장 0** | cache · transcript · debug dump · temp 파일 없음. 성공 경로와 4가지 실패 경로 전부에서 temp 디렉토리와 cwd를 검사한다 |
| **import 부수효과 0** | subprocess로 검사: 파일 0 · 환경변수 읽기 0 · 소켓 0. `urllib`은 `ssl`까지 끌어오므로 transport 함수 안에서 lazy import한다 |
| **usage는 opt-in·숫자뿐** | `AnthropicUsage`는 token count · status · latency · 불투명 message id. 콜백을 주지 않으면 **메모리에도 남지 않는다.** 이 값을 담는 Entity는 만들지 않았다 |
| **재전송은 명시적** | `RetryPolicy` 기본값은 시도 1회 = 재시도 없음. 재시도는 고객 evidence를 **한 번 더 제3자에게 보내는 일**이므로 라이브러리 기본값이 정할 문제가 아니다 |
| **network 모듈 격리** | `core/`·`adapters/` 전체 AST 스캔으로 network·SDK import가 `adapters/llm/` 밖에 없음을 검사한다 |

### 보장하지 않는 것 — 정확히 적는다

- **provider의 retention · training usage · data residency를 이 코드가 보장하지 않는다.**
  "zero retention" · "저장하지 않는다" 같은 문장을 코드에도 이 문서에도 쓰지 않는다. 0절의
  확인 항목표가 그대로 적용되며, 배포 조직이 **provider별로 직접 확인**한다.
- **timeout은 전체 deadline이 아니다.** `urlopen`의 `timeout`은 connect와 각 read 등 socket
  연산 단위로 걸린다. 바이트를 조금씩 흘려보내는 서버는 총 소요시간에서 이를 넘길 수 있다.
  전체 deadline이 필요하면 그것을 강제하는 transport를 주입한다.
- **모델 선택의 결과를 normalize하지 않는다.** 어떤 모델을 주느냐에 따라 provider-native
  thinking 동작 · 지연 · token usage · **비용**이 달라진다. adapter는 sampling control
  (`temperature`·`top_p`·`top_k`)도 `thinking`도 **보내지 않으며**, 이것은 누락이 아니라
  정책이다 — sampling semantics는 provider·모델마다 다르고 일부는 제약하거나 거부한다.
  요청 본문은 `model`·`max_tokens`·`system`·`messages` **4개로 닫혀 있고**, 그 4개 외의
  생성 파라미터가 adapter 판단으로 추가되는 경로가 없다.
- **`max_tokens`는 generation policy이며 adapter의 숨은 기본값이 아니다.** `api_key`·`model`과
  같이 **필수 인자**이고 기본값이 없다. Application Layer가 배포·용도에 맞는 budget을 고르고
  adapter에 명시적으로 전달한다 — model 이름에서 추론하지 않고, prompt 길이에서 계산하지 않고,
  per-model ceiling을 **normalize하거나 추정하지 않는다**. 상한에 닿은 응답은
  `LLM_RESPONSE_TRUNCATED`로 **거부**하며, 그 호출도 과금되었으므로 usage는 그대로 기록된다.
- **third-party·runtime·OS 내부 동작은 검증 대상이 아니다** (2절과 같은 범위 제한).
- **실제 provider 왕복은 NOT_MEASURED다.** live 테스트는 `HARNESS_LLM_LIVE_TEST=1` ·
  `HARNESS_LLM_LIVE_API_KEY` · `HARNESS_LLM_LIVE_MODEL` **세 개가 함께** 있을 때만 돈다.
  `ANTHROPIC_API_KEY`가 환경에 있다는 것은 그것을 쓰겠다는 동의가 아니므로 게이트가 아니다.
  기본 test suite는 네트워크 없이 실행된다.

로그 가능: `provider` · `model` · `status` · `latency_ms` · `attempts` · `input_tokens` ·
`output_tokens` · `message_id` · `stop_reason` · error code.
로그 금지: prompt · system prompt · evidence · 응답 원문 · JSON Schema · API key ·
provider 에러 메시지.

---

## 4-3. Brave Search Adapter *(Phase 8)*

`adapters/search/brave.py`는 **두 번째로 네트워크로 나가는 adapter**이고, 나가는 것의 성격이
LLM adapter와 다르다. 저쪽이 보내는 것은 **고객이 준 문서**이고, 이쪽이 보내는 것은
**무엇을 찾고 있는지**다 — query는 대상 산업·국가·문제·때로는 조직명을 그대로 담는다.
`"가상수처리공사 노후 설비 교체 2026"` 한 줄은 문서 한 장만큼 말해 준다.

그리고 **evidence trail이 여기서 시작한다.** 그래서 이 절에는 다른 adapter에 없는 항목이
하나 더 있다: *아무도 말하지 않은 것이 provenance로 기록되지 않을 것*.

### 전송되는 것과 누출인 것은 다르다

| | |
|---|---|
| **전송 (계약대로)** | query 문자열과 `country` 코드가 provider로 간다. 그것이 검색이다 (0절) |
| **누출 (있으면 안 됨)** | 같은 query, 결과 snippet, URL, publisher가 로그 · 예외 · traceback · repr · stdout/stderr · 디스크에 남는 것 |

`tests/test_search_brave.py`의 canary 테스트가 **양방향으로** 확인한다 — 가상 query·조직명·
파일명·이메일·전화번호·snippet·키 형태 문자열이 위 표면에 0이고, **동시에 요청에는 query가
반드시 존재**할 것. positive half가 없는 canary는 빈 query를 보내는 adapter에서도 통과한다.

### 구조적 보장

| | |
|---|---|
| **logger 부재** | 이 모듈에 `logging` import도 `print`도 없다. AST로 검사한다 |
| **query는 숫자로만 관측된다** | `BraveSearchUsage`에 query 문자열 자리가 없다. `query_chars`(길이)뿐이며, `TransmissionRecord.char_count`와 같은 방식이다 |
| **URL·snippet·publisher는 usage에 없다** | 결과에 대해 나가는 것은 `returned_count` · `mapped_count` · `rejected_count`뿐이다 |
| **provider 메시지 폐기** | 422 본문은 그것을 유발한 **query를 인용한다.** stable code + HTTP status + 예외 **클래스명**만 남기고 `raise ... from None`을 함께 쓴다 |
| **API key는 헤더에만** | `repr` · `str` · 예외 · traceback · URL · 파라미터 어디에도 없다 |
| **env 미독** | adapter는 `os`를 import하지 않는다. 키는 Application이 읽어 생성자로 주입한다 |
| **저장 0** | cache · transcript · temp 파일 없음. 성공 경로와 4가지 실패 경로 전부에서 temp 디렉토리와 cwd를 검사한다. 같은 query를 두 번 부르면 요청도 두 번 나간다 |
| **import 부수효과 0** | subprocess로 검사: 파일 0 · 환경변수 읽기 0 · 소켓 0. `urllib`은 `ssl`까지 끌어오므로 transport 함수 안에서 lazy import한다 |
| **이 머신의 위치를 보내지 않음** | `x-loc-lat` · `x-loc-city` · `x-loc-timezone` · `x-loc-country` · `search_lang` · `ui_lang` 전부 미전송. `locale` module을 import하지 않는다 |
| **재전송은 명시적** | `RetryPolicy` 기본값은 시도 1회. 재시도는 query를 **한 번 더 제3자에게 보내는 일**이다 |
| **network 모듈 격리** | `core/`·`adapters/` 전체 AST 스캔으로, network import가 있는 파일이 **이름으로 열거된 2개**(`llm/anthropic.py` · `search/brave.py`)뿐임을 검사한다 |

### provenance에 대한 보장 — 이 adapter에만 있는 항목

| | |
|---|---|
| **`published_date`를 만들지 않는다** | provider의 날짜 필드는 "published **or last modified**"로 정의되어 있다. publication date가 아니므로 기록하지 않는다. snippet의 연도·URL 경로·검색 시각에서 **추론하지 않는다** |
| **`retrieved_at` ≠ `published_at`** | 검색 시각은 adapter가 말할 자격이 있는 유일한 사실이고 채운다. 5년 된 페이지를 오늘 읽은 것은 **오래된 자료의 최근 retrieval**이지 최근 자료가 아니다 |
| **publisher를 유도하지 않는다** | hostname에서 만들지 않고, 200자를 넘으면 자르지 않고 **버린다.** 부재는 confidence를 제한할 뿐이며 그것은 동작하는 답이다 |
| **URL을 고쳐 쓰지 않는다** | tracking 파라미터 제거 · host 정규화 · redirect 해제 전부 하지 않는다. 검사만 한다 |
| **snippet은 engine의 발췌다** | adapter가 URL을 따라가 본문을 가져오지 않는다. locator는 `snippet`이고 ceiling은 MEDIUM이다 — `tests/test_search_contract.py`가 manual·brave 양쪽에서 확인한다 |
| **AI 생성물이 retrieval로 섞이지 않는다** | `summary`·`enable_rich_callback`을 켜지 않고 `result_filter=web`으로 요청하므로 summarizer·infobox 블록이 응답에 **오지 않는다** |
| **query를 바꾸지 않는다** | provider 기본값인 `spellcheck`(수정된 query로 검색)와 `operators`(구두점을 문법으로 해석)를 **끈다.** keyword 확장 · site 필터 · 지역 자동 추가 없음 |

### 보장하지 않는 것 — 정확히 적는다

- **provider가 query를 어떻게 다루는지 이 코드가 보장하지 않는다.** 검색어 보관 · 로그 ·
  익명화 · 재판매 여부는 배포의 속성이다. "저장하지 않는다" 같은 문장을 코드에도 이 문서에도
  쓰지 않는다. 0절의 확인 항목표가 그대로 적용되며, 배포 조직이 **직접 확인**한다.
- **query는 문서보다 짧을 뿐 덜 민감하지 않다.** 조직명이 들어간 query를 외부 검색 API로
  보내는 것은 그 조직을 조사 중이라는 사실을 제3자에게 알리는 일이다. `ManualSearch`가 여전히
  기본값인 이유이고, 외부 검색이 허용되지 않는 환경에서 Harness가 계속 동작하는 이유다.
- **timeout은 전체 deadline이 아니다.** `urlopen`의 `timeout`은 socket 연산 단위다.
- **index coverage·결과 품질·순위 근거를 주장하지 않는다.** provider의 결과 순서는 search
  ranking이며 `sales_priority`와 무관하다.
- **third-party·runtime·OS 내부 동작은 검증 대상이 아니다** (2절과 같은 범위 제한).
- **실제 provider 왕복은 NOT_MEASURED다.** live 테스트는 `HARNESS_SEARCH_LIVE_TEST=1` ·
  `HARNESS_SEARCH_LIVE_API_KEY` **두 개가 함께** 있을 때만 돈다. `BRAVE_API_KEY`가 환경에
  있다는 것은 그것을 쓰겠다는 동의가 아니므로 게이트가 아니다. 기본 test suite는 네트워크
  없이 실행된다.

로그 가능: `provider` · `status` · `latency_ms` · `attempts` · `limit` · `returned_count` ·
`mapped_count` · `rejected_count` · `query_chars` · `country` · error code.
로그 금지: query 원문 · snippet · 결과 URL · publisher · API key · provider 에러 메시지.

---

## 4-1. Web Application 표면 *(Phase 8)*

Phase 1–7의 원칙은 그대로다. Web에서 처음 생기는 표면만 여기 적는다. 이 절은 **별도
Application 저장소가 지켜야 할 요구사항**이며, 이 저장소의 코드가 아니다.

| 표면 | 규칙 |
|---|---|
| upload lifetime | 메모리 파싱, 디스크 미기록. 요청 종료 시 버퍼 해제 |
| `EvidenceCandidate` | **어떤 mode에서도 저장하지 않는다.** Bootstrap Run 종료와 함께 소멸 |
| session lifetime | 서명 쿠키 · `HttpOnly` · `Secure` · `SameSite=Lax`. 세션 종료 + N시간 후 데이터 삭제 |
| browser storage | 분석 내용 저장 금지. UI 선호(언어·접힘 상태)만 |
| server logs | allowlist: `request_id` `project_id` `session_id` `step` `status` `latency_ms` `error_code` `source_id` `gap_ref` `pricing_case_id` |
| error reporting | request body capture · locals capture · raw payload capture **전부 끈다** (5절) |
| analytics | 페이지뷰 수준만. 입력 내용·업로드·프롬프트 전송 금지 |
| crash reporting | 스택만, 변수 없이 |
| cache · CDN | 분석 결과 응답은 `no-store`. 정적 자산만 CDN |
| API traces | span 이름과 코드만. 인자 값 금지 |
| 교육생 식별 | 익명 participant id. **이름·이메일·전화번호를 받지 않는다** |
| 강사 화면 | 개별 교육생의 raw input을 기본 노출하지 않는다. 집계만 |
| LLM 전송 | zero-retention이라고 **과장하지 않는다.** 전송 고지를 화면에 노출 |
| sample data | 공개 데모·seed는 전부 가상 (`HARNESS.md` 9절) |

저장되는 것은 **해석 결과와 그 출처 id**뿐이다 — Finding · SWOT · KeyIssue ·
ClientCandidate · ClientAnalysis · ProposalStrategy · PricingResult. 원본 문서는 어느
mode에서도 남지 않으며, 그래서 STEP 1–7을 재개하려면 자료를 다시 올려야 한다. 이 제약은
비용이 아니라 privacy 보장의 결과다.

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

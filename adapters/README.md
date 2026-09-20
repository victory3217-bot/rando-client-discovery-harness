# adapters — 새 Adapter 추가 방법

이 디렉토리가 **유일한 통합 지점**이다. 자체 Database · 자체 방법론 · 다른 LLM · 자체 검색을
붙이려면 여기에 모듈 하나를 추가한다. `core/`는 수정하지 않는다.

## 규칙 3개

1. **import 방향은 한 방향이다.** Adapter는 `core`를 import하지만, `core`는 절대 Adapter를
   import하지 않는다. `tests/test_core_purity.py`가 이를 검사한다.
2. **상속하지 않는다.** Interface는 `typing.Protocol`이므로 base class를 상속할 필요가 없다.
   메서드 시그니처만 맞으면 된다. 그래서 조직 코드가 이 저장소에 묶이지 않는다.
3. **`name` 속성을 둔다.** 로그에 남겨도 안전한 짧은 식별자다 (`"null"`, `"memory"`, `"echo"`).

## 예: 자체 Database 연결

```python
# my_org/storage.py — 이 저장소 밖에 두어도 된다
from core.models import Project, ResearchFinding   # 타입만 가져온다

class MyOrgStorage:
    name = "myorg"

    def save_project(self, project: Project) -> str: ...
    def get_project(self, project_id: str): ...
    def save_finding(self, finding: ResearchFinding) -> str: ...
    def get_findings(self, project_id: str) -> list[ResearchFinding]: ...
    # ... core/interfaces/storage.py 의 나머지 메서드
```

조립:

```python
from core.harness import create_harness

harness = create_harness(
    storage=MyOrgStorage(),      # 여기만 바꾼다
    knowledge=StaticKnowledge.from_directory("knowledge/master-notes"),
    llm=EchoLLM(),
    search=ManualSearch(),
)
```

구현이 맞는지 확인하려면:

```python
from core.interfaces import StorageProvider
assert isinstance(MyOrgStorage(), StorageProvider)   # 런타임 구조 검사
```

`runtime_checkable` Protocol의 `isinstance`는 **메서드 존재만** 확인하고 시그니처는 보지
않는다. 실제 검증은 `tests/test_adapters.py`처럼 계약 테스트로 한다.

## 현재 Adapter

| 모듈 | Interface | 설명 |
|---|---|---|
| `storage/null.py` | Storage | 기본값. 전부 폐기 (EPHEMERAL 모드) |
| `storage/memory.py` | Storage | 프로세스 메모리. 세션 내 단계 연결 |
| `storage/sqlite.py` | Storage | **파일 저장.** Core 9 entity만. 경로는 호출자가 준다 — 아래 |
| `knowledge/static.py` | Knowledge | `knowledge/master-notes/*.json` 로드 |
| `knowledge/handbook.py` | Knowledge | handbook 경로 주입. 다른 provider를 감싼다 |
| `llm/echo.py` | LLM | 오프라인·결정적. API 키 불필요 |
| `llm/anthropic.py` | LLM | **첫 production provider.** Messages API. 키·모델은 호출자가 준다 — 아래 |
| `search/manual.py` | Search | 사용자가 제공한 자료만 반환 |
| `intake/text.py` | DocumentParser | TXT · MD · CSV. stdlib만 |
| `intake/html.py` | DocumentParser | stdlib `html.parser`. script·style·noscript·주석 제외 |
| `intake/pdf.py` | DocumentParser | pypdf. 텍스트 레이어만 (OCR 없음) |
| `intake/office.py` | DocumentParser | DOCX · PPTX · XLSX. package 내부로 타입 판별 |
| `intake/session.py` | — | request 수명 · batch 상한 · 버퍼 해제 |
| `intake/safe_logging.py` | — | 로그 allowlist |
| `prompts/loader.py` | — | `prompts/**/*.md` 로딩 (research + discovery). core는 파일을 읽지 않으므로 여기서 읽어 주입한다 |
| `pricing/file.py` | — | Pricing Harness와 JSON 파일 교환. provider가 아니다 — 아래 |

### SQLite storage adapter

이 저장소에서 **실제로 무언가를 보관하는 유일한 adapter**다. 그래서 가장 조심해야 한다 —
여기서의 버그는 데이터를 잃는 것이 아니라 **남기면 안 되는 것을 남긴다.**

```python
from adapters.storage.sqlite import SQLiteStorage

storage = SQLiteStorage("/var/lib/harness/harness.sqlite3")   # 경로 필수, 기본값 없음
```

| 결정 | 이유 |
|---|---|
| **table 1개 + payload JSON** | Core dataclass를 column으로 다시 모델링하지 않는다. 그러면 `core/models.py`의 세 번째 사본이 되고, 그 사본만 `test_schemas.py` 같은 정합성 검사가 없다 |
| **직렬화는 `as_dict`/`from_dict`** | 별도 encoder도 수동 enum 변환도 없다. MemoryStorage와 같은 Core 타입이 복원된다 |
| **append, project만 replace** | MemoryStorage의 의미를 **복제한 것이지 고른 것이 아니다.** 같은 finding을 두 번 저장하면 두 번 쌓인다 |
| **insertion order** | 역시 MemoryStorage와 맞춘 것. `row_id` 순서다 |
| **경로 기본값 없음** | 고객 분석이 담긴 파일의 위치는 배포 결정이다. home·cwd·temp를 adapter가 고르지 않는다 |
| **부모 디렉토리 생성 안 함** | 없으면 `STORAGE_PATH_UNAVAILABLE`. 디렉토리를 만드는 adapter는 아무도 안 본 곳에 쓴다 |
| **operation당 connection** | background thread가 쓰고 request thread가 읽는 구조라, connection 공유는 production에서만 터진다 |
| **WAL** | 쓰는 중에도 읽을 수 있다. `-wal`·`-shm` 파일은 **사용의** 정상 결과다 (import의 결과가 아니다) |
| **`PRAGMA user_version`** | 모르는 schema version은 조용히 읽지 않고 `STORAGE_SCHEMA_VERSION_UNSUPPORTED`로 멈춘다. migration framework는 없다 |
| **`clear()` 없음** | MemoryStorage의 `clear()`는 ephemeral 세션 종료용이다. 영속 adapter에서 같은 이름의 전체 삭제는 함정이다 |

저장하지 않는 것: `EvidenceCandidate` · 원본 문서 · 문서 전문 · prompt · LLM 원문 응답 ·
training session · participant · HTTP session · BootstrapRun. 마지막 네 개는 **Application
저장소의 책임**이고, 같은 SQLite 파일을 쓰더라도 table을 공유하지 않는다.

에러는 `SQLiteStorageError`로 감싼다. `sqlite3` 메시지는 SQL과 값을 인용하므로 **버리고**,
stable code와 원래 예외의 **클래스명만** 남긴다 (`IntakeError`와 같은 규칙).

한계: SQLite는 동시 쓰기가 많은 부하에 맞지 않는다. 교육 세션 규모를 전제로 하며, 그 이상이
필요하면 같은 Protocol의 다른 구현체로 바꾼다 — Database Agnostic 원칙이 그것을 위해 있다.

### Anthropic LLM adapter

`adapters/llm/anthropic.py`는 이 저장소에서 **실제로 네트워크로 나가는 유일한 adapter**다.
SQLite adapter가 "남기면 안 되는 것을 남기는" 위험이라면, 이쪽은 **"보내면 안 되는 것을
보내고, 보낸 사실이 로그에 남는"** 위험이다.

```python
from adapters.llm.anthropic import AnthropicLLM, RetryPolicy

llm = AnthropicLLM(
    api_key=os.environ["..."],      # Application이 읽어서 주입한다. adapter는 env를 안 읽는다
    model="...",                     # 호출자가 명시. 기본값 없음
    max_tokens=...,                  # 호출자가 명시. 기본값 없음 — Application이 고른다
    timeout_seconds=60.0,            # socket 연산 단위. 전체 deadline이 아니다
    retry=RetryPolicy(max_attempts=1),   # 기본값이 이미 이것이다 — 재시도 안 함
)
# temperature·top_p·top_k·thinking은 인자로 존재하지 않는다 (아래 표)
```

| 결정 | 이유 |
|---|---|
| **api_key·model·max_tokens 기본값 없음** | env를 adapter가 읽으면 다른 작업에서 남은 키로 과금된다. 모델을 adapter가 고르면 기본값이 바뀌는 날 **분석 내용이 조용히 달라진다**. 셋 다 필수 keyword 인자다 |
| **생성자에서 키 검증, 네트워크는 호출 시에만** | 자격증명 부재를 evidence 배치가 끝난 뒤에 발견하면 비용이 든 부분을 버린다 |
| **공식 SDK 대신 stdlib `urllib`** | SDK는 13개 패키지(컴파일 확장 2개 포함)를 끌어오고, **기본 `max_retries`가 0이 아니다.** 이 Harness에서 재시도는 고객 evidence 재전송이므로 라이브러리 기본값이 정할 일이 아니다. Messages 호출은 POST 하나다 |
| **transport 주입 가능** | 오프라인 테스트가 요청 구성·retry·timeout·error mapping·추출을 전부 실행할 수 있다. SDK·Bedrock·Vertex를 쓰고 싶은 조직은 여기에 꽂는다 |
| **retry 기본 = 1회 시도 (재시도 없음)** | 재시도는 privacy·비용·지연을 바꾼다. `RetryPolicy`로 **명시적으로** 켠다. auth·invalid request·schema 실패는 애초에 재시도 대상이 아니다 |
| **timeout은 socket 연산 단위** | `urlopen`의 `timeout`은 connect와 각 read에 걸리며 **전체 deadline이 아니다.** 보장하지 못하는 것을 보장한다고 쓰지 않는다. 전체 deadline이 필요하면 그런 transport를 주입한다 |
| **prompt 재작성 없음** | adapter가 더하는 문장은 module 상수 4개가 전부이고, 테스트가 **그 집합과 정확히 일치**하는지 검사한다. 열거할 수 없는 envelope은 hidden system prompt와 구분되지 않는다 |
| **instruction은 system, data는 user** | core의 `system`·`prompt`는 각 블록의 **맨 앞에 원문 그대로** 간다. evidence·schema는 데이터이므로 user 블록이다 |
| **로그 없음** | 이 모듈에 logger가 없다. prompt를 로그에 안 남기는 가장 싼 방법은 남길 곳을 안 두는 것이다. usage는 opt-in callback으로만 나가고 **숫자·식별자뿐**이다 |
| **저장 없음** | cache·transcript·debug dump·temp 파일 0. 성공·실패 경로 모두에서 검사한다 |
| **provider 메시지 폐기** | 4xx 본문은 그것을 유발한 요청을 인용한다. stable code + HTTP status + 예외 **클래스명**만 남긴다 (`IntakeError`·`SQLiteStorageError`와 같은 규칙) |
| **schema 검증 생략 안 함** | `jsonschema`가 없으면 `LLM_SCHEMA_VALIDATOR_UNAVAILABLE`로 멈춘다. 검증하지 않은 것을 통과로 표현하지 않는다 |
| **max_tokens는 generation policy다** | **adapter의 숨은 기본값이 아니다.** 답변 하나에 토큰을 얼마까지 쓸지는 배포가 무엇을 위한 것이고 얼마를 쓸 의향이 있는지에서 나온다 — 즉 policy이고, **policy 선택은 Application Layer의 일이지 transport의 일이 아니다.** 기본값을 두면 adapter가 잊어버린 모든 배포를 대신 결정하게 된다 |
| **budget을 고르지도 추론하지도 않는다** | model 이름에서도, prompt 길이에서도, provider별 heuristic에서도 계산하지 않는다. 받은 값을 그대로 body에 넣는다. `_body`에는 **call node가 0개**이고 `_max_tokens`는 **단 한 번** 대입된다 (AST 테스트) |
| **model별 token ceiling 미보유** | 상한을 하드코딩하지 않는다. adapter는 특정 모델의 한도를 **안다고 가정하지 않으며**, 안다고 가정하면 한도가 바뀌는 날 유효한 값을 거부한다. provider가 거부하면 `LLM_INVALID_REQUEST`로 온다 — 실제로 아는 쪽이 답한다 |
| **입력 검증은 최소한만** | `bool` 거부(`bool`은 `int`다 — `max_tokens=True`면 body에 `true`가 들어간다) · `int`만 허용 · `> 0`. 강제 변환하지 않는다: `int("4096")`·`int(4096.9)`는 둘 다 성공하고 둘 다 호출자가 보낸 줄 알았던 값이 아니다 |
| **sampling control 미설정** | `temperature`·`top_p`·`top_k`를 **보내지 않는다.** 빠뜨린 것이 아니라 의도적이다 — sampling semantics는 provider마다 다르고 한 provider 안에서도 모델마다 다르며, 일부 모델은 제약하거나 거부한다. 값을 보내는 adapter는 모든 분석 단계의 sampling 정책을 대신 고르는 것이고, provider 간에 번역하는 adapter는 그 값들이 같은 뜻이라고 주장하는 것이다. **둘 다 transport의 일이 아니다** |
| **thinking 자동 on/off 없음** | 켜지도 끄지도 않는다. 모델이 답 전에 추론하는지, 그것이 지연·토큰·비용에서 얼마인지는 **호출자가 고른 모델의 속성**이다. 여기서 강제하면 provider-native behavior가 Harness 정책이 된다 |
| **streaming·tool calling 없음** | `HARNESS.md` 10절이 Phase 1–8에서 제외한다 |
| **요청 본문은 닫힌 집합** | `REQUEST_BODY_KEYS` = `model`·`max_tokens`·`system`·`messages` **4개가 전부**이고, 그 4개 모두 호출자가 준 값이거나 core가 준 텍스트다. 보내면 안 되는 것의 목록이 아니라 보내는 것의 목록이다 — denylist는 API에 필드가 생길 때마다 조용히 샌다 (`docs/privacy.md` 4절 logging allowlist와 같은 이유). 4개 메서드 각각에 대해 테스트가 **정확히 일치**를 검사한다 |

**동기(sync)이며 호출 스레드를 왕복 내내 막는다.** `LLMProvider`는 동기 Protocol이고 adapter
편의로 바꾸지 않는다 — 기다림은 Phase 8 Application의 background thread가 맡는다.

**instance 공유**: 설정만 들고 있고 호출마다 요청을 새로 만들므로 여러 스레드에서 써도 된다.
단 이것은 이 구현에 대한 진술이지 주입된 transport나 `usage_sink`에 대한 보장이 아니다.

**실제 provider 테스트는 opt-in이다.** `HARNESS_LLM_LIVE_TEST=1` · `HARNESS_LLM_LIVE_API_KEY` ·
`HARNESS_LLM_LIVE_MODEL` **세 개가 함께** 있어야 실행된다. `ANTHROPIC_API_KEY`가 환경에 있다는
것은 그것을 쓰겠다는 동의가 아니므로 게이트로 쓰지 않는다. 셋이 없으면 **NOT_RUN**이다.

**모델 선택의 결과는 normalize하지 않는다.** 어떤 모델을 주느냐에 따라 provider-native
thinking 동작 · 지연 · token usage · 비용이 달라진다. adapter는 이것을 평탄화하지 않으며,
평탄화한 척도 하지 않는다. 모델은 호출자가 고르고 그 결과도 호출자의 것이다.

**과장하지 않는 것**: retention · training usage · data residency는 배포의 속성이지 이 코드의
속성이 아니다. 이 adapter는 provider가 받은 데이터를 어떻게 다루는지 **주장하지 않는다**
(`docs/privacy.md` 0절).

### Pricing adapter는 provider가 아니다

`create_harness()`는 그대로 provider 4개를 받는다. Core는 Pricing Harness를 **호출하지
않기** 때문이다 — payload를 조립하고 멈춘다. 파일을 어디에 쓸지는 그 디렉토리를 소유하는
Application Layer가 정하므로, `FilePricingBridge`는 거기서 직접 조립한다.

```python
from adapters.pricing.file import FilePricingBridge

bridge = FilePricingBridge.from_repository("../pricing-harness-public")  # 경로는 선택
path = bridge.write_payload(result, export_dir)     # HANDOFF_BLOCKED면 거부한다
answer = bridge.read_engine_result(result_path)
```

지켜야 할 것 3가지:

1. **Pricing Harness의 Python을 import하지 않는다.** 두 저장소 모두 top-level 패키지명이
   `core`라 같은 프로세스에서 충돌한다. 스키마 *파일*을 읽는 것은 무방하다.
2. **출력 디렉토리에 기본값을 두지 않는다.** 원가표가 담긴 파일이 아무도 고르지 않은 위치에
   생기지 않는다.
3. **검사하지 않은 것을 통과로 표현하지 않는다.** 외부 스키마 경로가 없으면
   `ExternalValidation(checked=False, code="EXTERNAL_CONTRACT_NOT_CHECKED")`다.

### Intake adapter를 추가할 때

`DocumentParser`는 harness provider가 아니다 — `create_harness()`에 넣지 않고
`adapters/intake/registry.py`에 등록한다.

```python
class MyFormatParser:
    name = "myformat"
    supported_types = frozenset({FileType.TXT})
    def parse(self, data: bytes, *, file_type: FileType) -> ExtractedDocument: ...
```

지켜야 할 것 4가지:

1. **`filename` 파라미터를 만들지 않는다.** 원본 파일명이 유입될 경로 자체를 두지 않는다.
2. **파일을 직접 만들거나 열지 않는다.** `BytesIO`로 처리한다. `tests/test_intake_canary.py`가
   `adapters/intake/**`의 `open()`·`tempfile`·`shutil` 사용을 AST로 금지한다. (라이브러리·런타임
   내부 동작까지 통제하는 것은 아니다 — `docs/privacy.md` 1절.)
3. **라이브러리 예외를 그대로 올리지 않는다.** `parser_guard`로 감싸 `IntakeError(code)`로
   변환한다 — 예외 메시지에 문서 원문이 들어 있다.
4. **라이브러리를 lazy import한다.** 미설치 시 `PARSER_UNAVAILABLE`이지 startup crash가 아니다.

## Phase별 예정

| Phase | Adapter |
|---|---|
| 8 | `llm/openai.py` · `llm/google.py` · `search/web.py` (`llm/anthropic.py`는 **완료**) |
| 9 | `reporting/html.py` · `reporting/docx.py` |

## 주의

- **Secret을 Adapter 코드에 쓰지 않는다.** 환경변수를 읽는 것은 Application 레이어의 일이고,
  Adapter는 생성자로 주입받는다.
- **원문을 로그에 남기지 않는다.** `docs/privacy.md`의 allowlist를 따른다.
- **특정 조직의 정보를 이 Public 저장소에 커밋하지 않는다.** 금지 목록은 `HARNESS.md` 9절에
  있다.

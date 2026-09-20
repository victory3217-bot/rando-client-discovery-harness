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
| 3 | `llm/anthropic.py` · `llm/openai.py` · `llm/google.py` · `search/web.py` |
| 9 | `reporting/html.py` · `reporting/docx.py` |

## 주의

- **Secret을 Adapter 코드에 쓰지 않는다.** 환경변수를 읽는 것은 Application 레이어의 일이고,
  Adapter는 생성자로 주입받는다.
- **원문을 로그에 남기지 않는다.** `docs/privacy.md`의 allowlist를 따른다.
- **특정 조직의 정보를 이 Public 저장소에 커밋하지 않는다.** 금지 목록은 `HARNESS.md` 9절에
  있다.

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
| 7 | `pricing/file.py` — Pricing Harness와 JSON 파일 계약 |
| 8 | `storage/sqlite.py` |
| 9 | `reporting/html.py` · `reporting/docx.py` |

## 주의

- **Secret을 Adapter 코드에 쓰지 않는다.** 환경변수를 읽는 것은 Application 레이어의 일이고,
  Adapter는 생성자로 주입받는다.
- **원문을 로그에 남기지 않는다.** `docs/privacy.md`의 allowlist를 따른다.
- **특정 조직의 정보를 이 Public 저장소에 커밋하지 않는다.** 금지 목록은 `HARNESS.md` 9절에
  있다.

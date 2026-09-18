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

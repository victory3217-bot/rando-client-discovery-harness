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
| `search/brave.py` | Search | **첫 production Search provider.** Web Search API. 키는 호출자가 준다 — 아래 |
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

### Brave Search adapter

`adapters/search/brave.py`는 `manual`이 아닌 **실제 외부 색인을 읽는 첫 Search adapter**다.
SQLite가 "남기면 안 되는 것을 남기는" 위험, Anthropic adapter가 "보낸 것이 로그에 남는" 위험이면,
이쪽은 **"아무도 말하지 않은 것이 provenance로 기록되는"** 위험이다. Evidence trail이 여기서
시작하기 때문이다.

```python
from adapters.search.brave import BraveSearch, RetryPolicy

search = BraveSearch(
    api_key=os.environ["..."],   # Application이 읽어서 주입한다. adapter는 env를 안 읽는다
    timeout_seconds=30.0,        # socket 연산 단위. 전체 deadline이 아니다
    retry=RetryPolicy(max_attempts=1),   # 기본값이 이것이다 — 재시도 안 함. 아래 경고를 읽을 것
    api_version=None,            # 선택. 주면 응답 계약이 그 날짜로 고정된다
)
```

**새 abstraction을 만들지 않았다.** 기존 `SearchProvider` Protocol을 그대로 구현하고,
`SearchResult`에 필드를 하나도 더하지 않았다. `create_harness()`의 `search=` 자리에 `ManualSearch`
대신 넣으면 끝이고, `tests/test_search_contract.py`가 그 교체 가능성을 두 adapter에 **같이**
돌려서 확인한다.

| 결정 | 이유 |
|---|---|
| **provider = Brave Web Search** | 이 contract가 요구하는 provenance 필드를 **파생이 아니라 필드로** 주는 쪽을 골랐다: `title` · `url`(목적지 주소, redirect wrapper 아님) · `description`(engine 발췌) · `profile.name`(publisher에 가장 가까운 것). `publisher` 부재가 confidence를 제한한다고 contract가 적고 있으므로 이 필드의 유무가 실제로 중요하다. 유명해서가 아니다 |
| **`web/search` endpoint. LLM Context endpoint 아님** | 같은 provider의 "machine consumption용" endpoint는 페이지 본문을 가공해 돌려준다. 그것을 snippet이라 부르며 넣으면, Harness는 **읽지 않은 페이지의 본문**을 읽지 않았다고 기록하게 된다 |
| **`spellcheck=false`** | provider 기본값이 `true`이고, 문서가 "spell checker가 켜져 있으면 **수정된 query가 항상 검색에 사용된다**"고 적는다. 수정된 query는 다른 query이고, core는 바뀐 줄도 모른다 |
| **`operators=false`** | 기본값 `true`는 query의 `-`·`site:`·따옴표를 **문법으로** 읽는다. core가 주는 것은 criteria에서 생성된 자연어 검색어지 검색 문법이 아니다. `IoT-기반`의 하이픈이 조용히 제외 연산자가 된다 |
| **`text_decorations=false`** | 기본값은 일치한 단어를 강조 markup으로 감싼다. 그 markup은 문서의 것이 아니라 engine의 것이고, `EvidenceCandidate` 안으로 들어가 **조직명을 태그 경계로 쪼갠다** — `core/client/discover.py`의 토큰 경계 검사가 바로 그것을 본다 |
| **`result_filter=web`** | 읽는 것이 web 결과뿐이므로 web 결과만 요청한다. summarizer·infobox·location 블록이 응답에 아예 오지 않는다 — **AI가 생성한 것이 retrieval로 오인될 경로를 없앤다** |
| **`summary`·`enable_rich_callback`·`extra_snippets` 미사용** | 앞의 둘은 생성된 텍스트를 켜고, `extra_snippets`는 한 페이지에서 발췌를 더 가져오는 것이라 **페이지를 읽는 쪽에 가까워진다.** 이 adapter가 넘지 않는 선이다 |
| **`freshness`·`goggles`·`safesearch` 미전송** | 날짜 창과 재정렬은 **research policy**다. contract에 인자가 없으므로, 보내는 adapter는 무엇이 관련 있는지를 core 대신 고르는 것이다 |
| **`x-loc-*` 헤더 미전송** | 이 머신의 위도·도시·timezone·국가다. 절대 보내지 않는다 — `country` 인자가 없을 때 지역을 암묵적으로 고르는 바로 그 행위다 |
| **`published_date`를 채우지 않는다** | **이 파일에서 가장 중요한 한 줄이다.** 이 endpoint의 날짜 필드(`page_age`)는 문서가 "published **or last modified** date"라고 정의한다. 그것은 publication date가 아니다. 발행 6년 된 페이지가 지난달에 수정됐다는 이유로 기록상 최신처럼 보이게 되고, `core/research/confidence.py`가 `source_date`를 바로 그 판단에 쓴다. snippet 연도·URL 경로·검색 시각 어느 것도 추측의 재료가 아니므로, **모른다고 기록한다** |
| **`retrieved_at`은 채운다** | adapter가 유일하게 말할 자격이 있는 사실이고, `check_source_metadata`가 SEARCH_RESULT에 요구한다. 한 call의 모든 결과가 같은 값을 공유한다 |
| **URL은 검사하되 고치지 않는다** | tracking 파라미터를 떼지 않고 host를 정규화하지 않는다. 두 주소가 같은 페이지라는 판단은 이 층이 할 수 없다. 검사만 한다: 문자열 · `http(s)` scheme · `SourceMetadata.url` 길이(2048) |
| **publisher는 자르지 않고 버린다** | 200자를 넘으면 `None`이다. 잘린 이름은 다른 조직의 이름이다. hostname에서 유도하지도 않는다 — 부재는 confidence를 제한할 뿐이고, 그것은 동작하는 답이다 |
| **결과 0개는 에러가 아니다** | `SEARCH_EMPTY_RESPONSE`를 만들지 않았다. 모델에게 빈 응답은 **없는 답**이지만 검색에서 0건은 **실제 답**이고, `core/analysis/research.py`가 이미 `if not hits: continue`로 읽는다 |
| **결과 단위 거부, call 단위 실패 아님** | title이 없거나 쓸 수 있는 URL이 없는 결과 하나 때문에 나머지 아홉을 잃지 않는다. 단 조용하지는 않다 — `BraveSearchUsage.rejected_count`로 나간다. container 자체가 이상하면(`web.results`가 list가 아님) call 전체를 `SEARCH_MALFORMED_RESPONSE`로 세운다 |
| **중복 제거 없음** | 같은 URL이 두 번 오면 두 번 돌려준다. 두 레코드가 같은 것이라는 판단은 entity resolution이고, `HARNESS.md` 7절이 이 파이프라인에서 금지한다. exact도 fuzzy도 하지 않는다 |
| **pagination 없음** | `offset`을 보내지 않고 두 번째 페이지를 읽는 루프가 없다. **한 `search()` = provider 요청 1회.** 조용히 4번 요청하는 adapter는 청구서를 4배로 만든다 |
| **`limit`은 1–20, 그 밖은 거부** | 양쪽 끝 모두 clamp하지 않는다. `limit`은 `core/analysis/policy.py`가 정한 **research 결정**이고, 25를 요청했는데 조용히 20을 돌려주는 adapter는 **배포의 정책이 이 provider로 충족 불가라는 사실을 숨기면서 성공처럼 보이게** 한다. 정책을 낮출지 다른 provider를 붙일지는 숫자를 정한 층의 결정이다. `limit < 1`도 같은 이유로 거부한다. 과금 전에 거부한다 |
| **공식 SDK 없음. stdlib `urllib`** | Phase 2B의 선택을 복사한 것이 아니라 다시 계산했다. 요청은 GET 하나에 파라미터 7개이고, 이 provider에 채택할 만한 공식 Python SDK가 없다. 범용 HTTP client는 이 Harness가 직접 소유해야 하는 retry 정책을 끌고 온다. **새 의존성 0개** |
| **transport 주입 가능** | 오프라인 테스트가 요청 구성·retry·timeout·error mapping·response 검증을 전부 실행한다. `params`를 mapping으로 넘기므로 query string을 만들지도 파싱하지도 않는다 |
| **`Accept-Encoding: gzip` 미전송** | provider 예제는 보내지만 `urlopen`은 압축을 풀지 않는다. 요청하면 압축 바이트를 malformed JSON이라 부르게 된다 |
| **`api-version` 기본값 없음** | Anthropic adapter는 버전을 못 박지만 이쪽은 못 박을 수 없다 — 하드코딩할 published version 문자열이 없고, 틀린 값은 모든 call을 깨뜨린다. 고정하려는 운영자가 dashboard의 값을 준다 |
| **retry 기본 = 1회 시도** | Anthropic adapter와 같은 원칙이다. 단 **아래 경고를 읽을 것** |
| **`retry-after` 없음 → `x-ratelimit-reset`** | 이 provider는 `retry-after`를 보내지 않는다. `x-ratelimit-reset`은 window마다 하나씩 쉼표로 오고 **첫 값이 burst window**다. 두 번째 값은 대기시간이 아니라 청구 주기다 (16일을 기다리는 retry는 없다) |
| **로그 없음** | 이 모듈에 logger가 없다. query를 로그에 안 남기는 가장 싼 방법은 남길 곳을 안 두는 것이다. `BraveSearchUsage`는 opt-in callback으로만 나가고 **숫자·status뿐**이다 (query는 `query_chars`로만) |
| **저장 없음** | cache·transcript·temp 파일 0. 같은 query를 두 번 부르면 요청도 두 번 나간다 — cache는 오래된 snippet을 방금 검색한 것처럼 보이게 한다 |
| **provider 메시지 폐기** | 422 본문은 그것을 유발한 query를 인용하고, **query는 고객의 시장을 서술한다.** stable code + HTTP status + 예외 클래스명만 남긴다 |

**⚠ rate limit과 retry 기본값.** Search plan은 월 할당량과 별개로 **초당 1건** 같은 burst
제한을 두는 경우가 흔하고, `core/analysis/research.py`는 query마다 `search()`를 **연속 루프**로
부른다. 기본 정책(1회 시도)에서는 두 번째 query가 곧바로 `429`를 받고 그 단계는 아무것도 찾지
못한 것처럼 끝난다. 기본값은 그대로 1회다 — 조용히 기다렸다 재전송하는 것을 이 파일이 배포 대신
정할 일이 아니기 때문이다. 하지만 **초당 제한이 있는 plan의 운영자는 거의 확실히
`RetryPolicy(max_attempts=3)`를 명시해야 한다.**

**snippet은 full-document evidence가 아니다.** 이 adapter는 받은 URL을 **하나도 따라가지
않는다** (테스트가 요청 수와 대상 URL을 검사한다). Phase 4 규칙 — 검색 snippet만으로는 P1이
되지 못한다 — 은 production provider를 붙여도 그대로이고,
`tests/test_search_contract.py`가 manual·brave 양쪽에서 ceiling이 MEDIUM임을 확인한다.

**실제 provider 테스트는 opt-in이다.** `HARNESS_SEARCH_LIVE_TEST=1` ·
`HARNESS_SEARCH_LIVE_API_KEY` **두 개가 함께** 있어야 실행된다. `BRAVE_API_KEY`가 환경에 있다는
것은 그것을 쓰겠다는 동의가 아니므로 게이트로 쓰지 않는다. 둘이 없으면 **NOT_RUN**이다.

**과장하지 않는 것**: provider의 query 보관 · 로그 · 재판매 여부는 배포의 속성이지 이 코드의
속성이 아니다. 이 adapter는 provider가 받은 query를 어떻게 다루는지 **주장하지 않는다**
(`docs/privacy.md` 0절). index coverage · 결과 품질 · 순위 근거도 마찬가지로 주장하지 않는다.

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
| 8 | `llm/openai.py` · `llm/google.py` (`llm/anthropic.py`·`search/brave.py`는 **완료**) |
| 9 | `reporting/html.py` · `reporting/docx.py` |

## 주의

- **Secret을 Adapter 코드에 쓰지 않는다.** 환경변수를 읽는 것은 Application 레이어의 일이고,
  Adapter는 생성자로 주입받는다.
- **원문을 로그에 남기지 않는다.** `docs/privacy.md`의 allowlist를 따른다.
- **특정 조직의 정보를 이 Public 저장소에 커밋하지 않는다.** 금지 목록은 `HARNESS.md` 9절에
  있다.

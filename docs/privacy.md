# Privacy

> Intake(파일 처리)는 Phase 2에 구현된다. 이 문서는 그 구현이 따라야 할 **규칙**이며, 규칙을
> 먼저 쓰는 이유는 privacy가 나중에 붙이는 기능이 아니기 때문이다.
> `core/intake/`나 Reference App을 만질 때 **반드시** 먼저 읽는다.

---

## 0. 가장 먼저 알아야 할 것: Zero-persistence ≠ Zero-transmission

이 Harness는 업로드된 원본을 **저장하지 않는다.** 그러나 분석을 위해 추출된 텍스트는
**설정된 LLM Provider로 전송된다.** 이 두 가지는 다른 문제이고, 둘 다 사용자에게 알려야 한다.

| | 기본 동작 |
|---|---|
| 서버에 영구 저장 | **하지 않는다** (`storage_mode = EPHEMERAL`) |
| 로그·캐시·백업·Vector DB에 원문 기록 | **하지 않는다** |
| 외부 LLM API로 추출 텍스트 전송 | **한다** — 어떤 Provider를 설정했는지에 따라 |

`locales/*.json`의 `messages.ephemeral_notice`와 `messages.transmission_notice`는 이 두 가지를
각각 사용자에게 알리는 문구다. **둘 중 하나만 표시하지 않는다.** `tests/test_locales.py`가
두 문구의 존재를 검사한다.

원본이 조직 밖으로 나가는 것 자체가 허용되지 않는 환경에서는 Local Model Adapter를 연결한다.
`LLMProvider` Interface는 그것을 위해 존재한다.

---

## 1. Upload Flow

```
POST /upload
  |
  +-- 1. source_id = new_id("src")          랜덤. 파일명은 즉시 폐기
  +-- 2. tempfile.TemporaryDirectory()      with 블록 = 보장된 삭제
  +-- 3. intake: 텍스트·표 추출              (메모리)
  +-- 4. Evidence 후보 생성                  (메모리)
  +-- 5. LLM Interface 호출 -> Finding       <-- 여기서만 외부 전송
  +-- 6. StorageProvider.save_finding(...)   null adapter면 no-op
  +-- 7. finally: tempdir 삭제
  |            텍스트 버퍼 해제
  |            processing_status = PURGED
```

**7단계는 `finally`에 둔다.** 예외가 발생했을 때가 원본이 가장 오래 남는 순간이다.

---

## 2. 영구 저장 금지 목록

- 원본 PDF · DOCX · PPTX · XLSX · HTML · CSV 등 업로드 파일 전체
- Raw binary
- 문서 전체 raw text
- 원문 전체 cache
- **업로드 파일 기반 Vector DB / Embedding**
- 원본 파일명

마지막 항목이 자주 누락된다. 파일명은 그 자체로 고객사명·프로젝트 코드·담당자명을 담는다.
그래서 `SourceMetadata`에 `filename` 필드가 없고, 스키마가 `additionalProperties: false`이고,
`tests/test_privacy.py`가 그 두 가지를 검사한다.

`.gitignore`가 `*.pdf` `*.docx` `*.pptx` `*.xlsx` `clients/` `uploads/` `tmp/` `.env`를 선제
차단한다. 커밋이 원본이 도달할 수 있는 가장 영구적인 장소다.

---

## 3. Logging — allowlist

로그에 남길 수 있는 것은 다음뿐이다.

```python
ALLOWED_LOG_FIELDS = {
    "source_id", "project_id", "file_type", "file_size",
    "processing_status", "timestamp", "error_code",
    "adapter_name",          # Adapter의 name 속성은 계약상 비민감
}
```

**deny-list가 아니라 allow-list로 구현한다.** deny-list는 새 필드가 추가될 때마다 조용히
누출된다.

### 예외 메시지를 로그에 쓰지 않는다

문서 원문이 로그에 도달하는 가장 흔한 경로는 stack trace다. 파서가 던진 예외 메시지에는
문서의 한 문단이 그대로 들어 있을 수 있다.

그래서 `core/errors.py`의 모든 예외는 짧고 안정적인 `code`를 갖고, `SourceMetadata`에는
`error_code` 필드가 있다. 파서 예외는 **코드로 변환한 뒤** 기록한다.

```python
# 하지 않는다
logger.error(f"extraction failed: {exc}")

# 한다
logger.error("extraction failed", extra={"source_id": sid, "error_code": "EXTRACT_NO_TEXT_LAYER"})
```

Core는 아예 로그를 남기지 않는다 — 예외를 던지고, 무엇을 기록할지는 호출자가 결정한다.
`tests/test_core_purity.py`가 `core/`의 `logging` import와 `print` 호출을 금지한다.

### APM · 에러 추적 도구

Sentry 등을 붙일 때 request body·form data·local variable 캡처를 **끈다.** 기본 설정은 보통
이것들을 전송한다.

---

## 4. Storage Mode

| Mode | 기본값 | 사용처 |
|---|---|---|
| `EPHEMERAL` | ✓ | Public Reference Web App. `adapters/storage/null.py` 또는 `memory.py` |
| `PERSISTENT` | | 기업·Self-host. 도입 조직이 연결한 Storage Adapter |

**Persistence 정책은 Core가 아니라 도입 조직이 결정한다.** Core는 `StorageProvider`를 호출할
뿐이고, 그 Adapter가 아무것도 하지 않는 것이 정상 동작이다.

Persistent Mode에서 저장 가능한 것: Project · Research Finding · SWOT · Client Candidate ·
Client Analysis · Proposal Strategy · Pricing Result. **원본 문서는 어느 모드에서도 이
Harness가 저장하지 않는다.**

`MemoryStorage`를 쓰는 장기 실행 프로세스는 세션 종료 시 `clear()`를 호출한다.

---

## 5. Phase 2에서 추가할 검증 (canary test)

문서에 고유 문자열을 심고 파이프라인을 통과시킨 뒤, 그 문자열이 다음 어디에도 없음을 검사한다.

- 애플리케이션 로그 · 에러 로그 · 디버그 출력
- temp 디렉토리 (삭제 후)
- Storage Adapter가 보관한 레코드
- 직렬화된 예외 메시지

Phase 1에서 이미 검사하는 것: `EchoLLM`이 프롬프트를 되돌려주지 않는다는 점
(`tests/test_adapters.py::test_echo_never_returns_the_prompt`). Provider가 입력을 그대로
반환하면 그것만으로 누출 경로가 된다.

---

## 6. Public Repository

`HARNESS.md` 9절이 원본 규칙이다. 요약하면: 실제 Client 정보 · 기업 내부자료 · 컨설팅 데이터 ·
개인정보 · API Key · Secret · 비공개 제안서 · 비공개 Master Note 전문 · 특정 조직의 Production
정보와 내부 설정은 커밋하지 않는다.

`examples/`의 데이터는 전부 가상이다. 가상임을 이름에도 표시한다 (`(가상)`, `Fictional`).

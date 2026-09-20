# Client Discovery Harness

**English: [README.md](README.md)**

기업의 사업자료 · 컨설팅 결과 · 시장자료를 분석하여, 국내·외에서 **실제 영업할 잠재 Client를
발굴**하고 우선순위 Client에 대한 **제안전략**까지 도출하는 재사용 가능한 Modular AI Harness.

한 문장으로:

> **우리가 무엇을 가지고, 어느 시장의 누구에게, 무엇을 제안할 것인가를 찾아주는 Harness**

완성형 CRM이나 Business Development Platform이 **아니다.** 다른 시스템에 삽입되는 작고
이식 가능한 Core다.

---

## 현재 상태

**Phase 6 / 9 — Proposal Strategy.**
버전 `0.6.0-alpha.1`. Research · 진단 · Client Discovery · 심층분석 · 제안전략은 동작하고,
Pricing과 보고서 출력은 아직이다. 개발 순서는 [docs/development-guide.md](docs/development-guide.md)를 참조한다.

사용 예정: 독립 Public Harness · Web Application의 분석 Core · 영업조직 교육용 Mobile-first
실습 도구. Core는 이 셋 모두에 대해 독립을 유지한다 — [HARNESS.md](HARNESS.md) 12절.

| Phase | 범위 | 상태 |
|---|---|---|
| 1 | Architecture · 문서 · Interface · Schema · KO/EN · Ephemeral Storage | **완료** |
| 2 | File Intake (8종, 메모리 파싱) · Evidence Candidate | **완료** |
| 3 | Master Note 진단 · Finding · SWOT · Key Issue | **완료** |
| 4 | Client Discovery · Fit 평가 · 결정적 우선순위 | **완료** |
| 5 | 사람이 선택한 Client 심층분석 | **완료** |
| 6 | 제안전략 (문서가 아니라 전략) | **완료** |
| 7 | Pricing Adapter | 예정 |
| 8–9 | Reference Dashboard · Report Output | 예정 |

---

## 설계 원칙

| 원칙 | 실무적 의미 |
|---|---|
| Modular Core | Core는 Interface만 알고 구현을 모른다 |
| Database Agnostic | Core에 SQL · ORM · 커넥션 · 트랜잭션이 없다 |
| Bilingual by Design | Core는 enum·code만 반환하고 문구는 App이 렌더한다 |
| Privacy by Default | 기본 `storage_mode = EPHEMERAL`. 원본은 처리 후 삭제 |
| AI Platform Agnostic | 공통 규칙 1개 문서. AI별 파일은 얇은 포인터 |
| Evidence First | 출처 없는 Finding · SWOT · Client를 만들지 않는다 |
| Structured Data First | HTML/DOCX/PDF는 Output이다. 원본 Data가 아니다 |
| Embeddable | Reference App을 삭제해도 Core가 동작한다 |
| Human Decision First | 근거 없는 점수로 사람의 판단을 대신하지 않는다 |

전체 규칙은 이 저장소의 Single Source of Truth인 **[HARNESS.md](HARNESS.md)**에 있다.
구조와 경계는 **[ARCHITECTURE.md](ARCHITECTURE.md)**에 있다.

---

## 빠른 시작

```bash
pip install -r requirements.txt
pytest
python examples/run_example.py
```

`examples/run_example.py`는 **완전히 가상의** 회사 데이터로 파이프라인을 끝까지 실행한다.
메모리에서 생성한 문서를 intake한 뒤 Phase 1 구조를 따라간다. Memory Storage Adapter와
결정적(deterministic) `echo` LLM Adapter를 쓰므로 **API 키도 네트워크도 필요 없고, intake
구현이 temp file을 만들지 않는다.**

자기 Adapter로 Harness를 조립하는 방법:

```python
from core.harness import create_harness
from adapters.storage.memory import MemoryStorage
from adapters.knowledge.static import StaticKnowledge
from adapters.llm.echo import EchoLLM
from adapters.search.manual import ManualSearch

harness = create_harness(
    storage=MemoryStorage(),
    knowledge=StaticKnowledge.from_directory("knowledge/master-notes"),
    llm=EchoLLM(),
    search=ManualSearch(),
)
```

자체 Database · 자체 Knowledge Framework · 다른 LLM으로 바꾸려면 **Adapter 모듈 하나만**
작성한다. Core는 수정하지 않는다.

---

## 저장소 구조

```
HARNESS.md              공통 규칙 — Single Source of Truth
ARCHITECTURE.md         구조와 경계
CLAUDE.md AGENTS.md GEMINI.md    AI별 얇은 진입점

core/                   순수 로직: Entity · Evidence 불변식 · Intake · Research ·
                        Client Discovery · Deep Analysis · 제안전략 · Interface
adapters/               storage · knowledge · llm · search · intake 구현체
schemas/                Entity 9개의 JSON Schema (Draft 2020-12)
knowledge/master-notes/ 공개용 분석 프레임워크 카드 (MN02–MN07)
prompts/                코드와 분리된 provider 중립 Prompt
locales/                ko.json · en.json
examples/               가상 Sample Project
tests/                  아키텍처 경계 테스트 포함
docs/                   product-spec · privacy · data-model · development-guide
```

---

## Privacy

업로드된 원본은 기본적으로 **저장되지 않는다.** 문서 원문은 로그 · 캐시 · 백업 · Vector DB에
남기지 않고, `source_id` · 파일 유형 · 크기 · 처리 상태 · 타임스탬프만 기록한다.
단 **Zero-persistence는 Zero-transmission이 아니다** — 추출된 텍스트는 설정한 LLM Provider로
전송된다. 자세한 내용은 [docs/privacy.md](docs/privacy.md)를 참조한다.

## 관련 저장소

| 저장소 | 관계 |
|---|---|
| `pricing-harness-public` | 가격 계산. Phase 7에서 JSON 파일 계약으로 연결. 런타임 의존성 없음 |
| `business-planning-handbook` | MN01–MN08 분석 프레임워크의 공개용 표현체. 경로 주입으로 읽는다 |

## 라이선스

MIT — [LICENSE](LICENSE) 참조.

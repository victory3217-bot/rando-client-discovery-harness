# Development Guide

> 규칙은 `HARNESS.md`, 구조는 `ARCHITECTURE.md`. 이 문서는 **어떻게 작업하는가**를 다룬다.

---

## 시작하기

```bash
pip install -r requirements.txt
pytest
python examples/run_example.py
```

| 항목 | 값 |
|---|---|
| Python | 3.11+ (개발 환경 3.13에서 검증) |
| 의존성 | `jsonschema` · `pytest` · intake 파서 4종(`pypdf` `python-docx` `python-pptx` `openpyxl`). **Core는 표준 라이브러리만 쓴다** |
| 패키징 | pip-installable하지 않다. 저장소 루트를 `sys.path`에 두고 쓴다 (`tests/conftest.py` 참조) |

intake 파서 4종은 BSD-3/MIT이며, **이 프로젝트는 별도의 시스템 바이너리 설치를 요구하지
않는다.** 현재 지원 환경에서는 일반적으로 pip wheel로 설치된다.

다만 **의존성 트리 전체가 순수 Python인 것은 아니다.** `python-docx`는 `lxml`을,
`python-pptx`는 `lxml` · `Pillow` · `XlsxWriter`를 요구하며 이 중 일부는 컴파일된 확장을
포함한다. 주요 플랫폼에는 wheel이 제공되지만, 어떤 환경에서도 소스 빌드가 일어나지 않는다고
보장하지는 않는다.

**OCR은 쓰지 않는다** — Tesseract 같은 외부 시스템 바이너리는 Phase 2 범위 밖이다.

각 파서가 **lazy import**하므로 CSV·TXT만 처리하는 배포는 넷 다 설치하지 않아도 되고, 없으면
`PARSER_UNAVAILABLE` 코드가 나올 뿐 startup이 깨지지 않는다.

PyMuPDF는 PDF 텍스트 추출 품질이 더 낫지만 **AGPL-3.0**이라 채택하지 않았다. MIT 저장소를
임베드하는 쪽의 배포 조건을 바꾸는 의존성은 품질보다 우선해서 거른다.

`pyproject.toml`을 만들지 않는 이유: 이 Harness는 clone 또는 vendor 해서 삽입하는 방식이고,
자매 저장소인 `pricing-harness-public`도 같은 방식이다. PyPI 배포는 MVP 범위 밖이다.

---

## 개발 순서 (Phase)

| Phase | 내용 | 상태 | 완료 기준 |
|---|---|---|---|
| **1** | Architecture · 문서 · Interface 4개 · Entity/Schema 8개 · KO/EN · Ephemeral Storage · echo LLM | **완료** | `pytest` 통과 + 경계 테스트 통과 |
| **2** | File Intake (8종) · 메모리 파싱 · Evidence Candidate · 버퍼 해제 | **완료** | canary 6개 표면 누출 0 · intake가 temp file을 만들지 않음 |
| **3** | Master Note 진단 · Finding · SWOT · Key Issue · 전송 게이트웨이 | **완료** | hallucination 거부 · 전송 단일 경계 · 오프라인 E2E |
| **4** | Client Discovery · Fit · Priority | **완료** | 근거 없는 회사명 저장 불가 · 숫자 없는 band · snippet P1 차단 |
| **5** | Client Deep Analysis (사람이 선택) | **완료** | 자동 Top 3 불가 · Phase 4 band 불변 · SYNTHESIS는 FACT 불가 |
| **6** | Proposal Strategy | **완료** | 목표 기본값 없음 · Solution whitelist · Phase 5 게이트 유지 · 근거 없는 숫자 거부 |
| **7** | Pricing Harness Adapter | **완료** | `pricing_payload`가 Pricing Harness 스키마 검증 통과 · LLM 부재 · 숫자 무생성 · payload만 전송 |
| **8** | SQLite · production provider adapter (Application·UI는 **별도 저장소**) | 예정 | Application 삭제 후에도 core 테스트 통과 · Core 변경 0 |
| **9** | Report Output (HTML/DOCX) | 예정 | 구조화 데이터만 읽어서 생성 |

Phase 1에서 **만들지 않은 것**과 그 이유:

| 안 만든 것 | 이유 |
|---|---|
| SQLite Adapter | Phase 1–7에는 읽는 주체(대시보드)가 없다. 지금 만들면 실제 쿼리 요구가 확정되기 전에 스키마를 고정하고, 마이그레이션 비용만 남는다. Phase 8에서 대시보드와 함께 만든다 |
| `core/intake/` · `core/research/` · `core/client/` 빈 패키지 | 아무것도 하지 않는 패키지를 미리 만들지 않는다. 위치는 `ARCHITECTURE.md` 7절에 문서화되어 있다 |
| `PricingProvider` · `ReportProvider` Protocol | 호출자가 없는 Protocol은 계약이 아니라 추측이다. `PricingProvider`는 Phase 7에서 **최종적으로 취소**했다 — Core가 Pricing Harness를 호출하지 않기 때문이다 (`ARCHITECTURE.md` 3절) |

### Phase 5에서 남긴 것 (backlog)

범위를 넘기지 않기 위해 의도적으로 미룬 두 가지다. 둘 다 Phase 5가 만든 문제가 아니라 Phase 5에서
드러난 문제다.

| | |
|---|---|
| **core gap 문자열의 locale 렌더링** | `"not assessed in this run"` 같은 fallback을 Core가 영문으로 만들어 사용자 목록에 그대로 나온다 (`examples/run_example.py` 11절에서 확인 가능). Bilingual by Design대로라면 code를 반환하고 `locales/*.json`이 렌더해야 한다. Phase 4의 `core/client/fit.py`도 같은 방식이라 **두 Phase를 함께 고쳐야** 하고, 그래서 Phase 5 범위에서 하지 않았다 |
| **claim과 인용 finding의 의미적 적합성** | 모델이 무관한 FACT finding을 `BUYER`에 인용해도 구조 검사는 통과한다. 지금 막는 것은 ref 해석 가능성 · finding의 evidence_type · 조직명 검증뿐이다. **해결 방법은 아직 정하지 않았다.** 더 좁은 구조적 제약으로 상당 부분을 걸러낼 수 있는지부터 검토하고, 그것으로 부족할 때 어떤 수단을 쓸지는 그때 판단한다 — 이 저장소가 지금까지 도입하지 않은 수단(NER · embedding · LLM 심판)을 들이는 선택지도 그 검토에 포함되지만, 필요하다고 단정된 상태는 아니다 |

### Web / Training 관련으로 아직 만들지 않은 것

Phase 8의 방향은 `docs/product-spec.md`에 기록되어 있으나, 현재 저장소에는 다음이 **하나도
없고** 지금 추가하지 않는다.

```
FastAPI · Flask · Django · Next.js · React · Vue · API Server
Authentication · User Account · Training Session Engine · QR Generator
Dashboard · Mobile UI · Instructor Console · Learner Account
Team Comparison · Deployment
```

Web framework 의존성이 하나라도 들어오면 `tests/test_core_purity.py`가 `core/`에서 그것을
잡는다. Application Layer 쪽은 테스트가 막아주지 않으므로, 그 디렉토리를 만드는 시점에
`HARNESS.md` 12절의 경계를 먼저 읽는다.

Phase 8의 Application과 UI는 **이 저장소가 아니라 별도 저장소**에 만든다. 근거는
`docs/product-spec.md` Phase 8 절에 있다 — 배포 대상이 런타임 없는 정적 사이트이고, Core는
어떤 사이트의 백엔드도 되어서는 안 된다. 이 저장소에 추가되는 것은 adapter 뿐이다.

### `scripts/spikes/`

측정용 코드다. production 코드가 아니고, `core/`도 `adapters/`도 import하지 않는 것을
전제로 하지 않는다 — 오히려 Core를 밖에서 호출해 재는 것이 목적이다. 규칙 3개:

1. `core/`에 넣지 않는다.
2. 테스트 스위트의 의존성이 되지 않는다 (`pytest`가 수집하지 않는 위치·이름).
3. 문서 원문 · prompt · secret을 출력하지 않는다.

`phase8_runtime_spike.py`는 Bootstrap Analysis Run의 provider 호출 수 · 문자 수 ·
wall-clock · peak 메모리를 볼륨별로 잰다. **production module이 아니라 재현 가능한
architecture benchmark**다 — 결과가 `docs/product-spec.md`에 인용되어 있으므로, 제약이
바뀌었는지 확인할 때 같은 명령으로 다시 돌린다.

| | |
|---|---|
| 기본 모드 | `EchoLLM` · 네트워크 없음 · credential 없음 · 결정적 |
| 실제 provider | **explicit opt-in** (`--real-provider`). 기본값으로는 절대 켜지지 않는다 |
| 출력 | 개수 · 문자 수 · 초 · 바이트. **secret · prompt · 문서 원문을 stdout에도 로그에도 쓰지 않는다** |

---

## 테스트

```bash
pytest                    # 전체
pytest tests/test_core_purity.py -v
pytest -k evidence
```

| 파일 | 무엇을 지키는가 |
|---|---|
| `test_core_purity.py` | Core에 파일 I/O · 환경변수 · 네트워크 · logging · `print` · adapter import가 없다 |
| `test_core_standalone.py` | `core/`만 복사해 빈 디렉토리에서 실행해도 동작한다. Core가 표준 라이브러리만 쓴다 |
| `test_schemas.py` | dataclass ↔ JSON Schema 필드·enum 일치, 예제 검증 |
| `test_locales.py` | ko/en 키 구조 동일, 모든 enum 멤버에 라벨 존재, 오래된 라벨 없음 |
| `test_evidence.py` | Evidence 불변식 |
| `test_adapters.py` | Adapter 계약 (새 Adapter를 만들 때의 사양서 역할) |
| `test_knowledge_cards.py` | MN 카드 형식과 dimension 목록이 `HARNESS.md` 5절과 일치 |
| `test_docs_no_duplication.py` | AI 진입점 3개가 얇게 유지되고 Required Reading이 실존 파일을 가리킨다 |
| `test_privacy.py` | `SourceMetadata`에 파일명·원문 필드가 없다, source_id가 랜덤이다 |
| `test_intake.py` | 8종 파싱 · locator 형식 · 결정성 · 인코딩 · OOXML 판별 · 상한 · 에러 코드 · `display_label` |
| `test_intake_canary.py` | **6개 표면 누출 검증** — 로그 · 파일시스템 · storage · `repr` · traceback · 직렬화 |
| `test_research.py` | 파이프라인 4단계 · batching · framework 선택 · 검색결과 통합 · 오프라인 E2E |
| `test_research_validation.py` | **hallucination 거부** · confidence cap · snippet 상한 · KeyIssue 전부-또는-전무 · directive는 flag이지 거부가 아님 · Entity 불변식 |
| `test_transmission_boundary.py` | **`core/` 전체에서 LLM 호출이 단일 게이트웨이를 통과** (AST) · 전송 객체의 `repr` 은닉 |
| `test_client_discovery.py` | criteria · 조직 추출 · fit 8개 · 검색 통합 · 오프라인 E2E |
| `test_client_validation.py` | **회사명 hallucination 거부** · **토큰 경계 공격** · signal 없는 STRONG 차단 · 파생 집계 일관성 · 잘림 없는 거부 |
| `test_client_priority.py` | 규칙표 전 분기 · **snippet P1 차단** · reason code i18n · 결정성 |
| `test_analysis_selection.py` | **사람이 고른 Client만** · 자동 Top 3 부재(AST) · Phase 4 band 불변 |
| `test_analysis_validation.py` | claim 19개 · evidence type 3분류 · CA 4조건 · VP 최소조건 · 조직명 검증 |
| `test_client_analysis.py` | MN별 4회 호출 · 해외 8개 · serializer roundtrip · 오프라인 E2E |
| `test_analysis_canary.py` | 6표면 누출 0 · 개인정보 필드 부재 |
| `test_analysis_handoff.py` | Phase 6 입력 · Phase 7 commercial context 4개 |
| `test_proposal_validation.py` | 목표 게이트 · Solution whitelist · 숫자 출처 · 반론 basis · Entity 불변식 |
| `test_proposal_strategy.py` | 2회 호출 · Phase 5 게이트 · serializer roundtrip · 오프라인 E2E |
| `test_proposal_canary.py` | 6표면 누출 0 · 연락처 필드 부재 |
| `test_proposal_handoff.py` | Phase 7 commercial context · Phase 9 **구조만** (렌더링 0) |
| `test_pricing_contract.py` | 로컬 strict contract · unknown key 0 · **실제 외부 스키마 검증**(있을 때) · 미검증과 통과의 구분 · contract_version · 결정성 |
| `test_pricing_validation.py` | **LLM 부재(AST)** · **곱셈·나눗셈 부재(AST)** · 필드별 정확 복사 · `None`→`null`(0 아님) · MN06 claim 숫자화 차단 · whitelist · **gap_ref gate**(문장으로 승인 불가 · 결정성 · 변경 시 무효 · stale ref 거부) · 그쪽 rule은 flag · engine result 대조 |
| `test_pricing_bridge.py` | serializer roundtrip · Entity 불변식 · 파일 어댑터 E2E · blocked는 파일을 쓰지 않음 · **blocked→acknowledged UI round trip** · 두 저장소 동시 import 부재 |
| `test_pricing_canary.py` | 6표면 + **export 표면** — payload에 파일명·경로·URL·claim 원문 0 |
| `pricing_fixtures.py` | Phase 7 고정값 (테스트가 아니라 fixture 모듈). **모든 숫자가 서로 유도되지 않게** 골라져 있다 |
| `scripted_llm.py` | 준비된 응답을 돌려주는 테스트 double (테스트가 아니라 도구 모듈) |
| `intake_fixtures.py` | 테스트 문서 8종을 메모리에서 생성 (테스트가 아니라 fixture 모듈) |

`.gitignore`가 `*.pdf` `*.docx` `*.pptx` `*.xlsx`를 차단하므로 **바이너리 fixture를 커밋할 수
없다.** 그래서 `intake_fixtures.py`가 8종을 코드로 만든다 — Public 저장소에 정체불명의
바이너리가 남지 않고, 테스트가 파싱하는 모든 바이트를 리뷰할 수 있다. PDF는 의존성 없이 손으로
조립한다 (비압축 content stream).

**경계 테스트가 실패하면 테스트를 고치지 않는다.** `test_core_purity`와
`test_core_standalone`은 `HARNESS.md` 11절 성공기준의 마지막 두 항목을 자동 검증하는
장치다. 실패는 "Core가 무언가를 안으로 끌어들였다"는 신호이며, 답은 그것을 Adapter나
Application 레이어로 옮기는 것이다.

---

## 작업별 절차

### 필드를 추가한다
`docs/data-model.md` 마지막 절을 따른다 — dataclass · schema · 문서 · locales를 함께 고친다.

### 새 Adapter를 만든다
`adapters/README.md`를 따른다. `tests/test_adapters.py`가 사양서다.

### 새 Interface를 만든다
먼저 **호출자가 있는지** 확인한다. 없으면 `ARCHITECTURE.md` 3절에 정의만 적고 코드는 쓰지
않는다. 호출자가 생기면 `core/interfaces/`에 `Protocol`로 추가한다 (ABC 아님).

### Prompt를 추가한다
`prompts/<stage>/<name>.md`에 둔다. 코드에 프롬프트 문자열을 쓰지 않는다. `prompts/README.md`
참조.

### Engine을 구현한다 (Phase 3+)
1. `docs/product-spec.md`에서 그 Stage의 입출력을 확인한다
2. `core/<engine>/`에 순수 함수로 작성한다 — Provider는 인자로 받는다
3. 산출물을 `core/evidence.py`의 `check_*`로 검증한 뒤 반환한다
4. 테스트는 `EchoLLM`으로 작성한다 — CI가 API 키 없이 돌아야 한다

---

## 코드 규약

| | |
|---|---|
| 파일 첫 줄 | `# -*- coding: utf-8 -*-` (자매 저장소와 동일) |
| `from __future__ import annotations` | 모든 모듈 |
| 타입 힌트 | public 함수·메서드에 필수 |
| Docstring | 모듈과 public 정의에. **무엇을 하는지가 아니라 왜 그렇게 되어 있는지**를 쓴다 |
| 주석 언어 | 코드 주석·docstring은 영어, 문서(`*.md`)는 한국어 (README는 양쪽) |
| Core의 예외 | `core/errors.py`의 계층을 쓴다. 비민감 `code`를 갖는다 |
| Core의 출력 | 없다. 값을 반환하거나 예외를 던진다 |

---

## 문서 구조

```
HARNESS.md          규칙 — Single Source of Truth. 여기만 고친다
ARCHITECTURE.md     구조 · 경계 · 수정 지점
docs/
  product-spec.md       단계별 입출력
  privacy.md            업로드 · 로깅 · 전송 규칙
  data-model.md         Entity 필드 정의
  development-guide.md  이 문서
README.md / README.ko.md   외부용 소개 (bilingual)
CLAUDE.md / AGENTS.md / GEMINI.md   AI별 얇은 진입점 (40줄 이하)
```

**AI별 진입점에 규칙을 복제하지 않는다.** 복제하면 세 파일이 drift 하고, 결국 세 AI가 서로
다른 버전의 규칙을 따른다. `tests/test_docs_no_duplication.py`가 이를 막는다.

---

## 외부 저장소

| 저장소 | 관계 | 필요 여부 |
|---|---|---|
| `pricing-harness-public` | JSON 파일 계약으로 연결. `FilePricingBridge.from_repository(path)`에 경로를 주입하면 실제 스키마로 검증하고, 없으면 `EXTERNAL_CONTRACT_NOT_CHECKED` | 선택 |
| `business-planning-handbook` | MN 방법론 원본. `adapters/knowledge/handbook.py`가 경로 주입으로 읽는다 | 선택 — 없어도 카드만으로 동작 |

둘 다 **런타임 의존성이 아니다.** `examples/run_example.py`는 handbook이 `../business-planning-handbook`에
있으면 `handbook found`, 없으면 `cards only`로 표시하고 정상 동작한다.

`pricing-harness-public`을 in-process import 하면 **`core` 패키지명이 충돌한다** —
`ARCHITECTURE.md` 6절의 "알려진 제약"을 읽는다. 스키마 *파일*을 읽는 것은 충돌하지 않으므로
Phase 7의 외부 검증은 그 방식으로 한다.

---

## 커밋

- Public 저장소다. 커밋 전 `HARNESS.md` 9절 금지사항을 확인한다.
- `.gitignore`가 업로드 확장자와 `clients/` · `uploads/` · `.env`를 차단하지만, 최종 책임은
  커밋하는 사람에게 있다.
- `examples/`의 데이터는 전부 가상이며, 이름에 가상임을 표시한다.

# Phase 8 Deployment Proof

**production 애플리케이션이 아니다.** `docs/product-spec.md` Phase 8 절의 Application
architecture가 실제 runtime에서 성립하는지만 확인하는 일회성 검증물이다. 18-step UI도,
인증도, production adapter도 없다.

Harness 본체는 **전혀 바뀌지 않는다.** `core/` · `adapters/` · `schemas/` · `locales/` ·
`tests/` · `examples/`에 파일 하나 건드리지 않고, `requirements.txt`에 의존성을 추가하지 않는다.
Harness는 Web framework 없이 동작해야 하고 `tests/test_core_standalone.py`가 그것을 계속
검사한다.

---

## 실행

```bash
python -m venv .proof-venv                       # 저장소 밖에 만드는 편이 낫다
.proof-venv/Scripts/python -m pip install -r requirements-proof.txt pytest

# 검증 62개
.proof-venv/Scripts/python -m pytest scripts/spikes/phase8_deployment_proof/proof_tests.py -q

# 브라우저로 보기
cd scripts/spikes/phase8_deployment_proof
../../../.proof-venv/Scripts/python -m uvicorn proof_app.app:create_app --factory --port 8391
```

`proof_tests.py`는 **의도적으로 `test_*.py`가 아니다.** 저장소 루트의 `pytest`가 이 파일을
수집하면 Harness 테스트 스위트가 Litestar 설치에 의존하게 된다. 경로로 직접 지정하면 안의
`test_*` 함수는 정상 수집된다.

---

## 무엇을 증명하는가

| 라우트 | 증명하는 것 |
|---|---|
| `GET /` | Harness가 **밖에서** import되고 `create_harness()`로 조립된다 |
| `GET /session` | 세션 쿠키가 발급되고 **불투명 id 하나만** 담는다 |
| `GET /upload` | CSRF 토큰이 들어간 서버 렌더 폼. SPA 아님 |
| `POST /upload` | multipart bytes가 메모리로 Harness에 도달하고, run id가 즉시 반환된다 |
| `GET /runs/{id}` | 서버 렌더 상태 화면. 375px에서 읽힌다 |
| `GET /api/runs/{id}` | 같은 상태를 JSON으로. 민감한 것이 하나도 없다 |
| `POST /acknowledge` | CSRF가 업로드 말고 다른 POST에서도 강제된다 |

---

## 구조

```
proof_app/
  config.py         환경변수 · 경로. 읽은 값을 절대 출력하지 않는다
  safe_log.py       allowlist 로깅. 목록에 없는 필드는 기록될 수 없다
  runs.py           BootstrapStatus(application-local) + in-process background runner
  store.py          SQLite. proof_run · proof_session 두 테이블. Harness 9 entity 아님
  harness_probe.py  Harness를 만지는 유일한 파일
  app.py            Litestar 조립 + 7개 라우트
  templates/        서버 렌더 HTML
  static/proof.css  mobile-first, 375px 기준
proof_tests.py      검증 62개
deploy/render.yaml  배포 manifest (적용하지 않았다)
```

---

## 지켜지는 경계

**Core는 Web을 모른다.** `proof_tests.py::test_b2`가 `core/` 전체를 스캔해 `litestar` ·
`starlette` · `fastapi` · `jinja2` · `uvicorn` 문자열이 없음을 확인한다.

**import에 부수효과가 없다.** `proof_app.app`을 import해도 아무 파일·디렉토리가 생기지
않는다. 모듈 수준에서 앱을 만들면 SQLite 디렉토리가 시스템 temp 루트에 생기고, Harness의
`test_intake_canary.py::test_intake_leaves_no_file_in_the_temp_directory`가 바로 그 디렉토리를
감시하고 있어 실패한다. 그 테스트가 이 문제를 잡아냈다 — proof는 Harness가 테스트되는 환경을
건드려서는 안 된다. 그래서 `--factory`로 띄운다.

**업로드는 저장되지 않는다.** bytes는 `IntakeSession`으로 들어가 evidence candidate가 되고
run이 끝나면 사라진다. SQLite에는 그것을 담을 컬럼 자체가 없다 (`test_i`).

**원본 파일명은 확장자 판별에만 쓰이고 즉시 버려진다.** 로그에도 응답에도 화면에도 나오지
않는다 (`test_j`, `test_j2`).

**background run은 durable하지 않다.** broker도 worker도 queue도 retry도 없다. 프로세스가
죽으면 진행 중이던 run은 사라지고, 다시 시작되지 않는다. 재시작 후 `RUNNING_*`으로 남은 행은
**읽는 시점에** `INTERRUPTED_REUPLOAD_REQUIRED`로 해석된다 — 저장된 값은 그대로 두고, 해석만
바꾼다. 그 구분이 사라지면 "run이 중단을 기록했다"(불가능하다)와 "읽는 쪽이 추론했다"를
나눌 수 없다.

**부분 실패는 all-or-nothing이 아니다.** 업로드 폼의 체크박스로 discovery만 실패시켜 볼 수
있다. 결과는 `DISCOVERY_FAILED_REUPLOAD_REQUIRED`이고, 화면은 "진단 결과는 남아 있습니다.
고객 발굴을 다시 하려면 자료를 다시 올려야 합니다"라고 말한다.

---

## 사용 데이터

전부 가상이다 (`HARNESS.md` 9절). 실제 고객명 · 회사자료 · 개인정보 · credential을 쓰지
않는다. LLM은 `EchoLLM`이고 네트워크에 나가지 않는다.

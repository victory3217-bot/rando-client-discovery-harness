# knowledge/master-notes — 공개용 분석 프레임워크 카드

이 디렉토리의 `MN0*.json`은 **분석 프레임워크**다. 시장이나 기업에 관한 **사실 데이터가
아니다.** 이 구분은 `HARNESS.md` 5절에 정의되어 있고, 무너지면 Harness 전체가 신뢰를 잃는다.

```
Company / Market / External Data  =  Evidence
Master Note                       =  Analysis Framework
```

## 이 파일들에 무엇이 들어 있는가

각 카드는 "무엇을 확인해야 하는가"의 목록이다. 답은 업로드된 자료(Evidence)에서만 나온다.

| 파일 | 영역 | Handbook |
|---|---|---|
| `MN02.json` | 역량·아이템·산업·시장 | CH02 |
| `MN03.json` | 고객·구매자·문제 | CH03 |
| `MN04.json` | 가치제안·경쟁우위·포지셔닝 | CH04 |
| `MN05.json` | 비즈니스모델 | CH05 |
| `MN06.json` | 원가·가격·수익모델 | CH06 |
| `MN07.json` | 사업타당성·유효시장·추정재무 | CH07 |

**MN01**(사업목적·목표수익·성장목표·리스크 허용범위)은 상위 판단기준이며, 필요할 때
`reference`를 통해 참조한다. **MN08**(실행 → 데이터 → 수정 → 재실행)은 MVP 범위 밖이다.

ENGINE 1(Research & Diagnosis)은 MN02–MN07을 사용하고, ENGINE 2의 Client 분석은 **MN03–MN06만**
사용한다. 이 구분은 `core/harness.py`의 `RESEARCH_FRAMEWORKS` / `CLIENT_ANALYSIS_FRAMEWORKS`에
코드로 박혀 있다.

## 여기에 무엇을 넣지 않는가

이 저장소는 Public으로 공개된다. 따라서:

- **비공개 Master Note 전문을 넣지 않는다.** 이 카드는 확인 항목과 질문만 담는다.
- **방법론 본문을 복사하지 않는다.** 상세 방법론은 `business-planning-handbook`의 CH02–CH07에
  있고, 각 카드의 `reference`가 그곳을 가리킨다. 복사하면 두 곳이 drift 한다.
- 실제 기업·Client 사례를 넣지 않는다.

## 자기 방법론으로 교체하기

이 디렉토리는 `adapters/knowledge/static.py`가 읽는 **기본 제공 데이터**일 뿐이다. 조직 고유의
영업·사업개발 방법론을 쓰려면 `KnowledgeProvider`를 구현하는 Adapter를 하나 추가한다 —
`core/`는 수정하지 않는다.

```python
harness = create_harness(
    knowledge=MyMethodologyKnowledge(...),   # 여기만 바꾼다
    storage=..., llm=..., search=...,
)
```

`framework_id`는 `MN02` 같은 문자열일 필요가 없다. `core/harness.py`의 두 상수만 조직 프레임워크
id로 맞추면 된다.

## 파일 형식

```json
{
  "framework_id": "MN02",
  "title_ko": "...", "title_en": "...",
  "reference": { "handbook_chapter": "CH02", "handbook_paths": ["..."] },
  "dimensions": [
    { "key": "capability", "label_ko": "역량", "label_en": "Capability",
      "question_ko": "...", "question_en": "..." }
  ]
}
```

`core/interfaces/knowledge.py`의 `Framework` · `FrameworkDimension`과 1:1로 대응한다.
`tests/test_knowledge_cards.py`가 모든 카드를 로드해 검증한다.

# HWP 영어시험 파싱 시스템 구조 규칙

## 📋 목차
1. [데이터 구조](#데이터-구조)
2. [문항 번호 탐지 규칙](#문항-번호-탐지-규칙)
3. [질문문 탐지 규칙](#질문문-탐지-규칙)
4. [지문 분류 규칙](#지문-분류-규칙)
5. [선지/보기 탐지 규칙](#선지보기-탐지-규칙)
6. [정답 추출 규칙](#정답-추출-규칙)
7. [문제유형 분류 규칙](#문제유형-분류-규칙)
8. [3단계 파싱 프로세스](#3단계-파싱-프로세스)
9. [Validation & Repair 규칙](#validation--repair-규칙)

---

## 📊 데이터 구조

### QuestionData (9열 + v2.0 필드)

```python
{
  # ── 9열 고정 출력 필드 ──
  "question_number": int,        # 문제번호
  "school": str,                 # 학교
  "grade": int,                  # 학년
  "question_text": str,          # 출제문항
  "common_passage": str,         # 공통지문
  "question_passage": str,       # 문제지문
  "choices": str,                # 보기/조건
  "answer": str,                 # 정답
  "question_type": str,          # 문제유형 (4가지 고정)
  
  # ── v2.0 강화 필드 ──
  "seq_no": int,                 # 문서 순서 기반 번호
  "raw_no": int | null,          # 텍스트 원본 번호
  "answer_source": str,          # answer_key | inline | missing
  "source_block_ids": [int],     # 소스 라인 인덱스 배열
  "item_warnings": [str],        # 문항별 경고
  "choices_list": [str],        # 선지 배열 (JSON 호환)
  
  # ── 내부 메타데이터 ──
  "confidence": float,
  "notes": str,
  "passage_group_id": int | null,
  "raw_block_text": str,
}
```

### 문제유형 (4가지 고정)
- `Vocabulary`
- `Reading/Comprehension` (기본값)
- `Grammar`
- `Listening`

---

## 🔢 문항 번호 탐지 규칙

### PATTERN_Q_START (v2.0)

```python
PATTERN_Q_START = [
    r'^\s*(\d{1,2})\s*\.\s+',     # "N. " (예: "1. ")
    r'^\s*(\d{1,2})\s*\)\s+',      # "N) " (예: "1) ")
    r'^\s*\((\d{1,2})\)\s+',       # "(N) " (예: "(1) ")
    r'^\s*\[(\d{1,2})\]\s+',       # "[N] " (예: "[1] ")
]
```

### 탐지 우선순위
1. **Pass 1**: PATTERN_Q_START 패턴 매칭
2. **Pass 2**: 번호만 있는 단독 블록 → 다음 줄과 병합 후 재검사
3. **Pass 3**: 명시적 번호 없음 → 질문 패턴으로 순차 번호 부여

### 필터링 규칙
- ❌ 선지 패턴(①②③④⑤)으로 시작하는 줄은 문항 번호로 인식하지 않음
- ✅ 1 ≤ 번호 ≤ 50 범위만 유효

---

## ❓ 질문문 탐지 규칙

### 객관식 종결 패턴

```yaml
endings:
  - '것은\?$'      # 예: "가장 적절한 것은?"
  - '것\?$'
  - '문장은\?$'
  - '개수는\?$'
  - '질문은\?$'
  - '단어는\?$'
  - '곳은\?$'
  - '고르면\?$'
  - '인가\?$'
  - '않은가\?$'
  - '무엇인가\?$'
  - '알맞은가\?$'
  - '올바른가\?$'
  - '적절한가\?$'
```

### 서술형 종결 패턴

```yaml
subjective_endings:
  - '쓰시오\.'
  - '완성하시오\.'
  - '영작하시오\.'
  - '답하시오\.'
  - '채우시오\.'
  - '서술하시오\.'
  - '설명하시오\.'
  - '구하시오\.'
  - '고르시오\.'
  - '나타내시오\.'
  - '적으시오\.'
  - '바꾸시오\.'
  - '고치시오\.'
  - '표현하시오\.'
```

### 질문 후보 점수화 (v2.0)

```python
점수 계산:
  +2 : '?' 포함
  +2 : '시오.' 포함
  +1 : '다음', '윗글', '위 글', '대화', '표', '읽고' 포함
  +1 : 한글 10자 이상
  -3 : 선지 패턴(①②③④⑤)으로 시작

점수 >= 2 → 질문 후보로 인식
```

### 필터링 규칙
- ❌ 메타데이터 라인 (년도, 출판사, 정답 헤더 등)
- ❌ 선지로 시작하는 줄
- ❌ 길이 < 5자
- ❌ 특수 기호로 시작 (•→-·▶▷)

---

## 📖 지문 분류 규칙

### 공통지문 (Common Passage)

**트리거 패턴:**
```yaml
intro_patterns:
  - '다음 글을 읽고'
  - '다음을 읽고'
  - '물음에 답하시오'
```

**참조 패턴:**
```yaml
reference_patterns:
  - '^윗글'
  - '^위 글'
  - '^위의 글'
  - '^위 대화'
  - '^위의 대화'
```

**처리 규칙:**
1. "다음 글을 읽고 물음에 답하시오." **바로 아래 박스** = 공통지문
2. "윗글~"로 시작하는 문항 → 이전 공통지문 참조
3. 공통지문 공유 문항은 **각각 별도 행(row)**으로 출력
4. 엑셀에서 공통지문 셀 병합 (해당 문항 범위)

### 문제지문 (Question Passage)

- 해당 문항에만 등장하는 박스/지문
- 한 문항에 박스 여러 개 → 모두 포함
- 그림이 있으면 텍스트로 변환하여 포함

### 박스 라벨 키워드

```yaml
box_labels:
  - '<예시문>'
  - '<예문>'
  - '<보기>'
  - '<조건>'
  - '<요약문>'
```

---

## 🔘 선지/보기 탐지 규칙

### PATTERN_CHOICE (v2.0)

```python
PATTERN_CHOICE = [
    re.compile(r'[①②③④⑤]'),           # 원문자
    re.compile(r'^\s*\(?[1-5]\)?[.)]\s+'), # 숫자 (1) 2. 등
    re.compile(r'^\s*[A-Ea-e][.)]\s+'),   # 영문자 A) B. 등
]
```

### 선지 분리 규칙

```python
_split_choices(text):
  # 한 줄에 여러 선지(①②③④⑤)가 있으면 분리
  # 예: "① A ② B ③ C" → ["① A", "② B", "③ C"]
```

### 서술형 처리

- 서술형 문항(~시오.) → `choices` = 빈 문자열
- `choices_list` = 빈 배열
- 답란 패턴: `^\s*→\s*[_\s]{3,}`

---

## ✅ 정답 추출 규칙

### 정답 섹션 헤더

```python
_is_end_of_content(line):
  패턴: '^\s*(정답|정답\s*및\s*해설|정답\s*/\s*해설|Answer\s*Key?|모범\s*답안)\s*$'
```

### 정답 매핑 패턴

```yaml
mapping_patterns:
  - '(\d+)\s*[:\.\-→]\s*([①②③④⑤\d]+)'  # "1: ②" 또는 "1. 2"
  - '(\d+)\s*번?\s*[:\.\-→]?\s*([①②③④⑤ⓐⓑⓒⓓⓔ][\s,]*[ⓐⓑⓒⓓⓔ]*)'  # "1번 ⓐ,ⓑ"
  - '(\d+)\s+([①②③④⑤])'  # "1 ②"
```

### 정답 정규화

```python
_normalize_answer(ans):
  # 숫자 → 원문자 변환
  '1' → '①'
  '2' → '②'
  '3' → '③'
  '4' → '④'
  '5' → '⑤'
```

### answer_source 우선순위

1. **answer_key**: 정답 섹션에서 추출
2. **inline**: 문항 본문에서 인라인 정답
3. **missing**: 정답 없음

---

## 🏷️ 문제유형 분류 규칙

### 키워드 기반 분류 (우선순위 순)

#### 1. Grammar (우선순위 1)

```python
_GRAMMAR_KEYWORDS = [
    '문법', '어법', '문법적으로', '문법상',
    '영작', '올바르게 표현', '문장을 완성',
]
```

#### 2. Vocabulary (우선순위 2)

```python
_VOCABULARY_KEYWORDS = [
    '의미로', '뜻으로', '다른 뜻', '의미가', '의미는',
]
```

#### 3. Listening (우선순위 3)

```python
_LISTENING_KEYWORDS = [
    '듣기', '들으시오', '들려주는', '방송',
]
```

#### 4. Reading/Comprehension (기본값)

- 위 키워드가 없으면 기본값
- confidence = 0.7 (다른 유형은 0.9)

---

## 🔄 3단계 파싱 프로세스

### [1단계] 전체 문항 번호 스캔

```python
_prescan_question_numbers(lines):
  # 목적: 시험지의 모든 문항 번호를 사전 탐지
  # 결과: expected_numbers, number_positions
```

**탐지 방법:**
1. PATTERN_Q_START 패턴 매칭
2. 번호만 있는 단독 블록 → 다음 줄 병합 후 재검사
3. 질문 패턴으로 순차 번호 부여

### [2단계] 상세 파싱

```python
# 각 문항에 대해:
1. 출제문항 추출 (질문문)
2. 지문 분류 (공통지문 vs 문제지문)
3. 보기/조건 추출
4. 정답 추출 (인라인 우선)
5. 문제유형 분류
6. seq_no, source_block_ids, choices_list 등 v2.0 필드 설정
```

### [3단계] 검증 및 복구

```python
# 누락 문항 확인
missing = expected_numbers - extracted_numbers

# 복구 시도
for num in missing:
    recovered = _recover_missing_question(...)
    if recovered:
        questions.append(recovered)
```

---

## 🔍 Validation & Repair 규칙

### Validation 단계

```python
_validate_extraction(questions, answer_map, expected_numbers):
  검증 항목:
    1. detected_questions vs detected_answers 비교
    2. 번호 연속성 검사 (gap > 2 → warning)
    3. 품질 최소 조건:
       - question_text >= 5 OR
       - choices >= 3 OR
       - passage >= 50
```

### Repair 단계

#### Case 1: 정답키 기반 강제 슬롯

```python
# 정답키에 존재하나 문항 없는 번호 발견
→ 강제 QuestionData 슬롯 생성
→ item_warnings: ["FORCED_SLOT_FROM_ANSWER_KEY"]
```

#### Case 2: 고아 선지 기반 생성

```python
# 선지(①~⑤) 반복 등장하나 문항번호 없음
→ 새 문항 생성
→ item_warnings: ["FORCED_SLOT_FROM_ORPHAN_CHOICES"]
```

#### Case 3: 번호 점프 구간 재스캔

```python
# 번호 점프 발생 (예: 3 → 5)
→ 점프 구간(4번) 주변 블록 재스캔
→ 복구 시도
→ item_warnings: ["RECOVERED_FROM_NUMBER_JUMP"]
```

---

## 📝 필수 로그 출력

파일 처리 후 반드시 출력:

```
===== 파싱 검증 결과 =====
시험지 총 문항 수: N개
출력된 행 수: M개
문항 번호 리스트: [1, 2, 3, ..., N]
누락된 문항: [없음] 또는 [5번, 12번]

── Validation 결과 ──
  detected_questions: N
  detected_answers: M
  missing_answer_numbers: [...]
  questions_without_answer: [...]
  suspicious_number_jumps: [...]
  questions_without_question_text: [...]

── Repair 로그 ──
  Case1: N번 강제 슬롯 생성
  Case2: M번 선지 기반 생성
  Case3: K번 번호 점프 복구
========================
```

---

## ⚠️ 핵심 원칙

### 문항 누락 절대 금지

1. ✅ 공통지문 공유 문항도 각각 별도 행으로 출력
2. ✅ 서술형 문항 반드시 포함 (보기만 비움)
3. ✅ "윗글~" 문항도 별도 행
4. ✅ 번호 점프 허용 (경고만 출력)
5. ✅ 과분할보다 과포함 허용 (누락 방지 우선)

### 출력 형식 (절대 준수)

- **한 문항 = 한 행(row)**
- **열 순서 고정**: 문제번호 | 학교 | 학년 | 출제문항 | 공통지문 | 문제지문 | 보기/조건 | 정답 | 문제유형

---

## 📌 참고 파일

- **규칙 설정**: `backend/rules/config.yaml`
- **파싱 엔진**: `backend/question_extractor.py`
- **HWP 추출**: `backend/hwp_parser.py`
- **Excel 생성**: `backend/excel_generator.py`






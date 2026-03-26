"""
434개 시험지 일괄 파싱 검증 스크립트
검사항목:
  1. 파싱 성공/실패
  2. 문항번호 누락 / 중복 / 비연속
  3. 문항 수와 정답 수 불일치
  4. 객관식인데 선지 미검출
  5. 서술형인데 답란 구조 오류
  6. 문제 본문 누락 (question_text < 5자)
  7. 두 문제 병합 의심 (passage 길이 과다)
  8. 보기 파싱 실패 (객관식인데 choices_list < 2)
  9. 정답 매핑 실패 (answer 비어있음)
"""

import os
import sys
import json
import time
import traceback
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from hwp_parser import extract_text_from_hwp
from question_extractor import extract_questions

DATASET_DIR = r"C:\DBexam\NE_DBexam\exam_dataset"
REPORT_PATH = os.path.join(os.path.dirname(__file__), "validation_report.json")
SUMMARY_PATH = os.path.join(os.path.dirname(__file__), "validation_summary.txt")
# None이면 전체, 숫자면 해당 개수만 검증 (예: 354)
FILE_LIMIT = 354

def validate_file(filepath: str, filename: str) -> dict:
    result = {
        "filename": filename,
        "parse_success": False,
        "parse_method": "",
        "parse_error": "",
        "total_questions": 0,
        "total_answers": 0,
        "issues": [],
    }

    try:
        parse_result = extract_text_from_hwp(filepath)
        if not parse_result.success:
            result["parse_error"] = parse_result.error or "unknown"
            return result

        result["parse_success"] = True
        result["parse_method"] = parse_result.method_used

        extraction = extract_questions(
            parse_result.full_text, filename,
            endnote_answers=parse_result.endnote_answers,
        )
        questions = extraction.questions
        result["total_questions"] = len(questions)
        result["total_answers"] = extraction.detected_answers

        if len(questions) == 0:
            result["issues"].append({"type": "NO_QUESTIONS", "detail": "문항이 하나도 추출되지 않음"})
            return result

        q_numbers = [q.question_number for q in questions]
        q_set = set(q_numbers)

        # 1. 문항번호 중복
        if len(q_numbers) != len(q_set):
            dupes = [n for n in q_set if q_numbers.count(n) > 1]
            result["issues"].append({
                "type": "DUPLICATE_NUMBERS",
                "detail": f"중복 문항번호: {dupes}"
            })

        # 2. 문항번호 누락 / 비연속
        numeric_nums = sorted([n for n in q_set if isinstance(n, int) and n > 0])
        if numeric_nums:
            expected = set(range(1, max(numeric_nums) + 1))
            missing = sorted(expected - set(numeric_nums))
            if missing:
                result["issues"].append({
                    "type": "MISSING_NUMBERS",
                    "detail": f"누락 문항번호: {missing}"
                })

        # 3. 문항 수와 정답 수 불일치
        answers_found = sum(1 for q in questions if q.answer and q.answer.strip())
        if extraction.detected_answers > 0 and abs(len(questions) - extraction.detected_answers) > 2:
            result["issues"].append({
                "type": "QUESTION_ANSWER_COUNT_MISMATCH",
                "detail": f"문항={len(questions)}, 정답키감지={extraction.detected_answers}, 정답있는문항={answers_found}"
            })

        for q in questions:
            qn = q.question_number
            is_subjective = q.question_format == "서술형"
            is_objective = q.question_format == "객관식"

            # 4. 객관식인데 선지 미검출
            if is_objective and (not q.choices or not q.choices.strip()):
                result["issues"].append({
                    "type": "OBJECTIVE_NO_CHOICES",
                    "detail": f"Q{qn}: 객관식인데 선지 없음"
                })

            # 5. 서술형으로 분류되었으나 정답이 ①~⑤ → 객관식 선지 미검출 의심 (분류 오류)
            if is_subjective and q.answer:
                ans = q.answer.strip()
                if ans in ("①", "②", "③", "④", "⑤") or (len(ans) == 1 and ans.isdigit()):
                    result["issues"].append({
                        "type": "LIKELY_OBJECTIVE_NO_CHOICES",
                        "detail": f"Q{qn}: 서술형으로 분류됐으나 정답이 번호형('{ans}') → 객관식 선지 미검출/분류오류 의심"
                    })

            # 6. 문제 본문 누락
            if not q.question_text or len(q.question_text.strip()) < 5:
                if "[MISSING]" not in (q.question_text or "") and "⚠️" not in (q.question_text or ""):
                    result["issues"].append({
                        "type": "EMPTY_QUESTION_TEXT",
                        "detail": f"Q{qn}: 출제문항 본문 너무 짧거나 없음 ('{q.question_text[:30] if q.question_text else ''}')"
                    })

            # 7. 두 문제 병합 의심 (passage가 비정상적으로 긴 경우)
            passage = q.question_passage or ""
            if len(passage) > 800:
                result["issues"].append({
                    "type": "SUSPECTED_MERGE",
                    "detail": f"Q{qn}: 문제지문이 비정상적으로 길음 ({len(passage)}자) — 병합 의심"
                })

            # 8. 보기 파싱 실패 (객관식인데 choices_list가 2개 미만)
            if is_objective and q.choices and len(q.choices_list) < 2:
                result["issues"].append({
                    "type": "CHOICES_PARSE_FAIL",
                    "detail": f"Q{qn}: 객관식 보기 텍스트 있으나 파싱된 선지 {len(q.choices_list)}개"
                })

            # 9. 정답 매핑 실패
            if not q.answer or not q.answer.strip():
                result["issues"].append({
                    "type": "NO_ANSWER",
                    "detail": f"Q{qn}: 정답 없음 (answer_source={q.answer_source})"
                })

    except Exception as e:
        result["parse_error"] = f"Exception: {str(e)}"
        result["issues"].append({
            "type": "EXCEPTION",
            "detail": traceback.format_exc()[-500:]
        })

    return result


def main():
    hwp_files = sorted([
        f for f in os.listdir(DATASET_DIR)
        if f.lower().endswith(".hwp")
    ])
    if FILE_LIMIT is not None:
        hwp_files = hwp_files[:FILE_LIMIT]

    total = len(hwp_files)
    print(f"=== 일괄 파싱 검증 시작: {total}개 파일 ===")
    print(f"시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    all_results = []
    issue_counter = defaultdict(int)
    parse_fail_count = 0
    files_with_issues = 0
    start_time = time.time()

    for idx, fname in enumerate(hwp_files, 1):
        filepath = os.path.join(DATASET_DIR, fname)
        elapsed = time.time() - start_time
        eta = (elapsed / idx) * (total - idx) if idx > 0 else 0

        print(f"[{idx}/{total}] {fname[:60]}...", end="", flush=True)

        file_start = time.time()
        result = validate_file(filepath, fname)
        file_elapsed = time.time() - file_start

        all_results.append(result)

        if not result["parse_success"]:
            parse_fail_count += 1
            print(f" FAIL ({file_elapsed:.1f}s) - {result['parse_error'][:60]}")
        elif result["issues"]:
            files_with_issues += 1
            for issue in result["issues"]:
                issue_counter[issue["type"]] += 1
            print(f" {len(result['issues'])} issues ({file_elapsed:.1f}s) [Q={result['total_questions']}]")
        else:
            print(f" OK ({file_elapsed:.1f}s) [Q={result['total_questions']}]")

        if idx % 50 == 0:
            print(f"  --- 진행: {idx}/{total}, 경과: {elapsed:.0f}s, ETA: {eta:.0f}s ---")

    total_elapsed = time.time() - start_time
    clean_count = total - parse_fail_count - files_with_issues

    # === 리포트 저장 ===
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    # === 요약 출력 ===
    summary_lines = [
        "=" * 70,
        f"  일괄 파싱 검증 결과 요약",
        f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  총 소요 시간: {total_elapsed:.0f}초 ({total_elapsed/60:.1f}분)",
        "=" * 70,
        "",
        f"  총 파일 수:        {total}",
        f"  파싱 성공 (이슈 없음): {clean_count}  ({clean_count/total*100:.1f}%)",
        f"  파싱 성공 (이슈 있음): {files_with_issues}  ({files_with_issues/total*100:.1f}%)",
        f"  파싱 실패:          {parse_fail_count}  ({parse_fail_count/total*100:.1f}%)",
        "",
        "  --- 이슈 유형별 발생 횟수 ---",
    ]

    for issue_type, count in sorted(issue_counter.items(), key=lambda x: -x[1]):
        label = {
            "NO_QUESTIONS": "문항 0건 추출",
            "DUPLICATE_NUMBERS": "문항번호 중복",
            "MISSING_NUMBERS": "문항번호 누락",
            "QUESTION_ANSWER_COUNT_MISMATCH": "문항수-정답수 불일치",
            "OBJECTIVE_NO_CHOICES": "객관식 선지 미검출",
            "LIKELY_OBJECTIVE_NO_CHOICES": "객관식 선지 미검출 의심 (서술형으로 분류됨)",
            "EMPTY_QUESTION_TEXT": "문제 본문 누락",
            "SUSPECTED_MERGE": "두 문제 병합 의심",
            "CHOICES_PARSE_FAIL": "보기 파싱 실패",
            "NO_ANSWER": "정답 매핑 실패",
            "EXCEPTION": "예외 발생",
        }.get(issue_type, issue_type)
        summary_lines.append(f"    {label:30s} : {count}건")

    # 파싱 실패 파일 목록
    fail_files = [r for r in all_results if not r["parse_success"]]
    if fail_files:
        summary_lines.append("")
        summary_lines.append(f"  --- 파싱 실패 파일 ({len(fail_files)}건) ---")
        for r in fail_files[:30]:
            summary_lines.append(f"    {r['filename'][:70]}")
            summary_lines.append(f"      → {r['parse_error'][:100]}")
        if len(fail_files) > 30:
            summary_lines.append(f"    ... 외 {len(fail_files)-30}건")

    # 이슈 많은 파일 TOP 20
    issue_files = sorted(
        [r for r in all_results if r["issues"]],
        key=lambda r: -len(r["issues"])
    )
    if issue_files:
        summary_lines.append("")
        summary_lines.append(f"  --- 이슈 많은 파일 TOP 20 ---")
        for r in issue_files[:20]:
            types = defaultdict(int)
            for iss in r["issues"]:
                types[iss["type"]] += 1
            type_str = ", ".join(f"{k}({v})" for k, v in types.items())
            summary_lines.append(f"    [{len(r['issues'])}건] {r['filename'][:60]}")
            summary_lines.append(f"           {type_str}")

    summary_lines.append("")
    summary_lines.append("=" * 70)

    summary_text = "\n".join(summary_lines)
    print(summary_text)

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write(summary_text)

    print(f"\n상세 리포트: {REPORT_PATH}")
    print(f"요약 리포트: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()

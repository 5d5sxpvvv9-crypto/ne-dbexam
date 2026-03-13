"use client";

import React, { useState, useCallback, useRef, useEffect } from "react";

// ── 타입 정의 (9열 구조) ──
interface FileTask {
  task_id: string;
  filename: string;
  status: "queued" | "processing" | "completed" | "failed" | "rejected";
  total_questions: number;
  error: string | null;
  warnings: string[];
  metadata: Record<string, unknown>;
  parse_method?: string;
  parse_time_ms?: number;
}

interface Question {
  question_number: number;
  question_text: string;
  common_passage: string;
  question_passage: string;
  choices: string;
  answer: string;
  question_type: string;       // Vocabulary | Reading/Comprehension | Grammar | Listening
  question_format: string;     // 객관식 | 서술형
  confidence: number;
  notes: string;
  passage_group_id: number | null;
  raw_block_text: string;
  school: string;
  grade: number;
  // v2.0 강화 필드
  seq_no: number;
  raw_no: number | null;
  answer_source: string;       // answer_key | inline | missing
  source_block_ids: number[];
  item_warnings: string[];
  choices_list: string[];
}

// 키 컬러
const PRIMARY_COLOR = "#E83828";

// 문제유형 뱃지 색상
const TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  Grammar: { bg: "#FEF3C7", text: "#92400E" },
  Vocabulary: { bg: "#DBEAFE", text: "#1E40AF" },
  "Reading/Comprehension": { bg: "#D1FAE5", text: "#065F46" },
  Listening: { bg: "#EDE9FE", text: "#5B21B6" },
};

export default function HomePage() {
  const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";
  const [tasks, setTasks] = useState<FileTask[]>([]);
  const [previewQuestions, setPreviewQuestions] = useState<Question[]>([]);
  const [detailQuestion, setDetailQuestion] = useState<Question | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const tasksRef = useRef<FileTask[]>([]);
  tasksRef.current = tasks;                          // 항상 최신 tasks를 ref에 동기화
  const fetchedTaskIdsRef = useRef<Set<string>>(new Set());  // questions를 이미 fetch한 taskId

  // ── 파일 업로드 ──
  const uploadFiles = useCallback(async (files: FileList | File[]) => {
    const formData = new FormData();
    const fileArray = Array.from(files);
    fileArray.forEach((f) => formData.append("files", f));

    setIsAnalyzing(true);
    try {
      const reqId = crypto.randomUUID();
      console.log("[upload] start", reqId);
      const res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.files) {
        const newTasks: FileTask[] = data.files.map((f: { task_id: string; filename: string; status: string; error?: string }) => ({
          task_id: f.task_id,
          filename: f.filename,
          status: f.status,
          total_questions: 0,
          error: f.error || null,
          warnings: [],
          metadata: {},
        }));
        setTasks((prev) => [...prev, ...newTasks.filter((t: FileTask) => t.task_id)]);
      } else {
        // 서버가 files를 반환하지 않은 경우 즉시 해제
        setIsAnalyzing(false);
      }
    } catch (err) {
      console.error("업로드 실패:", err);
      alert("파일 업로드에 실패했습니다. 서버 연결을 확인해주세요.");
      setIsAnalyzing(false);
    }
  }, []);

  // ── 상태 폴링 ──
  // 의존성: pendingTaskIds (문자열) — tasks 객체 자체가 아닌 "아직 처리 중인 ID 목록"만 추적
  const pendingTaskIds = tasks
    .filter((t) => t.status === "queued" || t.status === "processing")
    .map((t) => t.task_id)
    .join(",");

  useEffect(() => {
    // ★ 폴링 대상이 0이면 interval을 생성하지 않음 (요구사항 6)
    if (!pendingTaskIds) {
      console.log("[polling] 대상 없음 — interval 미생성");
      setIsAnalyzing(false);
      return;
    }

    if (pollingRef.current) clearInterval(pollingRef.current);
    pollingRef.current = setInterval(async () => {
      // ref에서 최신 tasks를 읽어 pending 목록 확인 (요구사항 5)
      const currentTasks = tasksRef.current;
      const pending = currentTasks.filter(
        (t) => t.status === "queued" || t.status === "processing"
      );

      // 모두 완료됐으면 interval 자체를 정리
      if (pending.length === 0) {
        console.log("[polling] pending 0 → interval 정리");
        if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
        return;
      }

      for (const task of pending) {
        try {
          const res = await fetch(`${API_BASE}/api/status/${task.task_id}`);
          const data = await res.json();

          // completed 또는 failed → 상태 확정 (요구사항 3, 5)
          if (data.status === "completed" || data.status === "failed") {
            setTasks((prev) =>
              prev.map((t) =>
                t.task_id === task.task_id
                  ? { ...t, status: data.status, total_questions: data.total_questions || 0, error: data.error || null }
                  : t
              )
            );

            // ★ completed + 아직 fetch하지 않은 taskId일 때만 1회 fetch (요구사항 1, 2, 3)
            if (
              data.status === "completed" &&
              data.total_questions > 0 &&
              !fetchedTaskIdsRef.current.has(task.task_id)
            ) {
              fetchedTaskIdsRef.current.add(task.task_id);   // 선점(fetch 전에 등록)
              console.log(`[questions] fetch 시작 — taskId=${task.task_id} (최초 1회)`);

              try {
                const qRes = await fetch(`${API_BASE}/api/questions/${task.task_id}`);
                const qData = await qRes.json();
                if (qData.questions?.length > 0) {
                  // ★ 덮어쓰기: 동일 taskId 문항은 교체, 다른 taskId 문항은 유지 (요구사항 4)
                  setPreviewQuestions((prev) => {
                    const incomingNumbers = new Set(
                      qData.questions.map((q: Question) => `${task.task_id}_${q.question_number}`)
                    );
                    const kept = prev.filter(
                      (q) => !incomingNumbers.has(`${task.task_id}_${q.question_number}`)
                    );
                    return [...kept, ...qData.questions];
                  });
                  console.log(`[questions] fetch 완료 — taskId=${task.task_id}, ${qData.questions.length}문항`);
                }
              } catch {
                // fetch 실패 시 재시도할 수 있도록 Set에서 제거
                fetchedTaskIdsRef.current.delete(task.task_id);
                console.warn(`[questions] fetch 실패 — taskId=${task.task_id} (다음 폴링에서 재시도)`);
              }
            } else if (fetchedTaskIdsRef.current.has(task.task_id)) {
              // ★ 이미 fetch한 taskId가 다시 도달한 경우 — 검증 로그 (요구사항 7)
              console.log(`[questions] SKIP — taskId=${task.task_id} 이미 fetch 완료`);
            }
          }
        } catch {
          // 네트워크 에러 — 다음 폴링에서 재시도
        }
      }
    }, 1500);

    return () => {
      if (pollingRef.current) { clearInterval(pollingRef.current); pollingRef.current = null; }
    };
  }, [pendingTaskIds]);

  // ── 드래그&드롭 ──
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);
  const handleDragLeave = useCallback(() => setIsDragging(false), []);
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files.length > 0) {
        uploadFiles(e.dataTransfer.files);
      }
    },
    [uploadFiles]
  );

  // ── 엑셀 다운로드 ──
  const exportExcel = useCallback(async () => {
    setIsExporting(true);
    try {
      const completedIds = tasks.filter((t) => t.status === "completed").map((t) => t.task_id);
      const res = await fetch(`${API_BASE}/api/export/excel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(completedIds),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "엑셀 생성 실패");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `exam_questions_${new Date().toISOString().slice(0, 10)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error("엑셀 다운로드 실패:", err);
      alert(`엑셀 다운로드 실패: ${err}`);
    } finally {
      setIsExporting(false);
    }
  }, [tasks]);

  const totalQuestions = previewQuestions.length || tasks.reduce((sum, t) => sum + (t.total_questions || 0), 0);

  return (
    <div className="min-h-screen bg-gray-50" onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
      {/* 드래그 오버레이 */}
      {isDragging && (
        <div className="fixed inset-0 bg-white/90 backdrop-blur-sm z-50 flex items-center justify-center border-4 border-dashed" style={{ borderColor: PRIMARY_COLOR }}>
          <div className="text-center">
            <div className="text-6xl mb-4">📄</div>
            <div className="text-2xl font-semibold" style={{ color: PRIMARY_COLOR }}>HWP 파일을 여기에 놓으세요</div>
          </div>
        </div>
      )}

      {/* 헤더 */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-6 py-5">
          <div className="flex items-center gap-4 mb-3">
            <div className="w-32 h-10 relative">
              <img src="/logo.svg" alt="NE 능률" className="h-full w-auto object-contain" />
            </div>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mb-1">내신기출문제 분석 DB생성</h1>
          <p className="text-sm text-gray-600">HWP 파일을 엑셀 데이터베이스로 즉시 변환합니다.</p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-8">
        {/* ── 업로드 영역 ── */}
        <div
          onClick={() => !isAnalyzing && fileInputRef.current?.click()}
          className={`relative border-2 border-dashed border-gray-300 rounded-xl p-12 text-center mb-8
                     transition-all bg-white ${isAnalyzing ? "cursor-not-allowed opacity-80" : "hover:border-gray-400 hover:bg-gray-50/50 cursor-pointer group"}`}
        >
          <div className="flex flex-col items-center justify-center">
            <svg className="w-16 h-16 mb-4 group-hover:scale-110 transition-transform" style={{ color: PRIMARY_COLOR }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <h3 className="text-lg font-semibold text-gray-800 mb-2">
              HWP 파일을 드래그하거나 클릭하여 업로드하세요
            </h3>
            <p className="text-sm text-gray-500">분석할 내신 기출문제 파일을 선택해 주세요 (.hwp, .hwpx)</p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".hwp,.hwpx"
            multiple
            className="hidden"
            disabled={isAnalyzing}
            onChange={(e) => e.target.files && uploadFiles(e.target.files)}
          />
          {isAnalyzing && (
            <div className="absolute inset-0 flex items-center justify-center rounded-xl bg-white/70 backdrop-blur-sm">
              <div className="h-12 w-12 animate-spin rounded-full border-4 border-gray-200 border-t-blue-600" />
            </div>
          )}
        </div>

        {/* ── 처리 상태 표시 ── */}
        {tasks.length > 0 && (
          <div className="mb-6 flex flex-wrap gap-2">
            {tasks.map((task) => (
              <div
                key={task.task_id}
                className="text-xs px-3 py-1.5 rounded-full bg-white border border-gray-200 flex items-center gap-2"
              >
                <span className={task.status === "completed" ? "text-green-600" : task.status === "processing" ? "text-blue-600" : "text-gray-600"}>
                  {task.status === "completed" ? "✓" : task.status === "processing" ? "⟳" : "○"}
                </span>
                <span className="text-gray-700 truncate max-w-[200px]">{task.filename}</span>
                {task.status === "completed" && task.total_questions > 0 && (
                  <span className="text-green-600 font-medium">{task.total_questions}문항</span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* ── 데이터 테이블 (9열) ── */}
        {previewQuestions.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 shadow-sm overflow-hidden mb-6">
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 bg-gray-50">
              <div className="flex items-center gap-3">
                <svg className="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="text-sm text-gray-700 font-medium">
                  총 {totalQuestions}개의 문항이 성공적으로 분석되었습니다.
                </span>
              </div>
              <button
                onClick={exportExcel}
                disabled={isExporting}
                className="px-5 py-2 text-white rounded-lg font-semibold text-sm
                           hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed
                           transition-all flex items-center gap-2 shadow-sm"
                style={{ backgroundColor: PRIMARY_COLOR }}
              >
                {isExporting ? (
                  <>
                    <svg className="spinner w-4 h-4" viewBox="0 0 24 24" fill="none">
                      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="60" strokeLinecap="round" />
                    </svg>
                    생성 중...
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Excel 다운로드
                  </>
                )}
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600 uppercase w-12">번호</th>
                    <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600 uppercase w-16">학교</th>
                    <th className="px-3 py-3 text-center text-xs font-semibold text-gray-600 uppercase w-12">학년</th>
                    <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600 uppercase" style={{ minWidth: 200 }}>출제문항</th>
                    <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600 uppercase" style={{ minWidth: 200 }}>공통지문</th>
                    <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600 uppercase" style={{ minWidth: 200 }}>문제지문</th>
                    <th className="px-3 py-3 text-left text-xs font-semibold text-gray-600 uppercase" style={{ minWidth: 180 }}>보기/조건</th>
                    <th className="px-3 py-3 text-center text-xs font-semibold text-gray-600 uppercase w-16">정답</th>
                    <th className="px-3 py-3 text-center text-xs font-semibold text-gray-600 uppercase w-28">문제유형</th>
                    <th className="px-3 py-3 text-center text-xs font-semibold text-gray-600 uppercase w-20">문항형태</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {previewQuestions.map((q, idx) => {
                    const typeStyle = TYPE_COLORS[q.question_type] || { bg: "#F3F4F6", text: "#374151" };
                    return (
                      <tr key={idx} className="hover:bg-gray-50 transition-colors cursor-pointer" onClick={() => setDetailQuestion(q)}>
                        <td className="px-3 py-3 text-gray-700 font-medium">{q.question_number}</td>
                        <td className="px-3 py-3 text-gray-700 text-xs">{q.school?.replace("학교", "") || "-"}</td>
                        <td className="px-3 py-3 text-center text-gray-700">{q.grade || "-"}</td>
                        <td className="px-3 py-3 whitespace-pre-line text-gray-800 text-xs leading-relaxed">
                          {q.question_text ? (q.question_text.length > 80 ? q.question_text.slice(0, 80) + "…" : q.question_text) : "-"}
                        </td>
                        <td className="px-3 py-3 whitespace-pre-line text-gray-700 text-xs leading-relaxed">
                          {q.common_passage ? (q.common_passage.length > 60 ? q.common_passage.slice(0, 60) + "…" : q.common_passage) : "-"}
                        </td>
                        <td className="px-3 py-3 whitespace-pre-line text-gray-700 text-xs leading-relaxed">
                          {q.question_passage ? (q.question_passage.length > 60 ? q.question_passage.slice(0, 60) + "…" : q.question_passage) : "-"}
                        </td>
                        <td className="px-3 py-3 whitespace-pre-line text-gray-700 text-xs leading-relaxed">
                          {q.choices ? (q.choices.length > 60 ? q.choices.slice(0, 60) + "…" : q.choices) : "-"}
                        </td>
                        <td className="px-3 py-3 text-center text-gray-700 font-medium">{q.answer || "-"}</td>
                        <td className="px-3 py-3 text-center">
                          <span
                            className="inline-block text-xs px-2 py-0.5 rounded-full font-medium"
                            style={{ backgroundColor: typeStyle.bg, color: typeStyle.text }}
                          >
                            {q.question_type || "-"}
                          </span>
                        </td>
                        <td className="px-3 py-3 text-center">
                          <span
                            className={`inline-block text-xs px-2 py-0.5 rounded-full font-medium ${
                              q.question_format === "서술형"
                                ? "bg-orange-100 text-orange-700"
                                : "bg-blue-100 text-blue-700"
                            }`}
                          >
                            {q.question_format || "-"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── 빈 상태 ── */}
        {tasks.length === 0 && previewQuestions.length === 0 && (
          <div className="text-center py-20 text-gray-400">
            <div className="text-6xl mb-4">📄</div>
            <h3 className="text-lg font-medium text-gray-500">아직 업로드된 파일이 없습니다</h3>
            <p className="text-sm mt-2">HWP 영어시험 파일을 위 영역에 드래그하거나 클릭하여 업로드하세요</p>
          </div>
        )}
      </main>

      {/* ── 상세 보기 모달 ── */}
      {detailQuestion && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setDetailQuestion(null)}>
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-gray-50 sticky top-0">
              <div className="flex items-center gap-3">
                <h3 className="font-bold text-lg text-gray-900">
                  문항 {detailQuestion.question_number}번 상세
                </h3>
                <span
                  className="text-xs px-2 py-0.5 rounded-full font-medium"
                  style={{
                    backgroundColor: (TYPE_COLORS[detailQuestion.question_type] || { bg: "#F3F4F6" }).bg,
                    color: (TYPE_COLORS[detailQuestion.question_type] || { text: "#374151" }).text,
                  }}
                >
                  {detailQuestion.question_type}
                </span>
              </div>
              <button
                onClick={() => setDetailQuestion(null)}
                className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
              >
                ×
              </button>
            </div>
            <div className="p-6 space-y-5">
              <DetailSection title="출제문항" content={detailQuestion.question_text} />
              <DetailSection title="공통지문" content={detailQuestion.common_passage} />
              <DetailSection title="문제지문" content={detailQuestion.question_passage} />
              <DetailSection title="보기/조건" content={detailQuestion.choices} />
              <div className="grid grid-cols-4 gap-4">
                <DetailSection title="정답" content={detailQuestion.answer} />
                <DetailSection title="문제유형" content={detailQuestion.question_type} />
                <DetailSection title="문항형태" content={detailQuestion.question_format} />
                <DetailSection title="학교 / 학년" content={`${detailQuestion.school || "-"} / ${detailQuestion.grade || "-"}`} />
              </div>
              <div className="grid grid-cols-3 gap-4">
                <DetailSection title="정답 출처" content={detailQuestion.answer_source || "missing"} />
                <DetailSection title="seq / raw" content={`seq=${detailQuestion.seq_no ?? '-'} / raw=${detailQuestion.raw_no ?? '-'}`} />
                <DetailSection title="소스 블록" content={detailQuestion.source_block_ids?.length ? detailQuestion.source_block_ids.join(', ') : '-'} />
              </div>
              <DetailSection title="분류 근거" content={detailQuestion.notes} />
              {detailQuestion.item_warnings && detailQuestion.item_warnings.length > 0 && (
                <DetailSection title="⚠️ 문항 경고" content={detailQuestion.item_warnings.join('\n')} highlight />
              )}
              <DetailSection title="원문 블록" content={detailQuestion.raw_block_text} highlight />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DetailSection({ title, content, highlight }: { title: string; content: string; highlight?: boolean }) {
  if (!content) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">{title}</h4>
      <div
        className={`whitespace-pre-line text-sm leading-relaxed p-4 rounded-lg border ${
          highlight ? "bg-amber-50 border-amber-200 text-amber-900" : "bg-gray-50 border-gray-200 text-gray-800"
        }`}
      >
        {content}
      </div>
    </div>
  );
}

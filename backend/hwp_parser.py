"""
HWP 파일 텍스트 추출 모듈
1순위: Hancom COM 자동화 (Windows + 한컴 오피스 설치 필요)
2순위: olefile 기반 바이너리 파싱 (한컴 미설치 시)
"""

import os
import re
import sys
import struct
import zlib
import tempfile
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
_ENDNOTE_AUTONUM_PREFIX = re.compile(r"^\d+\)\s*")


@dataclass
class TextBlock:
    """텍스트 블록 단위"""
    text: str
    block_type: str = "paragraph"
    index: int = 0
    raw_text: str = ""


@dataclass
class HwpParseResult:
    """HWP 파싱 결과"""
    success: bool
    text_blocks: List[TextBlock] = field(default_factory=list)
    full_text: str = ""
    method_used: str = ""
    error: str = ""
    parse_time_ms: int = 0
    metadata: Dict = field(default_factory=dict)
    endnote_answers: List[Tuple[str, str]] = field(default_factory=list)


def _extract_text_from_hwp_legacy(filepath: str) -> HwpParseResult:
    """[내부용] COM/olefile 텍스트 추출 (endnote 미포함)"""
    start = time.time()
    filepath = os.path.abspath(filepath)

    if not os.path.exists(filepath):
        return HwpParseResult(success=False, error=f"파일을 찾을 수 없습니다: {filepath}")

    result = _try_com_extraction(filepath)
    if result.success:
        result.parse_time_ms = int((time.time() - start) * 1000)
        return result

    logger.warning(f"COM 추출 실패: {result.error}. olefile 파싱 시도합니다.")

    result = _try_olefile_extraction(filepath)
    result.parse_time_ms = int((time.time() - start) * 1000)
    return result


def _try_com_extraction(filepath: str) -> HwpParseResult:
    """Hancom COM 자동화로 텍스트 추출"""
    try:
        import win32com.client
        import pythoncom
    except ImportError:
        return HwpParseResult(success=False, error="pywin32 모듈이 설치되지 않았습니다.", method_used="com")

    hwp = None
    try:
        pythoncom.CoInitialize()
        hwp = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
        hwp.XHwpWindows.Item(0).Visible = False

        # 보안 모듈 등록
        hwp.RegisterModule("FilePathCheckDLL", "SecurityModule")

        if not hwp.Open(filepath, "HWP", "forceopen:true"):
            return HwpParseResult(success=False, error="HWP 파일 열기 실패", method_used="com")

        # GetText로 순차 추출
        text_blocks = []
        block_idx = 0

        hwp.InitScan(Range=0x0077, Option=0x0001)
        current_para = []
        while True:
            try:
                result = hwp.GetText()
                if result is None:
                    break
                state = result[0]
                text = result[1] if len(result) > 1 else ""

                if state == 0:
                    break
                if state == 1:
                    if text and text.strip():
                        current_para.append(text)
                    if current_para:
                        para_text = "".join(current_para)
                        if para_text.strip():
                            text_blocks.append(TextBlock(
                                text=para_text.strip(),
                                block_type="paragraph",
                                index=block_idx,
                                raw_text=para_text
                            ))
                            block_idx += 1
                        current_para = []
                elif state >= 2:
                    if text:
                        current_para.append(text)
            except Exception as e:
                logger.debug(f"GetText 반복 중 오류: {e}")
                break

        hwp.ReleaseScan()

        if current_para:
            para_text = "".join(current_para)
            if para_text.strip():
                text_blocks.append(TextBlock(
                    text=para_text.strip(),
                    block_type="paragraph",
                    index=block_idx,
                    raw_text=para_text
                ))

        # 텍스트 부족 시 SaveAs TEXT 시도
        total_text = " ".join(b.text for b in text_blocks)
        if len(total_text) < 100:
            text_blocks = _com_save_as_text(hwp, filepath)

        full_text = "\n".join(b.text for b in text_blocks)

        hwp.Clear()
        hwp.Quit()
        pythoncom.CoUninitialize()

        if not text_blocks:
            return HwpParseResult(success=False, error="추출된 텍스트가 없습니다.", method_used="com")

        return HwpParseResult(
            success=True,
            text_blocks=text_blocks,
            full_text=full_text,
            method_used="com"
        )

    except Exception as e:
        error_msg = f"COM 자동화 오류: {str(e)}"
        logger.error(error_msg)
        try:
            if hwp:
                hwp.Quit()
        except:
            pass
        try:
            pythoncom.CoUninitialize()
        except:
            pass
        return HwpParseResult(success=False, error=error_msg, method_used="com")


def _com_save_as_text(hwp, filepath: str) -> List[TextBlock]:
    """COM SaveAs TEXT 방법으로 텍스트 추출"""
    temp_dir = tempfile.mkdtemp()
    temp_txt = os.path.join(temp_dir, "output.txt")
    text_blocks = []

    try:
        act = hwp.HAction
        pset = hwp.HParameterSet
        act.GetDefault("FileSaveAs_S", pset.HFileOpenSave.HSet)
        pset.HFileOpenSave.filename = temp_txt
        pset.HFileOpenSave.Format = "TEXT"
        act.Execute("FileSaveAs_S", pset.HFileOpenSave.HSet)

        text = ""
        for encoding in ['utf-8', 'cp949', 'euc-kr', 'utf-16']:
            try:
                with open(temp_txt, 'r', encoding=encoding) as f:
                    text = f.read()
                if text and len(text) > 10:
                    break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if text:
            paragraphs = text.split('\n')
            for idx, para in enumerate(paragraphs):
                if para.strip():
                    text_blocks.append(TextBlock(
                        text=para.strip(),
                        block_type="paragraph",
                        index=idx,
                        raw_text=para
                    ))
    except Exception as e:
        logger.error(f"SaveAs TEXT 실패: {e}")
    finally:
        try:
            os.remove(temp_txt)
            os.rmdir(temp_dir)
        except:
            pass

    return text_blocks


def _try_olefile_extraction(filepath: str) -> HwpParseResult:
    """olefile을 이용한 HWP 바이너리 직접 파싱"""
    try:
        import olefile
    except ImportError:
        return HwpParseResult(
            success=False,
            error="olefile 모듈이 설치되지 않았습니다.",
            method_used="olefile"
        )

    try:
        if not olefile.isOleFile(filepath):
            return HwpParseResult(
                success=False,
                error="유효한 HWP(OLE) 파일이 아닙니다.",
                method_used="olefile"
            )

        ole = olefile.OleFileIO(filepath)

        # FileHeader에서 플래그 확인
        header_data = ole.openstream("FileHeader").read()
        properties = struct.unpack_from('<I', header_data, 36)[0]
        is_compressed = bool(properties & 0x01)
        is_encrypted = bool(properties & 0x02)

        if is_encrypted:
            ole.close()
            return HwpParseResult(
                success=False,
                error="암호화된 HWP 파일은 지원하지 않습니다.",
                method_used="olefile"
            )

        # BodyText 섹션에서 텍스트 추출
        all_paragraphs: List[str] = []
        section_idx = 0

        while True:
            stream_name = f"BodyText/Section{section_idx}"
            if not ole.exists(stream_name):
                break

            section_data = ole.openstream(stream_name).read()
            if is_compressed:
                try:
                    section_data = zlib.decompress(section_data, -15)
                except zlib.error:
                    try:
                        section_data = zlib.decompress(section_data)
                    except zlib.error as e:
                        logger.warning(f"Section{section_idx} 압축 해제 실패: {e}")
                        section_idx += 1
                        continue

            paragraphs = _parse_section_records(section_data)
            all_paragraphs.extend(paragraphs)
            section_idx += 1

        ole.close()

        if not all_paragraphs:
            return HwpParseResult(
                success=False,
                error="텍스트를 추출할 수 없습니다.",
                method_used="olefile"
            )

        text_blocks = []
        for idx, para in enumerate(all_paragraphs):
            if para.strip():
                text_blocks.append(TextBlock(
                    text=para.strip(),
                    block_type="paragraph",
                    index=idx,
                    raw_text=para
                ))

        full_text = "\n".join(b.text for b in text_blocks)

        return HwpParseResult(
            success=True,
            text_blocks=text_blocks,
            full_text=full_text,
            method_used="olefile"
        )

    except Exception as e:
        return HwpParseResult(
            success=False,
            error=f"olefile 파싱 오류: {str(e)}",
            method_used="olefile"
        )


def _parse_section_records(data: bytes) -> List[str]:
    """HWP 섹션 레코드를 파싱하여 텍스트 추출"""
    HWPTAG_BEGIN = 0x010
    HWPTAG_PARA_TEXT = HWPTAG_BEGIN + 51  # 67

    paragraphs = []
    offset = 0

    while offset < len(data):
        if offset + 4 > len(data):
            break

        header = struct.unpack_from('<I', data, offset)[0]
        tag_id = header & 0x3FF
        size = (header >> 20) & 0xFFF
        offset += 4

        if size == 0xFFF:
            if offset + 4 > len(data):
                break
            size = struct.unpack_from('<I', data, offset)[0]
            offset += 4

        if offset + size > len(data):
            break

        record_data = data[offset:offset + size]
        offset += size

        if tag_id == HWPTAG_PARA_TEXT:
            text = _extract_para_text(record_data)
            if text.strip():
                paragraphs.append(text)

    return paragraphs


def _extract_para_text(data: bytes) -> str:
    """HWPTAG_PARA_TEXT 레코드에서 텍스트 추출

    HWP 5.0 바이너리 형식:
    - 일반 문자 (code >= 32): 2바이트 (UTF-16LE)
    - 줄바꿈 (code == 10): 2바이트
    - 문단끝 (code == 13): 2바이트
    - 제어 문자 (code 0-9, 11-31 except 10,13): 16바이트
      (2바이트 코드 + 12바이트 확장 데이터 + 2바이트 종료)
    """
    chars = []
    i = 0
    data_len = len(data)

    while i < data_len:
        if i + 1 >= data_len:
            break

        code = data[i] | (data[i + 1] << 8)

        if code == 10:
            # 줄바꿈
            chars.append('\n')
            i += 2
        elif code == 13:
            # 문단 끝
            i += 2
        elif code < 32:
            # 모든 제어 문자: 16바이트 (코드 2 + 확장데이터 12 + 종료 2)
            i += 16
        else:
            chars.append(chr(code))
            i += 2

    return ''.join(chars)


def _extract_endnote_answers(filepath: str) -> List[Tuple[str, str]]:
    """pyhwp(hwp5proc)를 이용하여 HWP 미주(endnote) 정답을 구조적으로 추출.

    HWP 시험지의 정답은 대부분 미주(endnote)로 삽입되어 마지막 페이지에
    '정답' 영역으로 렌더링된다. olefile 바이너리 파싱으로는 미주 텍스트를
    문단 텍스트와 분리할 수 없으므로, pyhwp XML 파싱으로 정확한 매핑을 수행한다.

    Returns:
        [(parent_paragraph_text, endnote_answer_text), ...]
        pyhwp 미설치 또는 파싱 실패 시 빈 리스트 반환.
    """
    import shutil
    import subprocess

    hwp5proc = shutil.which("hwp5proc")
    if not hwp5proc:
        for candidate in [
            os.path.join(sys.prefix, "Scripts", "hwp5proc.exe"),
            os.path.join(os.path.dirname(sys.executable), "Scripts", "hwp5proc.exe"),
            r"C:\Users\sunny0323\AppData\Local\Python\pythoncore-3.14-64\Scripts\hwp5proc.exe",
        ]:
            if os.path.isfile(candidate):
                hwp5proc = candidate
                break
    if not hwp5proc:
        logger.debug("hwp5proc 미발견 — 미주 추출 건너뜀")
        return []

    try:
        proc = subprocess.run(
            [hwp5proc, "xml", filepath],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0 or not proc.stdout:
            logger.debug(f"hwp5proc 실패: code={proc.returncode}, stdout={len(proc.stdout or b'')}B")
            return []
    except subprocess.TimeoutExpired:
        logger.warning(f"hwp5proc 타임아웃 (120s)")
        return []
    except Exception as e:
        logger.debug(f"hwp5proc 실행 실패: {e}")
        return []

    try:
        import lxml.etree as ET
    except ImportError:
        logger.debug("lxml 미설치 — 미주 추출 건너뜀")
        return []

    try:
        root = ET.fromstring(proc.stdout)
    except ET.XMLSyntaxError as e:
        logger.debug(f"hwp5proc XML 파싱 오류: {e}")
        return []

    results: List[Tuple[str, str]] = []

    def _get_tag(elem) -> str:
        t = elem.tag
        return t.split("}")[-1] if "}" in t else t

    def _collect_text_excluding(elem, exclude_set):
        """elem 하위 텍스트를 수집하되 exclude_set에 있는 요소의 하위는 건너뜀"""
        parts = []
        if elem.text and elem not in exclude_set:
            parts.append(elem.text)
        for child in elem:
            if child in exclude_set or _get_tag(child) == "EndNote":
                if child.tail:
                    parts.append(child.tail)
                continue
            parts.extend(_collect_text_excluding(child, exclude_set))
            if child.tail:
                parts.append(child.tail)
        return parts

    for endnote in root.iter():
        if _get_tag(endnote) != "EndNote":
            continue

        en_text = "".join(endnote.itertext()).strip()
        # AutoNumbering 텍스트 제거 (예: "1) ③" → "③")
        en_text = _ENDNOTE_AUTONUM_PREFIX.sub("", en_text).strip()
        if not en_text:
            continue

        parent_para = endnote.getparent()
        while parent_para is not None:
            if _get_tag(parent_para) == "Paragraph":
                break
            parent_para = parent_para.getparent()

        para_text = ""
        if parent_para is not None:
            text_parts = _collect_text_excluding(parent_para, {endnote})
            para_text = "".join(text_parts).strip()

        results.append((para_text, en_text))

    if results:
        logger.info(f"미주(endnote) 정답 {len(results)}개 추출 성공")
    return results


def extract_text_from_hwp(filepath: str) -> HwpParseResult:
    """HWP 파일에서 텍스트 추출 (COM → olefile) + 미주(endnote) 정답 추출"""
    start = time.time()
    filepath = os.path.abspath(filepath)

    result = _extract_text_from_hwp_legacy(filepath)
    if result.success:
        result.endnote_answers = _extract_endnote_answers(filepath)
    result.parse_time_ms = int((time.time() - start) * 1000)
    return result


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) < 2:
        print("사용법: python hwp_parser.py <HWP파일경로>")
        _sys.exit(1)

    logging.basicConfig(level=logging.DEBUG)
    result = extract_text_from_hwp(_sys.argv[1])
    print(f"성공: {result.success}")
    print(f"방법: {result.method_used}")
    print(f"추출 시간: {result.parse_time_ms}ms")
    print(f"블록 수: {len(result.text_blocks)}")
    print(f"미주 정답: {len(result.endnote_answers)}개")

    if result.success:
        print("\n--- 전체 텍스트 ---")
        print(result.full_text[:3000])
        if result.endnote_answers:
            print("\n--- 미주 정답 ---")
            for para, ans in result.endnote_answers:
                print(f"  [{para[:60]}] → {ans}")
    else:
        print(f"오류: {result.error}")

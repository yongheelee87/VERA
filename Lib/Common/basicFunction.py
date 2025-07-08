from logging.config import dictConfig
import logging
import pandas as pd
import pygetwindow as gw
import os
import csv
import struct
import pickle
from typing import List, Tuple, Union, Any, Optional
from pathlib import Path

# 상수 정의
DEFAULT_ENCODINGS = ['utf-8', 'cp949', 'cp1252', 'euc-kr']
LOG_CONFIG = {
    'version': 1,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(message)s',
        },
        'simple': {
            'format': '%(message)s',
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "simple",
        },
        "info_file_handler": {
            "class": "logging.FileHandler",
            "level": "INFO",
            "formatter": "default",
            "encoding": "utf-8",
            "filename": "./data/result/Debug.log"
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ["console", "info_file_handler"]
    }
}


def to_raw(string: str) -> str:
    """
    문자열을 raw string으로 변환

    Args:
        string: 변환할 문자열

    Returns:
        str: raw string
    """
    return rf'{string}'


def to_hex_str(integerVariable: int) -> str:
    """
    정수를 16진수 문자열로 변환

    Args:
        integerVariable: 변환할 정수

    Returns:
        str: 16진수 문자열 (예: "0x2A")
    """
    return f"0x{integerVariable:02X}"


def float_to_hex(f: float) -> str:
    """
    float 값을 16진수 문자열로 변환

    Args:
        f: 변환할 float 값

    Returns:
        str: 16진수 문자열

    Raises:
        struct.error: 변환 실패 시
    """
    try:
        return hex(struct.unpack('<I', struct.pack('<f', f))[0])
    except struct.error as e:
        raise ValueError(f"Float to hex conversion failed for value {f}: {e}")


def hex_to_float(h: str) -> float:
    """
    16진수 문자열을 float 값으로 변환

    Args:
        h: 16진수 문자열

    Returns:
        float: 변환된 float 값

    Raises:
        ValueError: 변환 실패 시
    """
    try:
        return struct.unpack('<f', struct.pack('i', int(h, 16)))[0]
    except (ValueError, struct.error) as e:
        raise ValueError(f"Hex to float conversion failed for value {h}: {e}")


def _convert_to_hex_bytes(in_val: Union[str, int, float]) -> List[int]:
    """
    입력값을 16진수 바이트 리스트로 변환하는 헬퍼 함수

    Args:
        in_val: 변환할 값

    Returns:
        List[int]: 16진수 바이트 리스트
    """
    str_val = str(in_val)

    # float 값 처리
    if '.' in str_val:
        str_val = str(float_to_hex(float(str_val)))

    # 16진수 문자열 생성
    hex_str = to_hex_str(int(str_val, 0)).replace('0x', '')

    # 홀수 길이 처리
    if len(hex_str) % 2 != 0:
        hex_str = f'0{hex_str}'

    return list(bytes.fromhex(hex_str))


def to_hex_little_lst(in_val: Union[str, int, float]) -> List[int]:
    """
    입력값을 리틀 엔디안 바이트 리스트로 변환

    Args:
        in_val: 변환할 값

    Returns:
        List[int]: 리틀 엔디안 바이트 리스트
    """
    return _convert_to_hex_bytes(in_val)[::-1]


def to_hex_big_lst(in_val: Union[str, int, float]) -> List[int]:
    """
    입력값을 빅 엔디안 바이트 리스트로 변환

    Args:
        in_val: 변환할 값

    Returns:
        List[int]: 빅 엔디안 바이트 리스트
    """
    return _convert_to_hex_bytes(in_val)


def bytearray_to_hex(arr: Union[bytearray, List[int]]) -> str:
    """
    바이트 배열을 16진수 문자열로 변환

    Args:
        arr: 바이트 배열

    Returns:
        str: 16진수 문자열
    """
    return '0x' + ''.join(f'{x:02x}' for x in arr)


def isdir_and_make(dir_name: str) -> None:
    """
    디렉토리 존재 확인 및 생성

    Args:
        dir_name: 디렉토리 경로
    """
    dir_path = Path(dir_name)

    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"Success: Create {dir_name}\n")
    else:
        print(f"Success: Access {dir_name}\n")


def check_process_open(keyword: str) -> bool:
    """
    지정된 키워드를 포함한 윈도우 프로세스가 열려있는지 확인

    Args:
        keyword: 검색할 윈도우 키워드

    Returns:
        bool: True=열림, False=닫힘
    """
    try:
        windows = gw.getWindowsWithTitle(keyword)
        return len(windows) > 0
    except Exception as e:
        print(f"Error checking process: {e}")
        return False


def to_do_process_close(keyword: str) -> None:
    """
    지정된 키워드를 포함한 윈도우 프로세스 종료

    Args:
        keyword: 종료할 윈도우 키워드
    """
    try:
        windows = gw.getWindowsWithTitle(keyword)
        for window in windows:
            window.close()

        if windows:
            print(f"Success: Closed {len(windows)} window(s) with keyword '{keyword}'\n")
    except Exception as e:
        print(f"Error closing process: {e}")


def isfile_and_pass(file_path: str, file_name: str) -> None:
    """
    파일 존재 확인 및 상태 출력

    Args:
        file_path: 파일 경로
        file_name: 파일명
    """
    file_full_path = Path(file_path) / file_name

    if file_full_path.is_file():
        print(f"Success: Access {file_name}\n")
    else:
        print(f"Error: Access {file_name}\n")


def isfile_and_remove(file: str) -> None:
    """
    파일 존재 시 삭제

    Args:
        file: 삭제할 파일 경로
    """
    file_path = Path(file)

    if file_path.is_file():
        try:
            file_path.unlink()
            print(f"Success: Removed {file}\n")
        except OSError as e:
            print(f"Error removing file {file}: {e}")


def open_path(path: str) -> None:
    """
    지정된 경로 열기

    Args:
        path: 열 경로
    """
    try:
        real_path = os.path.realpath(path)
        os.startfile(real_path)
        print(f"Success: Open {real_path}\n")
    except Exception as e:
        print(f"Error opening path {path}: {e}")


def load_csv_dataframe(file_path: str, filename: str) -> pd.DataFrame:
    """
    CSV 파일을 DataFrame으로 로드

    Args:
        file_path: 파일 경로
        filename: 파일명 (확장자 제외)

    Returns:
        pd.DataFrame: 로드된 데이터프레임

    Raises:
        FileNotFoundError: 파일을 찾을 수 없는 경우
        pd.errors.EmptyDataError: 빈 파일인 경우
    """
    full_path = Path(file_path) / f'{filename}.csv'

    try:
        return pd.read_csv(full_path, dtype=object, encoding='cp1252')
    except UnicodeDecodeError:
        # 다른 인코딩으로 재시도
        for encoding in DEFAULT_ENCODINGS:
            try:
                return pd.read_csv(full_path, dtype=object, encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Unable to decode file {full_path} with available encodings")


def export_csv_dataframe(df: pd.DataFrame, file_path: str, filename: str) -> None:
    """
    DataFrame을 CSV 파일로 내보내기

    Args:
        df: 내보낼 데이터프레임
        file_path: 파일 경로
        filename: 파일명 (확장자 제외)
    """
    full_path = Path(file_path) / f'{filename}.csv'

    try:
        # 디렉토리가 없으면 생성
        full_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(full_path, index=False, encoding='utf-8-sig')
        print(f"Success: Exported CSV to {full_path}\n")
    except Exception as e:
        print(f"Error exporting CSV: {e}")


def load_csv_list(file_path: str) -> List[List[str]]:
    """
    CSV 파일을 리스트로 로드 (여러 인코딩 지원)

    Args:
        file_path: CSV 파일 경로

    Returns:
        List[List[str]]: CSV 데이터 리스트

    Raises:
        FileNotFoundError: 파일을 찾을 수 없는 경우
        UnicodeDecodeError: 모든 인코딩으로 디코딩 실패 시
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    for encoding in DEFAULT_ENCODINGS:
        try:
            with open(path, 'r', encoding=encoding) as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            continue

    raise UnicodeDecodeError(f"Unable to decode file {file_path} with available encodings")


def export_csv_list(file_path: str, filename: str, lists: List[List[str]]) -> None:
    """
    리스트를 CSV 파일로 내보내기

    Args:
        file_path: 파일 경로
        filename: 파일명 (확장자 제외)
        lists: 내보낼 데이터 리스트
    """
    full_path = Path(file_path) / f'{filename}.csv'

    try:
        # 디렉토리가 없으면 생성
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerows(lists)

        print(f"Success: Exported CSV list to {full_path}\n")
    except Exception as e:
        print(f"Error exporting CSV list: {e}")


def load_pkl_list(file_path: str) -> Any:
    """
    피클 파일을 로드

    Args:
        file_path: 피클 파일 경로

    Returns:
        Any: 피클 데이터

    Raises:
        FileNotFoundError: 파일을 찾을 수 없는 경우
        pickle.UnpicklingError: 피클 로드 실패 시
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Pickle file not found: {file_path}")

    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except pickle.UnpicklingError as e:
        raise pickle.UnpicklingError(f"Failed to load pickle file {file_path}: {e}")


def find_str_inx(lines: str, start_str: str, end_str: str) -> Tuple[int, int]:
    """
    문자열에서 시작 문자열과 끝 문자열의 인덱스를 찾음

    Args:
        lines: 검색 대상 문자열
        start_str: 시작 문자열
        end_str: 끝 문자열

    Returns:
        Tuple[int, int]: (시작 인덱스, 끝 인덱스)
    """
    start_idx = lines.find(start_str)
    end_idx = lines.find(end_str) + len(end_str) if end_str in lines else -1

    return start_idx, end_idx


def check_same_value(var: Any, value: Any) -> bool:
    """
    두 값이 같은지 확인 (타입 변환 포함)

    Args:
        var: 비교할 값 1
        value: 비교할 값 2

    Returns:
        bool: True=같음, False=다름
    """
    # 타입이 같은 경우
    if type(var) == type(value):
        return var == value

    # 숫자 타입인 경우
    if isinstance(var, (int, float)) and isinstance(value, (int, float)):
        return var == value

    # 문자열을 숫자로 변환 시도
    try:
        return float(var) == float(value)
    except (ValueError, TypeError):
        print("Error: Data Type is NOT Compatible")
        return False


def check_value_in_margin(var: Any, value: Any, percentage: float) -> bool:
    """
    값이 지정된 백분율 마진 내에 있는지 확인

    Args:
        var: 확인할 값
        value: 기준 값
        percentage: 마진 백분율 (0.0~1.0)

    Returns:
        bool: True=마진 내, False=마진 밖
    """
    try:
        var_float = float(var)
        value_float = float(value)

        # 0인 경우 처리
        if value_float == 0:
            return var_float == 0

        lower_bound = abs(value_float * (1 - percentage))
        upper_bound = abs(value_float * (1 + percentage))

        return lower_bound <= abs(var_float) <= upper_bound
    except (ValueError, TypeError):
        return False


def check_value_in_margin_value(input_val: Any, expected_result: Any, margin: Any) -> bool:
    """
    값이 지정된 절대 마진 내에 있는지 확인

    Args:
        input_val: 입력 값
        expected_result: 예상 결과
        margin: 절대 마진 값

    Returns:
        bool: True=마진 내, False=마진 밖
    """
    try:
        input_float = float(input_val)
        expected_float = float(expected_result)
        margin_float = float(margin)

        lower_bound = expected_float - margin_float
        upper_bound = expected_float + margin_float

        return lower_bound <= input_float <= upper_bound
    except (ValueError, TypeError):
        return False


def column_naming(data: List[List[Any]]) -> pd.DataFrame:
    """
    데이터에 컬럼명을 부여하여 DataFrame 생성

    Args:
        data: 변환할 데이터 리스트

    Returns:
        pd.DataFrame: 컬럼명이 부여된 데이터프레임
    """
    temp_df = pd.DataFrame(data)
    col_len = len(temp_df.columns)

    base_col_names = ['ret', 'Test_Result']

    if col_len == 2:
        col_names = base_col_names
    else:
        additional_cols = [f'var{i + 1}' for i in range(col_len - 2)]
        col_names = base_col_names + additional_cols

    return pd.DataFrame(data, columns=col_names)


def get_sqrt(df: pd.DataFrame, col1: str, col2: str) -> pd.Series:
    """
    두 컬럼의 제곱합의 제곱근 계산

    Args:
        df: 데이터프레임
        col1: 첫 번째 컬럼명
        col2: 두 번째 컬럼명

    Returns:
        pd.Series: 계산된 제곱근 값들
    """
    return (df[col1] ** 2 + df[col2] ** 2) ** 0.5


def get_window_with_loop(title: str, cnt_limit: int) -> Optional[Any]:
    """
    지정된 제한 횟수만큼 윈도우 검색 시도

    Args:
        title: 검색할 윈도우 제목
        cnt_limit: 최대 시도 횟수

    Returns:
        Optional[Any]: 찾은 윈도우 객체 또는 None
    """
    for attempt in range(cnt_limit):
        try:
            titles = gw.getAllTitles()
            matching_windows = [t for t in titles if title in t]

            if matching_windows:
                window = gw.getWindowsWithTitle(matching_windows[0])[0]
                print(f"Success: Get WINDOW {title} (attempt {attempt + 1})\n")
                return window
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")

    print(f"Failed to find window '{title}' after {cnt_limit} attempts\n")
    return None


def check_front_space(string: str) -> int:
    """
    문자열 앞쪽의 공백 및 # 문자 개수 계산

    Args:
        string: 확인할 문자열

    Returns:
        int: 앞쪽 공백 개수
    """
    count = 0

    for char in string:
        if char == " ":
            count += 1
        elif char == "#":
            pass  # # 문자는 카운트하지 않지만 계속 진행
        else:
            break

    return count


def check_task_open(name: str) -> bool:
    """
    지정된 이름의 작업이 실행 중인지 확인

    Args:
        name: 확인할 작업 이름

    Returns:
        bool: True=실행 중, False=실행 안 함
    """
    try:
        task_list = os.popen('tasklist /v').read().strip().split('\n')

        for task in task_list:
            if name in task:
                print(f"The task {name} Connection: True\n")
                return True

        print(f"The task {name} Connection: False\n")
        return False
    except Exception as e:
        print(f"Error checking task {name}: {e}")
        return False


def logging_initialize() -> None:
    """
    로깅 시스템 초기화
    """
    log_file_path = Path("./data/result/Debug.log")

    # 기존 로그 파일 삭제
    if log_file_path.exists():
        try:
            log_file_path.unlink()
        except OSError as e:
            print(f"Warning: Could not remove existing log file: {e}")

    # 로그 디렉토리 생성
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # 로깅 설정 적용
    try:
        dictConfig(LOG_CONFIG)
        print("Success: Logging initialized\n")
    except Exception as e:
        print(f"Error initializing logging: {e}")


def logging_print(text: str) -> None:
    """
    로그 메시지 출력

    Args:
        text: 출력할 텍스트
    """
    logging.info(text)


from logging.config import dictConfig
import logging
import pandas as pd
import pygetwindow as gw
import os
import csv
import struct
import pickle
from typing import List, Tuple, Union, Any, Optional
from pathlib import Path

# 상수 정의
DEFAULT_ENCODINGS = ['utf-8', 'cp949', 'cp1252', 'euc-kr']
LOG_CONFIG = {
    'version': 1,
    'formatters': {
        'default': {
            'format': '[%(asctime)s] %(message)s',
        },
        'simple': {
            'format': '%(message)s',
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "simple",
        },
        "info_file_handler": {
            "class": "logging.FileHandler",
            "level": "INFO",
            "formatter": "default",
            "encoding": "utf-8",
            "filename": "./data/result/Debug.log"
        }
    },
    'root': {
        'level': 'INFO',
        'handlers': ["console", "info_file_handler"]
    }
}


def to_raw(string: str) -> str:
    """
    문자열을 raw string으로 변환

    Args:
        string: 변환할 문자열

    Returns:
        str: raw string
    """
    return rf'{string}'


def to_hex_str(integerVariable: int) -> str:
    """
    정수를 16진수 문자열로 변환

    Args:
        integerVariable: 변환할 정수

    Returns:
        str: 16진수 문자열 (예: "0x2A")
    """
    return f"0x{integerVariable:02X}"


def float_to_hex(f: float) -> str:
    """
    float 값을 16진수 문자열로 변환

    Args:
        f: 변환할 float 값

    Returns:
        str: 16진수 문자열

    Raises:
        struct.error: 변환 실패 시
    """
    try:
        return hex(struct.unpack('<I', struct.pack('<f', f))[0])
    except struct.error as e:
        raise ValueError(f"Float to hex conversion failed for value {f}: {e}")


def hex_to_float(h: str) -> float:
    """
    16진수 문자열을 float 값으로 변환

    Args:
        h: 16진수 문자열

    Returns:
        float: 변환된 float 값

    Raises:
        ValueError: 변환 실패 시
    """
    try:
        return struct.unpack('<f', struct.pack('i', int(h, 16)))[0]
    except (ValueError, struct.error) as e:
        raise ValueError(f"Hex to float conversion failed for value {h}: {e}")


def _convert_to_hex_bytes(in_val: Union[str, int, float]) -> List[int]:
    """
    입력값을 16진수 바이트 리스트로 변환하는 헬퍼 함수

    Args:
        in_val: 변환할 값

    Returns:
        List[int]: 16진수 바이트 리스트
    """
    str_val = str(in_val)

    # float 값 처리
    if '.' in str_val:
        str_val = str(float_to_hex(float(str_val)))

    # 16진수 문자열 생성
    hex_str = to_hex_str(int(str_val, 0)).replace('0x', '')

    # 홀수 길이 처리
    if len(hex_str) % 2 != 0:
        hex_str = f'0{hex_str}'

    return list(bytes.fromhex(hex_str))


def to_hex_little_lst(in_val: Union[str, int, float]) -> List[int]:
    """
    입력값을 리틀 엔디안 바이트 리스트로 변환

    Args:
        in_val: 변환할 값

    Returns:
        List[int]: 리틀 엔디안 바이트 리스트
    """
    return _convert_to_hex_bytes(in_val)[::-1]


def to_hex_big_lst(in_val: Union[str, int, float]) -> List[int]:
    """
    입력값을 빅 엔디안 바이트 리스트로 변환

    Args:
        in_val: 변환할 값

    Returns:
        List[int]: 빅 엔디안 바이트 리스트
    """
    return _convert_to_hex_bytes(in_val)


def bytearray_to_hex(arr: Union[bytearray, List[int]]) -> str:
    """
    바이트 배열을 16진수 문자열로 변환

    Args:
        arr: 바이트 배열

    Returns:
        str: 16진수 문자열
    """
    return '0x' + ''.join(f'{x:02x}' for x in arr)


def isdir_and_make(dir_name: str) -> None:
    """
    디렉토리 존재 확인 및 생성

    Args:
        dir_name: 디렉토리 경로
    """
    dir_path = Path(dir_name)

    if not dir_path.exists():
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"Success: Create {dir_name}\n")
    else:
        print(f"Success: Access {dir_name}\n")


def check_process_open(keyword: str) -> bool:
    """
    지정된 키워드를 포함한 윈도우 프로세스가 열려있는지 확인

    Args:
        keyword: 검색할 윈도우 키워드

    Returns:
        bool: True=열림, False=닫힘
    """
    try:
        windows = gw.getWindowsWithTitle(keyword)
        return len(windows) > 0
    except Exception as e:
        print(f"Error checking process: {e}")
        return False


def to_do_process_close(keyword: str) -> None:
    """
    지정된 키워드를 포함한 윈도우 프로세스 종료

    Args:
        keyword: 종료할 윈도우 키워드
    """
    try:
        windows = gw.getWindowsWithTitle(keyword)
        for window in windows:
            window.close()

        if windows:
            print(f"Success: Closed {len(windows)} window(s) with keyword '{keyword}'\n")
    except Exception as e:
        print(f"Error closing process: {e}")


def isfile_and_pass(file_path: str, file_name: str) -> None:
    """
    파일 존재 확인 및 상태 출력

    Args:
        file_path: 파일 경로
        file_name: 파일명
    """
    file_full_path = Path(file_path) / file_name

    if file_full_path.is_file():
        print(f"Success: Access {file_name}\n")
    else:
        print(f"Error: Access {file_name}\n")


def isfile_and_remove(file: str) -> None:
    """
    파일 존재 시 삭제

    Args:
        file: 삭제할 파일 경로
    """
    file_path = Path(file)

    if file_path.is_file():
        try:
            file_path.unlink()
            print(f"Success: Removed {file}\n")
        except OSError as e:
            print(f"Error removing file {file}: {e}")


def open_path(path: str) -> None:
    """
    지정된 경로 열기

    Args:
        path: 열 경로
    """
    try:
        real_path = os.path.realpath(path)
        os.startfile(real_path)
        print(f"Success: Open {real_path}\n")
    except Exception as e:
        print(f"Error opening path {path}: {e}")


def load_csv_dataframe(file_path: str, filename: str) -> pd.DataFrame:
    """
    CSV 파일을 DataFrame으로 로드

    Args:
        file_path: 파일 경로
        filename: 파일명 (확장자 제외)

    Returns:
        pd.DataFrame: 로드된 데이터프레임

    Raises:
        FileNotFoundError: 파일을 찾을 수 없는 경우
        pd.errors.EmptyDataError: 빈 파일인 경우
    """
    full_path = Path(file_path) / f'{filename}.csv'

    try:
        return pd.read_csv(full_path, dtype=object, encoding='cp1252')
    except UnicodeDecodeError:
        # 다른 인코딩으로 재시도
        for encoding in DEFAULT_ENCODINGS:
            try:
                return pd.read_csv(full_path, dtype=object, encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Unable to decode file {full_path} with available encodings")


def export_csv_dataframe(df: pd.DataFrame, file_path: str, filename: str) -> None:
    """
    DataFrame을 CSV 파일로 내보내기

    Args:
        df: 내보낼 데이터프레임
        file_path: 파일 경로
        filename: 파일명 (확장자 제외)
    """
    full_path = Path(file_path) / f'{filename}.csv'

    try:
        # 디렉토리가 없으면 생성
        full_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(full_path, index=False, encoding='utf-8-sig')
        print(f"Success: Exported CSV to {full_path}\n")
    except Exception as e:
        print(f"Error exporting CSV: {e}")


def load_csv_list(file_path: str) -> List[List[str]]:
    """
    CSV 파일을 리스트로 로드 (여러 인코딩 지원)

    Args:
        file_path: CSV 파일 경로

    Returns:
        List[List[str]]: CSV 데이터 리스트

    Raises:
        FileNotFoundError: 파일을 찾을 수 없는 경우
        UnicodeDecodeError: 모든 인코딩으로 디코딩 실패 시
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    for encoding in DEFAULT_ENCODINGS:
        try:
            with open(path, 'r', encoding=encoding) as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            continue

    raise UnicodeDecodeError(f"Unable to decode file {file_path} with available encodings")


def export_csv_list(file_path: str, filename: str, lists: List[List[str]]) -> None:
    """
    리스트를 CSV 파일로 내보내기

    Args:
        file_path: 파일 경로
        filename: 파일명 (확장자 제외)
        lists: 내보낼 데이터 리스트
    """
    full_path = Path(file_path) / f'{filename}.csv'

    try:
        # 디렉토리가 없으면 생성
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerows(lists)

        print(f"Success: Exported CSV list to {full_path}\n")
    except Exception as e:
        print(f"Error exporting CSV list: {e}")


def load_pkl_list(file_path: str) -> Any:
    """
    피클 파일을 로드

    Args:
        file_path: 피클 파일 경로

    Returns:
        Any: 피클 데이터

    Raises:
        FileNotFoundError: 파일을 찾을 수 없는 경우
        pickle.UnpicklingError: 피클 로드 실패 시
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Pickle file not found: {file_path}")

    try:
        with open(path, 'rb') as f:
            return pickle.load(f)
    except pickle.UnpicklingError as e:
        raise pickle.UnpicklingError(f"Failed to load pickle file {file_path}: {e}")


def find_str_inx(lines: str, start_str: str, end_str: str) -> Tuple[int, int]:
    """
    문자열에서 시작 문자열과 끝 문자열의 인덱스를 찾음

    Args:
        lines: 검색 대상 문자열
        start_str: 시작 문자열
        end_str: 끝 문자열

    Returns:
        Tuple[int, int]: (시작 인덱스, 끝 인덱스)
    """
    start_idx = lines.find(start_str)
    end_idx = lines.find(end_str) + len(end_str) if end_str in lines else -1

    return start_idx, end_idx


def check_same_value(var: Any, value: Any) -> bool:
    """
    두 값이 같은지 확인 (타입 변환 포함)

    Args:
        var: 비교할 값 1
        value: 비교할 값 2

    Returns:
        bool: True=같음, False=다름
    """
    # 타입이 같은 경우
    if type(var) == type(value):
        return var == value

    # 숫자 타입인 경우
    if isinstance(var, (int, float)) and isinstance(value, (int, float)):
        return var == value

    # 문자열을 숫자로 변환 시도
    try:
        return float(var) == float(value)
    except (ValueError, TypeError):
        print("Error: Data Type is NOT Compatible")
        return False


def check_value_in_margin(var: Any, value: Any, percentage: float) -> bool:
    """
    값이 지정된 백분율 마진 내에 있는지 확인

    Args:
        var: 확인할 값
        value: 기준 값
        percentage: 마진 백분율 (0.0~1.0)

    Returns:
        bool: True=마진 내, False=마진 밖
    """
    try:
        var_float = float(var)
        value_float = float(value)

        # 0인 경우 처리
        if value_float == 0:
            return var_float == 0

        lower_bound = abs(value_float * (1 - percentage))
        upper_bound = abs(value_float * (1 + percentage))

        return lower_bound <= abs(var_float) <= upper_bound
    except (ValueError, TypeError):
        return False


def check_value_in_margin_value(input_val: Any, expected_result: Any, margin: Any) -> bool:
    """
    값이 지정된 절대 마진 내에 있는지 확인

    Args:
        input_val: 입력 값
        expected_result: 예상 결과
        margin: 절대 마진 값

    Returns:
        bool: True=마진 내, False=마진 밖
    """
    try:
        input_float = float(input_val)
        expected_float = float(expected_result)
        margin_float = float(margin)

        lower_bound = expected_float - margin_float
        upper_bound = expected_float + margin_float

        return lower_bound <= input_float <= upper_bound
    except (ValueError, TypeError):
        return False


def column_naming(data: List[List[Any]]) -> pd.DataFrame:
    """
    데이터에 컬럼명을 부여하여 DataFrame 생성

    Args:
        data: 변환할 데이터 리스트

    Returns:
        pd.DataFrame: 컬럼명이 부여된 데이터프레임
    """
    temp_df = pd.DataFrame(data)
    col_len = len(temp_df.columns)

    base_col_names = ['ret', 'Test_Result']

    if col_len == 2:
        col_names = base_col_names
    else:
        additional_cols = [f'var{i + 1}' for i in range(col_len - 2)]
        col_names = base_col_names + additional_cols

    return pd.DataFrame(data, columns=col_names)


def get_sqrt(df: pd.DataFrame, col1: str, col2: str) -> pd.Series:
    """
    두 컬럼의 제곱합의 제곱근 계산

    Args:
        df: 데이터프레임
        col1: 첫 번째 컬럼명
        col2: 두 번째 컬럼명

    Returns:
        pd.Series: 계산된 제곱근 값들
    """
    return (df[col1] ** 2 + df[col2] ** 2) ** 0.5


def get_window_with_loop(title: str, cnt_limit: int) -> Optional[Any]:
    """
    지정된 제한 횟수만큼 윈도우 검색 시도

    Args:
        title: 검색할 윈도우 제목
        cnt_limit: 최대 시도 횟수

    Returns:
        Optional[Any]: 찾은 윈도우 객체 또는 None
    """
    for attempt in range(cnt_limit):
        try:
            titles = gw.getAllTitles()
            matching_windows = [t for t in titles if title in t]

            if matching_windows:
                window = gw.getWindowsWithTitle(matching_windows[0])[0]
                print(f"Success: Get WINDOW {title} (attempt {attempt + 1})\n")
                return window
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")

    print(f"Failed to find window '{title}' after {cnt_limit} attempts\n")
    return None


def check_front_space(string: str) -> int:
    """
    문자열 앞쪽의 공백 및 # 문자 개수 계산

    Args:
        string: 확인할 문자열

    Returns:
        int: 앞쪽 공백 개수
    """
    count = 0

    for char in string:
        if char == " ":
            count += 1
        elif char == "#":
            pass  # # 문자는 카운트하지 않지만 계속 진행
        else:
            break

    return count


def check_task_open(name: str) -> bool:
    """
    지정된 이름의 작업이 실행 중인지 확인

    Args:
        name: 확인할 작업 이름

    Returns:
        bool: True=실행 중, False=실행 안 함
    """
    try:
        task_list = os.popen('tasklist /v').read().strip().split('\n')

        for task in task_list:
            if name in task:
                print(f"The task {name} Connection: True\n")
                return True

        print(f"The task {name} Connection: False\n")
        return False
    except Exception as e:
        print(f"Error checking task {name}: {e}")
        return False


def logging_initialize() -> None:
    """
    로깅 시스템 초기화
    """
    log_file_path = Path("./data/result/Debug.log")

    # 기존 로그 파일 삭제
    if log_file_path.exists():
        try:
            log_file_path.unlink()
        except OSError as e:
            print(f"Warning: Could not remove existing log file: {e}")

    # 로그 디렉토리 생성
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # 로깅 설정 적용
    try:
        dictConfig(LOG_CONFIG)
        print("Success: Logging initialized\n")
    except Exception as e:
        print(f"Error initializing logging: {e}")


def logging_print(text: str) -> None:
    """
    로그 메시지 출력

    Args:
        text: 출력할 텍스트
    """
    logging.info(text)

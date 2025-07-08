import pandas as pd
from typing import List, Tuple, Any, Union


def find_out_signals_for_col(out_sigs: List[List[Any]]) -> Tuple[List[str], List[Any]]:
    """
    최적화된 출력 신호 컬럼 및 T32 출력 추출 함수

    Args:
        out_sigs: 출력 신호 정보를 담은 중첩 리스트

    Returns:
        Tuple[List[str], List[Any]]: (컬럼명 리스트, T32 출력값 리스트)
    """
    cols: List[str] = [f'Out: {sig[2]}' for sig in out_sigs]
    t32_out: List[Any] = [sig[-1] for sig in out_sigs if 'T32' in sig[0]]
    return cols, t32_out


def judge_final_result(
        df_result: pd.DataFrame,
        expected_outs: List[List[Union[int, float, str, None]]],
        num_match: int,
        meas_log: List[List[Any]],
        out_col: List[str],
        judge: str = "same"
) -> List[List[Any]]:
    """
    최적화된 최종 결과 판정 함수

    Args:
        df_result: 결과 데이터프레임
        expected_outs: 예상 출력값들의 리스트
        num_match: 매칭되어야 하는 최소 행 수
        meas_log: 측정 로그 리스트
        out_col: 출력 컬럼명 리스트
        judge: 판정 모드 ("same" 또는 기타)

    Returns:
        List[List[Any]]: 업데이트된 측정 로그
    """
    final_result: str = 'Pass'
    fail_cases: List[List[Union[str, Any]]] = []

    def create_fail_case(expected: List[Union[int, float, str, None]], step_idx: int = 0) -> List[Union[str, Any]]:
        """
        실패 케이스 생성 헬퍼 함수

        Args:
            expected: 예상값 리스트
            step_idx: 스텝 인덱스

        Returns:
            List[Union[str, Any]]: 실패 케이스 정보 리스트
        """
        fail_step = str(int(expected[step_idx]))
        return [
            fail_step,
            'Fail Case',
            f'Step_{fail_step}',
            'Expected Output'
        ] + [f'{var}={val}' for var, val in zip(out_col, expected[1:])]

    def check_matching_rows(df: pd.DataFrame, expected: List[Union[int, float, str, None]], start_idx: int = 1) -> bool:
        """
        매칭 행 확인 헬퍼 함수

        Args:
            df: 확인할 데이터프레임
            expected: 예상값 리스트
            start_idx: 시작 인덱스

        Returns:
            bool: 매칭 조건을 만족하는지 여부
        """
        df_match = df.copy()
        for ex_value, col in zip(expected[start_idx:], df.columns[start_idx:]):
            if ex_value is not None:
                df_match = df_match[df_match[col] == ex_value]
        return len(df_match) >= num_match

    # 결과 판정 로직
    if judge == "same":
        # 'same' 모드: 전체 데이터프레임에서 매칭 확인
        for expected in expected_outs:
            if not check_matching_rows(df_result, expected, 0):
                fail_cases.append(create_fail_case(expected, 0))
    else:
        # 기타 모드: 스텝별로 매칭 확인
        for expected in expected_outs:
            df_step = df_result[df_result['Step'] == expected[0]]
            if not df_step.empty and not check_matching_rows(df_step, expected, 1):
                fail_cases.append(create_fail_case(expected, 0))

    # 실패 케이스 처리
    if fail_cases:
        final_result = 'Fail'

        # 실패 케이스들을 meas_log에 삽입
        for idx, fail_case in enumerate(fail_cases):
            meas_log.insert(idx + 1, fail_case[1:])

        # 최종 결과 문자열 생성
        fail_steps: List[str] = [case[0] for case in fail_cases]
        final_result += ',' + ','.join(fail_steps)
        final_result_str: str = final_result.replace(',', ', ').replace('Fail', 'Fail Step:')
        print(f'*** {final_result_str}')

    meas_log.append(['Result', final_result])
    return meas_log

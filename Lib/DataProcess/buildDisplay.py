import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import string
from typing import Dict, List, Tuple, Optional, Any
from Lib.Inst import canBus

# 상수 정의
HTML_STYLES = {
    'bootstrap_css': "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/css/bootstrap.min.css",
    'bootstrap_js': "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js",
    'font_black_han': "https://fonts.googleapis.com/css2?family=Black+Han+Sans&display=swap",
    'font_jua': "https://fonts.googleapis.com/css2?family=Jua&display=swap",
    'font_nunito': "https://fonts.googleapis.com/css?family=Nunito:400,300"
}

GRAPH_CONFIG = {
    'figure_size': (26, 26),
    'marker_size': 2,
    'line_width': 1.0,
    'alpha': 0.1,
    'max_yticks': 8
}

HTML_TEMPLATE_BASE = """
<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="EUC-KR">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="{bootstrap_css}" integrity="sha384-Zenh87qX5JnK2Jl0vWa8Ck2rdkQ2Bzep5IDxbcnCeuOxjzrPF/et3URy9Bv1WTRi" crossorigin="anonymous">
        <link rel='stylesheet' href='{font_black_han}' type='text/css'>
        <link rel='stylesheet' href='{font_jua}' type='text/css'>
        <link rel='stylesheet' href='{font_nunito}' type='text/css'>
        <title>{title} Result</title>
    </head>
    <body>
        {header}
        {additional_header}
        {sum_body}
        {res_body}
        {download_link}
        <script src="{bootstrap_js}" integrity="sha384-OERcA2EqjJCMA+/3y+gxIOqMEjwtxJY7qPCqsdltbNJuaOe923+mo//f6V8Qbsw3" crossorigin="anonymous"></script>
    </body>
</html>
"""


def signal_step_graph(
        df: pd.DataFrame,
        sigs: List[List[str]],
        x_col: str,
        filepath: str,
        filename: str,
        fill_zero: bool = True,
        step_debug: bool = True
) -> None:
    """
    신호 스텝 그래프를 생성하고 저장하는 함수

    Args:
        df: 데이터프레임
        sigs: 신호 정보 리스트
        x_col: X축 컬럼명
        filepath: 파일 저장 경로
        filename: 파일명
        fill_zero: 0으로 채우기 여부
        step_debug: 스텝 디버그 표시 여부
    """
    plt.rcParams['axes.xmargin'] = 0

    # 인덱스 설정 및 전처리
    df_processed = _preprocess_dataframe(df, x_col, fill_zero)
    step_dict = _extract_step_info(df_processed)

    # 그래프 생성
    fig, axs = _create_signal_plots(df_processed, sigs, step_dict, step_debug)

    # 저장 및 정리
    _save_and_cleanup_plot(fig, filepath, filename)


def _preprocess_dataframe(df: pd.DataFrame, x_col: str, fill_zero: bool) -> pd.DataFrame:
    """데이터프레임 전처리"""
    df_copy = df.copy()
    df_copy.set_index(x_col, drop=True, inplace=True)

    if fill_zero:
        df_copy.fillna(0, inplace=True)

    return df_copy


def _extract_step_info(df: pd.DataFrame) -> Dict[Any, Tuple[float, float]]:
    """스텝 정보 추출"""
    step_dict = {}

    if df.columns[0] == 'Step':
        for step, group in df.groupby('Step'):
            time_sec = group.index.to_numpy()
            step_dict[step] = (time_sec[0], time_sec[-1])

        df.drop(labels='Step', axis=1, inplace=True)

    return step_dict


def _create_signal_plots(
        df: pd.DataFrame,
        sigs: List[List[str]],
        step_dict: Dict[Any, Tuple[float, float]],
        step_debug: bool
) -> Tuple[Any, Any]:
    """신호 플롯 생성"""
    data_col = df.columns
    fig = plt.figure(figsize=GRAPH_CONFIG['figure_size'])
    axs = fig.add_gridspec(len(data_col), hspace=0.1).subplots(sharex=True, sharey=False)

    # 단일 서브플롯인 경우 리스트로 변환
    if len(data_col) == 1:
        axs = [axs]

    for i, signal in enumerate(data_col):
        _plot_single_signal(axs[i], df, signal, sigs, i, step_dict, step_debug, len(data_col))

    # 레이아웃 설정
    for ax in axs:
        ax.legend(loc='upper right')
        ax.label_outer()

    return fig, axs


def _plot_single_signal(
        ax: Any,
        df: pd.DataFrame,
        signal: str,
        sigs: List[List[str]],
        idx: int,
        step_dict: Dict[Any, Tuple[float, float]],
        step_debug: bool,
        total_signals: int
) -> None:
    """개별 신호 플롯"""
    sig_color_idx = idx % 20
    sig_name = signal.replace('In: ', '').replace('Out: ', '')

    # 데이터 준비
    df_signal = df[[signal]].dropna(axis=0)
    x_data = df_signal.index.to_numpy()
    y_data = df_signal.to_numpy()

    # 플롯 생성
    ax.step(x_data, y_data, 'o-',
            markersize=GRAPH_CONFIG['marker_size'],
            label=sig_name,
            c=plt.cm.tab20(sig_color_idx),
            where='post',
            linewidth=GRAPH_CONFIG['line_width'])

    # Y축 설정
    _set_y_axis(ax, y_data, sig_name, sigs, idx)

    # 스텝 디버그 표시
    if step_debug and step_dict:
        _add_step_debug(ax, step_dict, idx == 0)

    # X축 라벨 설정
    if idx == total_signals - 1:
        ax.set_xlabel('Time[sec]')


def _set_y_axis(ax: Any, y_data: np.ndarray, sig_name: str, sigs: List[List[str]], idx: int) -> None:
    """Y축 설정"""
    if y_data.size == 0:
        yticks_val = list(range(0, 2))
    else:
        min_y, max_y = int(min(y_data)), int(max(y_data))
        yticks_val = _calculate_yticks(min_y, max_y)

    ax.set_yticks(yticks_val)

    # Y축 라벨 설정
    yticks_labels = _get_ytick_labels(yticks_val, sig_name, sigs, idx)
    ax.set_yticklabels(yticks_labels)


def _calculate_yticks(min_y: int, max_y: int) -> List[int]:
    """Y축 틱 계산"""
    if max_y == 0:
        return list(range(min_y, max_y + 2))
    elif max_y > GRAPH_CONFIG['max_yticks']:
        yticks = list(range(min_y, max_y, int(max_y / 7)))
        yticks[-1] = max_y
        return yticks
    else:
        return list(range(min_y, max_y + 1))


def _get_ytick_labels(
        yticks_val: List[int],
        sig_name: str,
        sigs: List[List[str]],
        idx: int
) -> List[str]:
    """Y축 틱 라벨 생성"""
    yticks_labels = []

    for y_val in yticks_val:
        if (idx < len(sigs) and
                sig_name == sigs[idx][-1] and
                sigs[idx][0] not in ['T32', 'LIN'] and
                sig_name in canBus.devs[sigs[idx][0]].sig_val and
                y_val in canBus.devs[sigs[idx][0]].sig_val[sig_name]):
            yticks_labels.append(canBus.devs[sigs[idx][0]].sig_val[sig_name][y_val])
        else:
            yticks_labels.append(f'{y_val}')

    return yticks_labels


def _add_step_debug(ax: Any, step_dict: Dict[Any, Tuple[float, float]], is_first: bool) -> None:
    """스텝 디버그 표시 추가"""
    step_location = []

    for idx, step_time in enumerate(step_dict.values()):
        color_idx = idx % 20
        ax.axvspan(step_time[0], step_time[1],
                   alpha=GRAPH_CONFIG['alpha'],
                   color=plt.cm.tab20(color_idx))
        step_location.append(np.mean(step_time))

    if is_first and step_location:
        ax_twin = ax.twiny()
        ax_twin.set_xlim(ax.get_xlim())
        ax_twin.set_xticks(np.array(step_location))
        ax_twin.set_xticklabels(step_dict.keys())
        ax_twin.set_xlabel('Step')


def _save_and_cleanup_plot(fig: Any, filepath: str, filename: str) -> None:
    """플롯 저장 및 정리"""
    save_path = os.path.join(filepath, f'{filename}.png')
    fig.savefig(save_path, format='png', bbox_inches='tight')

    plt.cla()
    plt.clf()
    plt.close()


def make_pjt_HTML(
        df_sum: pd.DataFrame,
        project: str,
        version: str,
        dict_tc: Dict[str, str],
        tc_script: Dict[str, pd.DataFrame],
        tc_in_out: Dict[str, List[Any]],
        export_path: str
) -> None:
    """
    프로젝트 HTML 파일 생성

    Args:
        df_sum: 요약 데이터프레임
        project: 프로젝트명
        version: 버전 정보
        dict_tc: 테스트 케이스 딕셔너리
        tc_script: 테스트 케이스 스크립트 딕셔너리
        tc_in_out: 테스트 케이스 입출력 딕셔너리
        export_path: 내보내기 경로
    """
    header =  f'<h1 style="font-family: \'Black Han Sans\', sans-serif;font-size: 2.5em;color: red;margin: 20px 0 10px 40px;>{project}</h1>'
    additional_header = f'<h2 style="font-family: \'Jua\', sans-serif;font-size: 1.0em;color: black;margin: 20px 0 10px 40px;">* SW 버전: {version}</h2>'
    download_link =  f'<h2 style="font-family: \'Jua\', sans-serif;font-size: 1.0em;color: black;margin: 0 0 10px 40px;"><a href="./" style="text-decoration:none">테스트 원본 파일을 다운받으시려면 여기를 클릭해주세요</a></h2>'

    html_content = HTML_TEMPLATE_BASE.format(
        title=project,
        header=header,
        additional_header=additional_header,
        sum_body=_write_summary(df_sum),
        res_body=_write_tc_res_body(dict_tc, tc_script, tc_in_out),
        download_link=download_link,
        **HTML_STYLES
    )

    _save_html_file(html_content, export_path, f'Result_{project}.html')


def make_home_HTML(
        data: Dict[str, Dict[str, str]],
        export_path: str,
        df_ver: pd.DataFrame
) -> None:
    """
    홈 HTML 파일 생성

    Args:
        data: 테스트 결과 데이터 딕셔너리
        export_path: 내보내기 경로
        df_ver: 버전 데이터프레임
    """
    test_date = os.path.basename(export_path)

    # 테이블 생성
    header = f'<h1 style="font-family: \'Black Han Sans\', sans-serif;font-size: 2.5em;color: black;margin: 20px 0 10px 40px;>EILS 테스트 결과</h1>'
    additional_header = f'''
    <h2 style="font-family: 'Jua', sans-serif;font-size: 1.0em;color: red;margin: 20px 0 10px 40px;>
    * 테스트 수행 날짜: {test_date}<br>
    * 테스트 환경: 제어기 + CAN + T32<br>
    * 테스트 방법: CAN Bus와 T32 제어 가능한 프로그램을 이용하여 정해진 시나리오를 진행
    </h2>
    '''
    table_content = _create_home_table(data, test_date)

    html_content = HTML_TEMPLATE_BASE.format(
        title='EILS 테스트 결과',
        header=header,
        additional_header=additional_header + _write_version(df_ver),
        sum_body=f'<table style="font-family: \'Nunito\', sans-serif;border: none;border-collapse: collapse;font-size: 1.0em;color: black;margin-bottom: 40px;margin-left: 40px;padding: 20px;">{table_content}</table>',
        res_body='',
        download_link='',
        **HTML_STYLES
    )

    _save_html_file(html_content, export_path, f'Result_{test_date}.html')


def _create_home_table(data: Dict[str, Dict[str, str]], test_date: str) -> str:
    """홈 테이블 생성"""
    table_rows = [
        '<tr style="background-color: #54585d;border: 1px solid #54585d;">',
        '<th style="padding: 15px;border-right: 1px solid #54585d;text-align: center;color: white;">모듈</th>',
        '<th style="padding: 15px;border-right: 1px solid #54585d;text-align: center;color: white;">기능</th>',
        '<th style="padding: 15px;border-right: 1px solid #54585d;text-align: center;color: white;">결과</th>',
        '<th style="padding: 15px;text-align: center;color: white;">상세 링크</th>',
        '</tr>'
    ]

    for pjt, pjt_data in data.items():
        _add_project_rows(table_rows, pjt, pjt_data, test_date)

    return '\n'.join(table_rows)


def _add_project_rows(table_rows: List[str], pjt: str, pjt_data: Dict[str, str], test_date: str) -> None:
    """프로젝트 행 추가"""
    table_rows.append('<tr>')
    table_rows.append(f'<td rowspan={len(pjt_data)} style="padding: 15px;border: 1px solid #54585d;">{pjt}</td>')

    module_tr_written = False
    for tc, tc_result in pjt_data.items():
        if module_tr_written:
            table_rows.append('<tr>')

        table_rows.append(f'<td rowspan=1 style="padding: 15px;border: 1px solid #54585d;">{tc}</td>')

        # 결과 셀 스타일 결정
        result_style = _get_result_cell_style(tc_result)
        table_rows.append(f'<td rowspan=1 style="{result_style}">{_get_result_text(tc_result)}</td>')

        if not module_tr_written:
            table_rows.append(
                f'<td rowspan={len(pjt_data)} style="padding: 15px;border: 1px solid #54585d;text-align: center"><a href="{pjt}/Result_{pjt}.html">{pjt}<br>{test_date}</a></td>')
            module_tr_written = True

        table_rows.append('</tr>')


def _get_result_cell_style(result: str) -> str:
    """결과 셀 스타일 반환"""
    base_style = "padding: 15px;border: 1px solid #54585d;"

    if 'Fail' in result:
        return f"background-color: #F1948A;{base_style}"
    elif 'Pass' in result:
        return f"background-color: #ABEBC6;{base_style}"
    else:
        return base_style


def _get_result_text(result: str) -> str:
    """결과 텍스트 반환"""
    if 'Fail' in result:
        return 'Fail'
    elif 'Pass' in result:
        return 'Pass'
    else:
        return result


def _save_html_file(content: str, path: str, filename: str) -> None:
    """HTML 파일 저장"""
    export_file = os.path.join(path, filename)
    with open(export_file, 'w') as html_file:
        html_file.write(content)


def _write_version(df_ver: pd.DataFrame) -> str:
    """
    버전 정보 HTML 작성

    Args:
        df_ver: 버전 데이터프레임

    Returns:
        str: 버전 정보 HTML
    """
    html_lines = df_ver.to_html(border=None, index=False).split('\n')
    processed_lines = []

    for line in html_lines:
        if 'class="dataframe"' in line:
            line = '''<table class="dataframe" style="font-family: 'Nunito', sans-serif;border: none;border-collapse: collapse;font-size: 1.0em;color: black;margin: 0 0 40px 40px;padding: 20px;">'''
        elif '<td>' in line and '.' in line:
            line = line.replace('<td>', '<td style="text-align: right;padding-left: 30px;color: black;">')
        processed_lines.append(line)

    return '\n'.join(processed_lines)


def _write_summary(df_sum: pd.DataFrame) -> str:
    """
    요약 정보 HTML 작성

    Args:
        df_sum: 요약 데이터프레임

    Returns:
        str: 요약 정보 HTML
    """
    html_lines = df_sum.to_html(border=None).split('\n')
    processed_lines = []

    for line in html_lines:
        line = _process_summary_line(line, df_sum, processed_lines)
        processed_lines.append(line)

    return '\n'.join(processed_lines)


def _process_summary_line(line: str, df_sum: pd.DataFrame, processed_lines: List[str]) -> str:
    """요약 라인 처리"""
    if '<td' in line:
        return _process_summary_td(line, df_sum, processed_lines)
    elif '<th>' in line and 'Value' not in line:
        return line.replace('<th>', '<th style="padding-right: 20px;">')
    elif 'class="dataframe"' in line:
        return '''<table class="dataframe" style="font-family: 'Nunito', sans-serif;border: none;border-collapse: collapse;font-size: 1.0em;color: black;margin-bottom: 40px;margin-left: 40px;padding: 20px;">'''
    return line


def _process_summary_td(line: str, df_sum: pd.DataFrame, processed_lines: List[str]) -> str:
    """요약 테이블 데이터 처리"""
    if 'TestCase_Names' in processed_lines[-1]:
        test_cases = df_sum.loc['TestCase_Names', 'Value'].split(', ')
        html_test_cases = '<br>'.join(test_cases)
        return f'<td style="border-bottom: 2px solid #54585d;text-align: right;padding-left: 30px;font-weight: 900;color: black;">{html_test_cases}</td>'
    elif 'Fail_Case' in processed_lines[-1]:
        fail_cases = df_sum.loc['Fail_Case', 'Value'].split(', ')
        if fail_cases[0] != 'Nothing':
            html_fail_cases = '<br>'.join(fail_cases).replace(',', ', ')
            return f'<td style="border-bottom: 2px solid #54585d;text-align: right;padding-left: 30px;font-weight: 900;color: red;">{html_fail_cases}</td>'

    return line.replace('<td>', '<td style="text-align: right;padding-left: 30px;">')


def _write_tc_res_body(
        dict_tc: Dict[str, str],
        tc_script: Dict[str, Optional[pd.DataFrame]],
        tc_in_out: Dict[str, List[Any]]
) -> str:
    """
    테스트 케이스 결과 본문 HTML 작성

    Args:
        dict_tc: 테스트 케이스 딕셔너리
        tc_script: 테스트 케이스 스크립트 딕셔너리
        tc_in_out: 테스트 케이스 입출력 딕셔너리

    Returns:
        str: 테스트 케이스 결과 본문 HTML
    """
    tc_res_html_parts = []

    for tc, sub_title in dict_tc.items():
        img_src = f'{tc}.png'

        if tc_script and tc_script.get(tc) is not None:
            str_tc_prefix, str_tc_script = _write_tc(tc_script[tc], tc_in_out[tc])
            tc_res_body = f'''
            <h3 style="font-family: 'Jua', sans-serif;font-size: 1em;color: black;margin: 0 0 0 40px;">{sub_title}</h3>
            {str_tc_prefix}
            {str_tc_script}
            <img src="{img_src}" width="1100" height="1100" style="width: 1100px; height: 850px; margin: 0 0 40px 20px;" alt="NOT FOUND"></img>
            '''
        else:
            tc_res_body = f'''
            <h3 style="font-family: 'Jua', sans-serif;font-size: 1em;color: black;margin: 0 0 0 40px;">{sub_title}</h3>
            <img src="{img_src}" width="1100" height="1100" style="width: 1100px; height: 850px; margin: 0 0 40px 20px;" alt="NOT FOUND"></img>
            '''

        tc_res_html_parts.append(tc_res_body)

    return ''.join(tc_res_html_parts)


def _write_meas_res(project: str, tc_script: pd.DataFrame, tc_in_out: List[Any]) -> str:
    """
    측정 결과 HTML 작성

    Args:
        project: 프로젝트명
        tc_script: 테스트 케이스 스크립트
        tc_in_out: 테스트 케이스 입출력

    Returns:
        str: 측정 결과 HTML
    """
    img_src = f'{project}.png'
    str_tc_prefix, str_tc_script = _write_tc(tc_script, tc_in_out)

    return f'''
    <h3 style="font-family: 'Jua', sans-serif;font-size: 1em;color: black;margin: 0 0 0 40px;">Script and Result Graph</h3>
    {str_tc_prefix}
    {str_tc_script}
    <img src="{img_src}" width="1100" height="1100" style="width: 1100px; height: 850px; margin: 0 0 40px 20px;" alt="NOT FOUND"></img>
    '''


def _write_tc(df_script: pd.DataFrame, in_out: List[List[str]]) -> Tuple[str, str]:
    """
    테스트 케이스 HTML 작성

    Args:
        df_script: 테스트 케이스 스크립트 데이터프레임
        in_out: 입출력 정보 리스트

    Returns:
        Tuple[str, str]: (접두사 HTML, 스크립트 HTML)
    """
    cols = ['#', 'Scenario', 'Time[s]']

    # 입력 신호 처리
    inputs = []
    for i, in_sig in zip(string.ascii_uppercase, in_out[0]):
        inputs.append(f'{i}. {in_sig.replace(", ", "/ ")}')
        cols.append(i)

    # 출력 신호 처리 (오타 수정)
    outs = []
    for i, out_sig in zip(string.ascii_uppercase, in_out[1] if len(in_out) > 1 else []):
        outs.append(f'A{i}. {out_sig.replace("[OUT]", "").replace(", ", "/ ")}')
        cols.append(f'A{i}')

    # 데이터프레임 생성
    df_prefix = pd.DataFrame({
        'Input': ['spacing'.join(inputs)],
        'Output': ['spacing'.join(outs)]
    })

    df_script_copy = df_script.copy()
    df_script_copy.columns = cols[:len(df_script_copy.columns)]

    # HTML 생성
    pre_html = _table_tc_to_html(
        lst_html=df_prefix.to_html(border=None, index=False).split('\n'),
        scr=False
    ).replace('spacing', '<br>')

    max_length = df_script_copy['Scenario'].str.len().max() if 'Scenario' in df_script_copy.columns else 10
    scr_html = _table_tc_to_html(
        lst_html=df_script_copy.to_html(border=None, index=False).split('\n'),
        scr=True,
        max_length=max_length
    ).replace('spacing', '<br>')

    return pre_html, scr_html


def _table_tc_to_html(lst_html: List[str], scr: bool = False, max_length: int = 10) -> str:
    """
    테스트 케이스 테이블을 HTML로 변환

    Args:
        lst_html: HTML 라인 리스트
        scr: 스크립트 여부
        max_length: 최대 길이

    Returns:
        str: 변환된 HTML
    """
    processed_lines = []
    col_td = 0

    for line in lst_html:
        """테이블 라인 처리"""
        if 'class="dataframe"' in line:
            line = '''<table class="dataframe" style="font-family: 'Nunito', sans-serif;border: none;border-collapse: collapse;font-size: 0.8em;color: black;margin: 10px 0 20px 40px;padding: 20px;">'''
        elif '<th>' in line:
            line = _process_th_line(line, max_length)
        elif '<td>' in line:
            col_td += 1
            line = _process_td_line(line, scr, col_td)
        if '<tr>' in line:
            col_td = 0

        processed_lines.append(line)

    return '\n'.join(processed_lines)


def _process_th_line(line: str, max_length: int) -> str:
    """테이블 헤더 라인 처리"""
    if 'Scenario' in line:
        pixel_num = _calculate_pixel_width(max_length)
        return line.replace(', ', '<br>').replace('<th>',
                                                  f'<td style="background-color: #FCF3F2;border: 1px solid #c1c4c7;text-align: center;padding: 0 {pixel_num}px 0 {pixel_num}px;">')
    else:
        return line.replace(', ', '<br>').replace('<th>',
                                                  '<td style="background-color: #FCF3F2;border: 1px solid #c1c4c7;text-align: center;padding: 0 10px 0 10px;">')


def _process_td_line(line: str, scr: bool, col_td: int) -> str:
    """테이블 데이터 라인 처리"""
    if scr:
        if col_td != 1:  # col_td는 0-based이므로 1이면 두 번째 컬럼
            return line.replace('<td>',
                                '<td style="border: 1px solid #c1c4c7;text-align: center;padding: 0 10px 0 10px;">')
        else:
            return line.replace('<td>',
                                '<td style="border: 1px solid #c1c4c7;text-align: left;padding: 0 10px 0 10px;">')
    else:
        return line.replace('<td>',
                            '<td style="border: 1px solid #c1c4c7;text-align: left;padding: 0 10px 0 10px;vertical-align: top;">')


def _calculate_pixel_width(max_length: int) -> str:
    """픽셀 너비 계산"""
    if max_length <= 8:
        return '10'
    elif max_length <= 15:
        return '60'
    elif max_length <= 20:
        return '90'
    else:
        return str(int(max_length * 5.5))

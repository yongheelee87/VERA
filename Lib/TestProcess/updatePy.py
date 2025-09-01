import os
from itertools import groupby
from typing import List, Tuple, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import pandas as pd
import numpy as np
from Lib.Inst import canBus
from Lib.Common import load_csv_list, to_raw, find_str_inx


class DeviceType(Enum):
    """Device type enumeration"""
    CAN = "CAN"
    DEBUG = "DEBUG"


class MessageType(Enum):
    """Message type enumeration"""
    EVENT = "Event"
    PERIOD = "Period"


class FrameType(Enum):
    """Frame type enumeration"""
    NORMAL = "Normal"
    EXTENDED = "Extended"


class TimeType(Enum):
    """Time type enumeration"""
    DELTA = "Delta"
    TOTAL = "Total"


class UpdatePyConstants:
    """Constants for UpdatePy class"""
    # File extensions
    PY_EXT = '.py'
    CSV_EXT = '.csv'
    PKL_EXT = '.pkl'

    # Special command codes
    RESET_CODE = 255
    CAN_STOP_CODE = 254
    NVM_DEFAULT = 253

    # Signal prefixes and suffixes
    OUTPUT_PREFIX = '[OUT]'
    EVENT_MARKER = '_E_'
    TIME_SUFFIX = 'ms'

    # Default values
    DEFAULT_TIMEOUT = 0.2
    DEFAULT_SAMPLE_RATE = 0.01
    DEFAULT_PERIOD = 0.02
    EXTENDED_ID_THRESHOLD = 0xFFFF

    # Column indices
    STEP_COL_INDEX = 0
    TIME_COL_INDEX = 1
    SIGNAL_START_INDEX = 2

    # Template markers
    USE_DB_INTERFACE = '# USE DB INTERFACE'
    DATA_BEGIN = '# Data Begin'
    DATA_END = '# Data End'
    DEV_SIGNAL_BEGIN = '# Dev signal List Begin'
    DEV_SIGNAL_END = '# Dev signal List End'
    LOG_THREAD_BEGIN = '# LogThread Begin'
    LOG_THREAD_END = '# LogThread End'
    TC_MAIN_BEGIN = '# TC main Begin'
    TC_MAIN_END = '# TC main End'


@dataclass
class SignalInfo:
    """Signal information data class"""
    device: str
    frame: str
    signal: str
    frame_type: str = FrameType.NORMAL.value
    message_type: str = MessageType.PERIOD.value
    timeout: float = UpdatePyConstants.DEFAULT_TIMEOUT
    symbol: str = ""


@dataclass
class TestData:
    """Test data container"""
    input_data: List[List[Any]] = field(default_factory=list)
    expected_data: List[List[Any]] = field(default_factory=list)
    input_signals: List[SignalInfo] = field(default_factory=list)
    output_signals: List[SignalInfo] = field(default_factory=list)
    all_signals: List[List[str]] = field(default_factory=list)


@dataclass
class TestConfig:
    """Test configuration data class"""
    sample_rate: float = UpdatePyConstants.DEFAULT_SAMPLE_RATE
    time_type: str = TimeType.DELTA.value
    judge_type: str = "same"
    num_match: int = 0
    fill_zero: bool = True


class UpdatePyError(Exception):
    """Custom exception for UpdatePy errors"""
    pass


class TemplateError(UpdatePyError):
    """Custom exception for template errors"""
    pass


class SignalProcessingError(UpdatePyError):
    """Custom exception for signal processing errors"""
    pass


class CodeTemplates:
    """Code templates for test generation"""

    @staticmethod
    def get_header_template() -> str:
        """Get the main header template"""
        return '''
# USE DB INTERFACE
import pandas as pd
import numpy as np
from threading import Thread
from tqdm import tqdm
import time
from Lib.Common import export_csv_list, to_hex_big_lst
from Lib.Inst import canBus, debug
from Lib.DataProcess import signal_step_graph, judge_final_result, find_out_signals_for_col


OUTPUT_PATH = ''
title = []
outcome = [title]

# Data Begin
# Data End

# Dev signal List Begin
# Dev signal List End

out_col = find_out_signals_for_col(dev_out_sigs)
total_col = ['Step', 'Elapsed_Time'] + [f'In: {sig[2]}' for sig in dev_in_sigs] + out_col
outcome.append(total_col)

# LogThread Begin
# LogThread End

# TC main Begin
# TC main End
'''

    @staticmethod
    def get_log_thread_template() -> str:
        """Get the log thread template"""
        return '''
class LogThread(Thread):
    def __init__(self, can_bus):
        super().__init__()
        self.can = can_bus
        self.in_data = [None for _ in range({len_in})]
        self.log_state = False
        self.log_lst = []
        self.step = 0
        self.sample_rate = {sample_rate}
        self.start_test = time.time()

    def run(self):
        while True:
            if self.log_state:
                out_data = []
{read_msg}
                elapsed = round((time.time() - self.start_test), 2)
                self.log_lst.append([self.step, elapsed] + self.in_data + out_data)
            time.sleep(self.sample_rate)
'''

    @staticmethod
    def get_main_template() -> str:
        """Get the main test template"""
        return '''
# Initialize all variables
canBus.stop_all_period_msg()

debug.reinitialize()
time.sleep(0.5)

# Measure Data Thread 설정
log_th = LogThread(can_bus=canBus)
log_th.start()
log_th.log_state = True  # log start

start_time = log_th.start_test
elapsed_time = 0
for i in tqdm(input_data,
              total=len(input_data),  # 전체 진행수
              desc='Running',  # 진행률 앞쪽 출력 문장
              ncols=100,  # 진행률 출력 폭 조절
              leave=True,  # True 반복문 완료시 진행률 출력 남김. False 남기지 않음.
              colour='green'  # Bar 색
              ):
    if i[2] == 255:
        log_th.step = int(i[0])
        i[2] = None
        log_th.in_data = i[2:]

        canBus.stop_all_period_msg()
        debug.reinitialize()
    elif i[2] == 254:
        log_th.step = int(i[0])
        i[2] = None
        log_th.in_data = i[2:]

        canBus.stop_all_period_msg()
    elif i[2] == 253:
        log_th.step = int(i[0])
        i[2] = None
        log_th.in_data = i[2:]
    
    
    else:
{write_msg}

    log_th.step = int(i[0])
    log_th.in_data = i[2:]

    time.sleep(i[1])

log_th.log_state = False  # log stop

for log_lst in log_th.log_lst:
    outcome.append(log_lst)

df_log = pd.DataFrame(np.array(log_th.log_lst, dtype=np.float32), columns=total_col)
df_log['Step'] = df_log['Step'].astype(int) 
signal_step_graph(df=df_log.copy(), sigs=dev_all_sigs, x_col='Elapsed_Time', filepath=OUTPUT_PATH, filename=title[0], fill_zero=True)

# Result judgement logic
JUDGE_TYPE = "same"  # define type to judge data
NUM_OF_MATCH = 0  # define criteria for matching rows
outcome = judge_final_result(df_result=df_log[['Step'] + out_col], expected_outs=expected_data, num_match=NUM_OF_MATCH, meas_log=outcome.copy(), out_col=out_col, judge=JUDGE_TYPE)
export_csv_list(OUTPUT_PATH, title[0], outcome)
'''


class SignalProcessor:
    """Signal processing utilities"""

    @staticmethod
    def parse_signal_info(column_name: str) -> SignalInfo:
        """
        Parse signal information from column name

        Args:
            column_name: Column name containing signal information

        Returns:
            SignalInfo object
        """
        try:
            # Clean and split the column name
            clean_name = column_name.replace(UpdatePyConstants.OUTPUT_PREFIX, '').strip()
            parts = [part.strip() for part in clean_name.split(', ')]

            if len(parts) < 2:
                raise SignalProcessingError(f"Invalid signal format: {column_name}")

            signal_info = SignalInfo(
                device=parts[0],
                frame=parts[1] if len(parts) > 1 else "",
                signal=parts[2] if len(parts) > 2 else parts[1]
            )

            # Process additional signal properties
            if signal_info.device in DeviceType.DEBUG.value:
                signal_info.symbol = parts[-1] if len(parts) > 2 else parts[1]
                signal_info.frame = ""
            else:
                SignalProcessor._process_can_signal_properties(signal_info)

            return signal_info

        except Exception as e:
            raise SignalProcessingError(f"Failed to parse signal info from '{column_name}': {e}")

    @staticmethod
    def _process_can_signal_properties(signal_info: SignalInfo):
        """Process CAN signal specific properties"""
        if signal_info.device in DeviceType.DEBUG.value:
            return

        try:
            # Determine frame type based on message ID
            msg_id = canBus.devs[signal_info.device].get_msg_id(signal_info.frame)
            signal_info.frame_type = (FrameType.EXTENDED.value
                                      if msg_id > UpdatePyConstants.EXTENDED_ID_THRESHOLD
                                      else FrameType.NORMAL.value)

            # Determine message type and timeout based on frame name
            if UpdatePyConstants.EVENT_MARKER in signal_info.frame:
                signal_info.message_type = MessageType.EVENT.value
                signal_info.timeout = UpdatePyConstants.DEFAULT_TIMEOUT
            else:
                # Extract period from frame name
                for part in signal_info.frame.split('_'):
                    if UpdatePyConstants.TIME_SUFFIX in part:
                        period_ms = int(part.replace(UpdatePyConstants.TIME_SUFFIX, ''))
                        if period_ms <= 0:
                            signal_info.message_type = MessageType.EVENT.value
                            signal_info.timeout = UpdatePyConstants.DEFAULT_TIMEOUT
                        else:
                            signal_info.message_type = MessageType.PERIOD.value
                            signal_info.timeout = float(period_ms) / 1000
                        break
                else:
                    # Default to period if no timing info found
                    signal_info.message_type = MessageType.PERIOD.value
                    signal_info.timeout = UpdatePyConstants.DEFAULT_PERIOD

        except Exception as e:
            print(f"Warning: Failed to process CAN signal properties for {signal_info.device}: {e}")
            # Set safe defaults
            signal_info.frame_type = FrameType.NORMAL.value
            signal_info.message_type = MessageType.PERIOD.value
            signal_info.timeout = UpdatePyConstants.DEFAULT_PERIOD


class UpdatePy:
    """
    Optimized UpdatePy class for test script generation and management
    """

    def __init__(self):
        """Initialize UpdatePy with default settings"""
        self.py_path = ''
        self.py_title = ''
        self.py_sub_title = ''
        self.py_output_path = ''
        self.db_interface = False
        self.in_out_sigs: List[List[str]] = []
        self.templates = CodeTemplates()

    def update_py(self) -> Tuple[str, Optional[pd.DataFrame]]:
        """
        Update Python test script with optimized error handling

        Returns:
            Tuple of (generated_code, test_case_dataframe)
        """
        try:
            # Parse the script file
            code = self._parse_script_file()
            df_test_case = None

            if self.db_interface:
                df_test_case = self._process_database_interface(code)
                code = df_test_case[0]  # Updated code
                df_test_case = df_test_case[1]  # DataFrame
            else:
                self.py_sub_title = Path(self.py_path).stem
            return code, df_test_case

        except Exception as e:
            print(f"Error updating Python script: {e}")
            raise UpdatePyError(f"Failed to update Python script: {e}")

    def _parse_script_file(self) -> str:
        """
        Parse script file and determine interface type

        Returns:
            Script content as string
        """
        self.db_interface = False

        if os.path.isfile(self.py_path):
            try:
                with open(to_raw(self.py_path), "r+", encoding='utf-8') as file:
                    lines = file.readlines()
            except Exception as e:
                raise UpdatePyError(f"Failed to read script file {self.py_path}: {e}")
        else:
            # Use default template if file doesn't exist
            lines = self.templates.get_header_template().splitlines(True)[1:]

        # Check if using database interface
        if lines and UpdatePyConstants.USE_DB_INTERFACE in lines[0]:
            self.db_interface = True

        return self._fill_header_variables(lines)

    def _process_database_interface(self, code: str) -> Tuple[str, Optional[pd.DataFrame]]:
        """
        Process database interface and generate code

        Args:
            code: Base code template

        Returns:
            Tuple of (updated_code, test_dataframe)
        """
        try:
            # Load CSV data
            csv_path = self.py_path.replace(UpdatePyConstants.PY_EXT, UpdatePyConstants.CSV_EXT)
            csv_data = load_csv_list(file_path=csv_path)

            if len(csv_data) < 8:
                raise UpdatePyError(f"Invalid CSV format in {csv_path}")

            # Extract configuration from CSV
            self.py_sub_title = csv_data[0][1]
            config = TestConfig(
                sample_rate=float(csv_data[1][1]),
                time_type=csv_data[2][1],
                judge_type=csv_data[3][1],
                num_match=int(csv_data[4][1])
            )

            # Create DataFrame from test data
            df_test_case = pd.DataFrame(csv_data[7:], columns=csv_data[6])

            # Generate code with variables filled
            updated_code, processed_df = self._fill_variables(
                df=df_test_case,
                py_code=code,
                config=config
            )

            return updated_code, processed_df

        except Exception as e:
            raise UpdatePyError(f"Failed to process database interface: {e}")

    def _fill_variables(self, df: pd.DataFrame, py_code: str, config: TestConfig) -> Tuple[str, pd.DataFrame]:
        """
        Fill template variables with test data

        Args:
            df: Test case DataFrame
            py_code: Template code
            config: Test configuration

        Returns:
            Tuple of (filled_code, processed_dataframe)
        """
        try:
            # Clean DataFrame
            clean_df = self._clean_dataframe(df)

            # Process signals and generate test data
            test_data = self._process_signals_and_data(clean_df)

            # Prepare code replacements
            replacements = self._prepare_code_replacements(test_data, config)

            # Apply replacements to code
            updated_code = self._apply_replacements(py_code, replacements)

            # Apply additional configurations
            updated_code = self._apply_config_modifications(updated_code, config)

            # Process DataFrame for output
            processed_df = self._process_dataframe_for_output(df)

            return updated_code, processed_df

        except Exception as e:
            raise UpdatePyError(f"Failed to fill variables: {e}")

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and prepare DataFrame"""
        # Remove scenario column if present and convert to numeric
        if 'Scenario' in df.columns:
            clean_df = df.drop(['Scenario'], axis=1).apply(pd.to_numeric, errors='coerce')
        else:
            clean_df = df.apply(pd.to_numeric, errors='coerce')

        return clean_df

    def _process_signals_and_data(self, df: pd.DataFrame) -> TestData:
        """
        Process signals and extract test data

        Args:
            df: Clean DataFrame

        Returns:
            TestData object with processed information
        """
        columns = df.columns.values

        # Separate input and output columns
        input_cols, output_cols = self._separate_input_output_columns(columns)

        # Store signal information for external use
        self.in_out_sigs = [input_cols[2:], output_cols[1:]]

        # Process signal information
        input_signals, output_signals, all_signals = self._process_signal_information(columns)

        # Extract data arrays
        input_data = df[input_cols].to_numpy().tolist()
        output_data = df[output_cols].to_numpy().tolist()

        # Replace NaN with None for JSON serialization
        input_data = self._replace_nan_with_none(input_data)
        output_data = self._replace_nan_with_none(output_data)

        return TestData(
            input_data=input_data,
            expected_data=output_data,
            input_signals=input_signals,
            output_signals=output_signals,
            all_signals=all_signals
        )

    def _separate_input_output_columns(self, columns: np.ndarray) -> Tuple[List[str], List[str]]:
        """Separate input and output columns"""
        input_cols = columns[:UpdatePyConstants.SIGNAL_START_INDEX].tolist()  # Step, Time
        output_cols = columns[:1].tolist()  # Step only

        for col in columns[UpdatePyConstants.SIGNAL_START_INDEX:]:
            if UpdatePyConstants.OUTPUT_PREFIX in col:
                output_cols.append(col)
            else:
                input_cols.append(col)

        return input_cols, output_cols

    def _process_signal_information(self, columns: np.ndarray) -> Tuple[
        List[SignalInfo], List[SignalInfo], List[List[str]]]:
        """Process signal information from column names"""
        input_signals = []
        output_signals = []

        for col in columns[UpdatePyConstants.SIGNAL_START_INDEX:]:
            try:
                signal_info = SignalProcessor.parse_signal_info(col)

                if UpdatePyConstants.OUTPUT_PREFIX in col:
                    output_signals.append(signal_info)
                else:
                    input_signals.append(signal_info)

            except SignalProcessingError as e:
                print(f"Warning: Skipping invalid signal column '{col}': {e}")
                continue

        # Create combined signal list for plotting
        all_signals = [[sig.device, sig.frame, sig.signal] for sig in input_signals + output_signals]

        return input_signals, output_signals, all_signals

    def _replace_nan_with_none(self, data: List[List[Any]]) -> List[List[Any]]:
        """Replace NaN values with None for better JSON serialization"""
        return [[None if pd.isna(item) else item for item in row] for row in data]

    def _prepare_code_replacements(self, test_data: TestData, config: TestConfig) -> List[Tuple[str, str, str]]:
        """Prepare code replacement tuples"""
        # Convert data to string representation
        input_data_str = str(test_data.input_data).replace('nan', 'None')
        output_data_str = str(test_data.expected_data).replace('nan', 'None')

        # Convert signals to string representation
        input_sigs_str = str([list(sig.__dict__.values()) for sig in test_data.input_signals])
        output_sigs_str = str([list(sig.__dict__.values()) for sig in test_data.output_signals])
        all_sigs_str = str(test_data.all_signals)

        replacements = [
            (
                UpdatePyConstants.DATA_BEGIN,
                UpdatePyConstants.DATA_END,
                f'input_data = {input_data_str}\nexpected_data = {output_data_str}'
            ),
            (
                UpdatePyConstants.DEV_SIGNAL_BEGIN,
                UpdatePyConstants.DEV_SIGNAL_END,
                f'dev_in_sigs = {input_sigs_str}\ndev_out_sigs = {output_sigs_str}\ndev_all_sigs = {all_sigs_str}'
            ),
            (
                UpdatePyConstants.LOG_THREAD_BEGIN,
                UpdatePyConstants.LOG_THREAD_END,
                self._generate_log_thread_code(test_data, config)
            ),
            (
                # Add appropriate input handling
                UpdatePyConstants.TC_MAIN_BEGIN,
                UpdatePyConstants.TC_MAIN_END,
                self._generate_main_code_with_frame_writes(test_data.input_signals)
            )
        ]

        return replacements

    def _generate_log_thread_code(self, test_data: TestData, config: TestConfig) -> str:
        """Generate log thread code"""
        read_msg_code = self._generate_message_read_code(test_data.output_signals)

        return self.templates.get_log_thread_template().format(
            len_in=len(test_data.input_signals),  # input signals
            sample_rate=config.sample_rate,
            read_msg=read_msg_code
        )

    def _generate_message_read_code(self, output_signals: List[SignalInfo]) -> str:
        """Generate code for reading output messages"""
        lines = []
        used_messages = {}
        msg_index = 0

        for signal in output_signals:
            if signal.device == DeviceType.DEBUG.value:
                line = f"                out_data.append(debug.read_symbol(symbol='{signal.symbol}'))"
            else:
                # Create message reading code
                if signal.message_type == MessageType.EVENT.value:
                    msg_read = f"self.can.devs['{signal.device}'].read_event_msg('{signal.frame}', decode_on=False)"
                else:
                    msg_read = f"self.can.devs['{signal.device}'].read_msg_by_frame('{signal.frame}', decode_on=False)"

                # Reuse message variable if same message already read
                if msg_read in used_messages:
                    msg_var = used_messages[msg_read]
                    line = f"                out_data.append({msg_var}['{signal.signal}'] if {msg_var} else None)"
                else:
                    msg_var = f'msg_{msg_index}'
                    used_messages[msg_read] = msg_var
                    msg_index += 1

                    line = (f"                {msg_var} = {msg_read}\n"
                            f"                out_data.append({msg_var}['{signal.signal}'] if {msg_var} else None)")

            lines.append(line)

        return '\n'.join(lines)

    def _generate_main_code_with_frame_writes(self, input_signals: List[SignalInfo]) -> str:
        """Generate main code with frame-based writes"""
        write_msg_code = self._generate_frame_write_code(input_signals)
        return self.templates.get_main_template().format(write_msg=write_msg_code)

    def _generate_frame_write_code(self, input_signals: List[SignalInfo]) -> str:
        """Generate code for writing signals grouped by frame"""
        lines = []
        idx = UpdatePyConstants.SIGNAL_START_INDEX
        # Group signals by frame
        grouped_signals = []
        for frame_name, signals in groupby(input_signals, lambda x: x.frame):
            grouped_signals.append(list(signals))

        for signal_group in grouped_signals:
            if not signal_group:
                continue

            first_signal = signal_group[0]

            if first_signal.device in DeviceType.DEBUG.value:
                debug_lines = []
                for sig in signal_group:
                    # Debugger signals are handled individually
                    debug_lines.append(f"        debug.write_symbol(symbol='{sig.symbol}', value=i[{idx}])")
                    idx += 1
                line = '\n'.join(debug_lines)
            else:
                # CAN signals grouped by frame
                signal_names = [sig.signal for sig in signal_group]
                signal_values = [f"i[{idx + i}]" for i in range(len(signal_group))]
                idx += len(signal_group)

                extended_param = ", is_extended=True" if first_signal.frame_type == FrameType.EXTENDED.value else ""

                if first_signal.message_type == MessageType.EVENT.value:
                    line = (f"        canBus.devs['{first_signal.device}'].send_frame_msg("
                            f"""'{first_signal.frame}', {signal_names}, {str(signal_values).replace("'", "")}, """
                            f"{first_signal.timeout}{extended_param})")
                else:
                    line = (f"        canBus.devs['{first_signal.device}'].send_periodic_frame_msg("
                            f"""'{first_signal.frame}', {signal_names}, {str(signal_values).replace("'", "")}, """
                            f"{first_signal.timeout}{extended_param})")

            lines.append(line)

        return '\n'.join(lines)

    def _apply_replacements(self, code: str, replacements: List[Tuple[str, str, str]]) -> str:
        """Apply code replacements"""
        for start_marker, end_marker, replacement in replacements:
            if start_marker in code:
                try:
                    start_idx, end_idx = find_str_inx(code, start_str=start_marker, end_str=end_marker)
                    code = code.replace(code[start_idx:end_idx], replacement)
                except Exception as e:
                    print(f"Warning: Failed to apply replacement for {start_marker}: {e}")

        return code

    def _apply_config_modifications(self, code: str, config: TestConfig) -> str:
        """Apply configuration-specific modifications"""
        # Apply time type modification
        if config.time_type == TimeType.TOTAL.value:
            code = code.replace(
                'time.sleep(i[1])',
                'while elapsed_time < i[1]:  # Timeout\n         elapsed_time = time.time() - start_time  # Total Time 방식'
            )

        # Apply fill zero configuration
        if not config.fill_zero:
            code = code.replace('fill_zero=True', 'fill_zero=False')

        # Apply judge type and match number
        code = code.replace('JUDGE_TYPE = "same"', f'JUDGE_TYPE = "{config.judge_type}"')
        code = code.replace('NUM_OF_MATCH = 0', f'NUM_OF_MATCH = {config.num_match}')

        return code

    def _process_dataframe_for_output(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process DataFrame for output (replace special codes with readable text)"""
        processed_df = df.copy()
        processed_df = processed_df.replace(str(UpdatePyConstants.CAN_STOP_CODE), 'CAN Stop')
        processed_df = processed_df.replace(str(UpdatePyConstants.RESET_CODE), 'Reset')
        processed_df = processed_df.replace(str(UpdatePyConstants.NVM_DEFAULT), 'NVM Default')
        return processed_df

    def _fill_header_variables(self, lines: List[str]) -> str:
        """Fill header variables in template"""
        updated_lines = []

        for line in lines:
            if "OUTPUT_PATH = " in line:
                line = f"OUTPUT_PATH = r'{self.py_output_path}'\n"
            elif 'title = [' in line:
                line = f"title = [r'{self.py_title}']\n"
            updated_lines.append(line)

        return ''.join(updated_lines)

    # Utility methods for backward compatibility
    def _get_msg_in_out(self, cols: np.ndarray) -> Tuple[
        List[str], List[str], List[List[str]], List[List[str]], List[List[str]], int]:
        """Backward compatibility method - kept for legacy support"""
        print("Warning: Using deprecated _get_msg_in_out method. Consider upgrading to new signal processing.")

        try:
            test_data = self._process_signals_and_data(pd.DataFrame(columns=cols))

            input_cols = cols[:UpdatePyConstants.SIGNAL_START_INDEX].tolist()
            output_cols = cols[:1].tolist()

            for col in cols[UpdatePyConstants.SIGNAL_START_INDEX:]:
                if UpdatePyConstants.OUTPUT_PREFIX in col:
                    output_cols.append(col)
                else:
                    input_cols.append(col)

            # Convert to legacy format
            input_legacy = [[sig.device, sig.frame, sig.signal, sig.frame_type, sig.message_type, str(sig.timeout)]
                            for sig in test_data.input_signals]
            output_legacy = [[sig.device, sig.frame, sig.signal, sig.message_type]
                             for sig in test_data.output_signals]

            return input_cols, output_cols, input_legacy, output_legacy, test_data.all_signals, 0

        except Exception as e:
            print(f"Error in legacy method _get_msg_in_out: {e}")
            return [], [], [], [], [], 0

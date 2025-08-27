import os
import time
import shutil
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager

import yaml
import pandas as pd
import numpy as np

from Lib.Common import isdir_and_make, Configure, load_csv_list
from Lib.DataProcess import make_home_HTML, make_pjt_HTML
from Lib.Inst import get_inst_status, debug
from .updatePy import UpdatePy


class TestResult(Enum):
    """Test result enumeration"""
    PASS = "Pass"
    FAIL = "Fail"
    SKIP = "Skip"


class TestConstants:
    """Test automation constants"""
    RESULT_DIRECTORY = "result"
    CONFIG_DIRECTORY = "config"
    SCRIPT_DIRECTORY = "script"
    INPUT_DIRECTORY = "input"
    DATA_DIRECTORY = "data"
    REMOTE_CONFIG_PATH = "remote"

    DEFAULT_TEST_MAP_FILE = "test_map.yaml"
    MAP_SCRIPT_FILE = "map_script_sw_test.yaml"
    MAP_TEST_MODE_FILE = "map_test_mode.yaml"
    SET_DIRECTORY = "set"

    ARCHIVE_PREFIX = "EILS_"
    SUMMARY_PREFIX = "Summary_"

    TIMEOUT_DEFAULT = 5
    VERSION_FORMAT_LENGTH = 5
    BSW_VERSION_FORMAT = "{}.{}{}.{}.{:02d}"
    OTHER_VERSION_FORMAT = "{}_{}_{}_{}.{}"

    BSW_VERSION_VARS = ['ubE_SoftwareVer1', 'ubE_SoftwareVer2', 'ubE_SoftwareVer3',
                        'ubE_SoftwareVer4', 'ubC_DraftReleaseCnt1']


@dataclass
class TestConfig:
    """Test configuration data class"""
    yaml_path: str
    script_path: str = ""
    result_path: str = ""
    project: str = ""


@dataclass
class TestCaseData:
    """Test case data container"""
    script: Dict[str, Any] = field(default_factory=dict)
    in_out: Dict[str, Any] = field(default_factory=dict)
    project_tc: Dict[str, str] = field(default_factory=dict)
    results: Dict[str, str] = field(default_factory=dict)
    num_lines: int = 0


@dataclass
class TestSummary:
    """Test summary statistics"""
    start_time: str
    end_time: str
    elapsed_time: str
    test_case_names: str
    total_count: int
    pass_count: int
    skip_count: int
    fail_count: int
    fail_cases: str
    total_steps: int


class AutoTestError(Exception):
    """Custom exception for AutoTest errors"""
    pass


class TestExecutionError(AutoTestError):
    """Custom exception for test execution errors"""
    pass


class ConfigurationError(AutoTestError):
    """Custom exception for configuration errors"""
    pass


class AutoTest(UpdatePy):
    """
    Optimized automated testing class with improved error handling and structure
    """

    def __init__(self, test_yaml: str):
        """
        Initialize AutoTest with configuration

        Args:
            test_yaml: Path to test YAML configuration file
        """
        super().__init__()

        # Initialize core components
        self.df_inst = self._get_instrument_status()
        self.config = self._initialize_config(test_yaml)
        self.test_map, self.total_map = self._load_test_maps()

        # Initialize test data containers
        self.test_data = TestCaseData()
        self.version: Optional[pd.DataFrame] = None
        self.test_case: List[str] = []

    def _get_instrument_status(self) -> pd.DataFrame:
        """Get instrument status with error handling"""
        try:
            return get_inst_status()
        except Exception as e:
            print(f"Warning: Failed to get instrument status: {e}")
            return pd.DataFrame()

    def _initialize_config(self, test_yaml: str) -> TestConfig:
        """
        Initialize and validate test configuration

        Args:
            test_yaml: Path to test YAML file

        Returns:
            TestConfig object
        """
        if os.path.isfile(test_yaml):
            yaml_path = test_yaml
        else:
            yaml_path = os.path.join(
                TestConstants.DATA_DIRECTORY,
                TestConstants.CONFIG_DIRECTORY,
                TestConstants.REMOTE_CONFIG_PATH,
                TestConstants.DEFAULT_TEST_MAP_FILE
            )
            print(f"Test YAML not found at {test_yaml}, using default: {yaml_path}")

        if not os.path.isfile(yaml_path):
            raise ConfigurationError(f"Test configuration file not found: {yaml_path}")

        return TestConfig(yaml_path=yaml_path)

    def _load_test_maps(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Load test maps from YAML configuration

        Returns:
            Tuple of (test_map, total_map)
        """
        try:
            with open(self.config.yaml_path, encoding="utf-8") as f:
                content = f.read()

            # Load twice to create separate instances
            auto_dict = yaml.safe_load(content)
            total_dict = yaml.safe_load(content)

            if not auto_dict:
                raise ConfigurationError("Empty test configuration file")

            return auto_dict, total_dict

        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML format in {self.config.yaml_path}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load test maps: {e}")

    @contextmanager
    def test_execution_context(self):
        """Context manager for test execution"""
        print("*" * 60)
        print("*** SW TEST Automation Test Start!")
        print("*** Please Do not try additional command until it completes")
        print("*" * 60)

        start_time = time.time()
        try:
            yield start_time
        finally:
            print("*" * 60)
            print("*** SW TEST Automation Test completed")
            print("*" * 60)

    def run(self):
        """Execute the complete test automation process"""
        with self.test_execution_context() as start_time:
            self._setup_test_environment(start_time)

            try:
                self.version = self._get_software_version()
                print(f"SW version\n{self.version}\n")

                total_results = self._execute_tests()
                self._generate_final_report(total_results)

            except Exception as e:
                print(f"Test execution failed: {e}")
                raise TestExecutionError(f"Test execution failed: {e}")
            finally:
                self._cleanup_and_archive()

    def _setup_test_environment(self, start_time: float):
        """Setup test environment and directories"""
        start_time_str = time.strftime("%a, %d-%b-%Y %I:%M:%S", time.localtime(start_time))
        print(f'Starting at: {start_time_str}')

        timestamp = time.strftime('%Y%m%d_%H%M%S', time.localtime(start_time))
        self.config.result_path = os.path.join(
            os.getcwd(),
            TestConstants.DATA_DIRECTORY,
            TestConstants.RESULT_DIRECTORY,
            timestamp
        )

        try:
            isdir_and_make(self.config.result_path)
        except Exception as e:
            raise AutoTestError(f"Failed to create result directory: {e}")

    def _execute_tests(self) -> Dict[str, Dict[str, str]]:
        """
        Execute tests for all projects or single project

        Returns:
            Dictionary of test results by project
        """
        total_results = {}

        if self.config.project:
            # Single project mode
            self._execute_project_tests()
            total_results[self.config.project] = self.test_data.results
        else:
            # Multiple projects mode
            for project_name in self.test_map.keys():
                self.config.project = project_name
                self._execute_project_tests()
                total_results[self.config.project] = dict(self.test_data.results)

        return total_results

    def _execute_project_tests(self):
        """Execute tests for a specific project"""
        self.config.script_path = os.path.join(
            TestConstants.DATA_DIRECTORY,
            TestConstants.INPUT_DIRECTORY,
            TestConstants.SCRIPT_DIRECTORY,
            self.config.project
        )

        project_tests = self.test_map[self.config.project].get('case', [])
        num_tests = len(project_tests)

        print("*" * 60)
        print(f"*** Module: {self.config.project}")
        print(f"*** Test Script: {', '.join(project_tests)}")
        print(f"*** Number of Test: {num_tests}")
        print("*" * 60)

        start_time = time.time()

        # Setup project output directory
        project_output_path = os.path.join(self.config.result_path, self.config.project)
        isdir_and_make(project_output_path)
        self.py_output_path = project_output_path

        # Reset test data for this project
        self._reset_test_data()

        # Execute individual test cases
        for idx, test_script in enumerate(project_tests):
            print(f'Starting on: {test_script} ({idx + 1}/{num_tests})')

            try:
                result = self._execute_single_test(test_script)
                self.test_data.results[self.py_sub_title] = result
                self.test_data.project_tc[test_script] = self.py_sub_title

                result_status = TestResult.FAIL.value if TestResult.FAIL.value in result else result
                print(f'Result: {result_status}')
                print(f'{test_script} has been Done ({idx + 1}/{num_tests})\n')

            except Exception as e:
                print(f'Error executing {test_script}: {e}')
                self.test_data.results[test_script] = TestResult.FAIL.value

        self._export_project_summary(start_time)

    def _reset_test_data(self):
        """Reset test data containers for new project"""
        self.test_data = TestCaseData()

    def _execute_single_test(self, test_script: str) -> str:
        """
        Execute a single test case

        Args:
            test_script: Name of the test script

        Returns:
            Test result string
        """
        self.py_title = test_script
        py_file_path = os.path.join(self.config.script_path, f'{test_script}.py')
        csv_file_path = os.path.join(self.config.script_path, f'{test_script}.csv')
        result_file_path = os.path.join(self.py_output_path, f'{test_script}.csv')

        # Check if test files exist
        if not (os.path.isfile(py_file_path) or os.path.isfile(csv_file_path)):
            return TestResult.SKIP.value

        # Execute test if result doesn't exist
        if not os.path.isfile(result_file_path):
            try:
                self.py_path = py_file_path
                py_lines, df_tc = self.update_py()

                if df_tc is not None:
                    self.test_data.script[test_script] = df_tc
                    self.test_data.in_out[test_script] = self.in_out_sigs
                    self.test_data.num_lines += len(df_tc)

                # Execute the test code
                exec(py_lines)

            except Exception as e:
                print(f"Error executing test {test_script}: {e}")
                return TestResult.FAIL.value

        return self._check_test_result(result_file_path)

    def _check_test_result(self, result_file_path: str) -> str:
        """
        Check test result from CSV file

        Args:
            result_file_path: Path to result CSV file

        Returns:
            Test result string
        """
        if not os.path.isfile(result_file_path):
            return TestResult.SKIP.value

        try:
            csv_data = load_csv_list(result_file_path)
            if csv_data and csv_data[-1]:
                return csv_data[-1][-1].strip()
        except PermissionError:
            print(f"Permission denied accessing result file: {result_file_path}")
        except Exception as e:
            print(f"Error reading result file {result_file_path}: {e}")

        return TestResult.SKIP.value

    def _export_project_summary(self, start_time: float):
        """
        Export project test summary

        Args:
            start_time: Test start time
        """
        end_time = time.time()
        summary = self._calculate_test_summary(start_time, end_time)

        # Create summary DataFrame
        summary_data = [
            summary.start_time, summary.end_time, summary.elapsed_time,
            summary.test_case_names, summary.total_count, summary.pass_count,
            summary.skip_count, summary.fail_count, summary.fail_cases, summary.total_steps
        ]

        summary_index = [
            "Date_Start", "Date_End", "Elapsed_Time", "TestCase_Names",
            "TestCase_Amt", "Pass_Amt", "Skip_Amt", "Fail_Amt", "Fail_Case", "Steps"
        ]

        df_summary = pd.DataFrame(
            np.array(summary_data, dtype=object),
            columns=["Value"],
            index=summary_index
        )

        # Export summary CSV
        summary_file = os.path.join(
            self.py_output_path,
            f"{TestConstants.SUMMARY_PREFIX}{os.path.basename(self.py_output_path)}.csv"
        )
        df_summary.to_csv(summary_file, encoding='utf-8-sig')

        # Print summary
        print(f"*** Number of Pass Test Case: {summary.pass_count}/{summary.total_count}")
        print(f"*** Number of Fail Test Case: {summary.fail_count}/{summary.total_count}")
        print(f"*** The Test for Module {os.path.basename(self.py_output_path)} has been completed\n")

        # Generate HTML report
        self._generate_project_html_report(df_summary)

    def _calculate_test_summary(self, start_time: float, end_time: float) -> TestSummary:
        """
        Calculate test summary statistics

        Args:
            start_time: Test start time
            end_time: Test end time

        Returns:
            TestSummary object
        """
        # Count results
        pass_count = skip_count = fail_count = 0
        fail_cases = []

        for tc_name, tc_result in self.test_data.results.items():
            if tc_result == TestResult.PASS.value:
                pass_count += 1
            elif tc_result == TestResult.SKIP.value:
                skip_count += 1
            else:
                fail_count += 1
                fail_parts = tc_result.split(',')
                if len(fail_parts) == 1:
                    fail_cases.append(tc_name)
                else:
                    step_info = ','.join(fail_parts[1:])
                    fail_cases.append(f'{tc_name} (Step {step_info})')

        # Format times
        start_time_str = time.strftime('%Y-%m-%d,%H:%M:%S', time.localtime(start_time))
        end_time_str = time.strftime('%Y-%m-%d,%H:%M:%S', time.localtime(end_time))
        elapsed_time_str = time.strftime("%H:%M:%S", time.gmtime(end_time - start_time))

        return TestSummary(
            start_time=start_time_str,
            end_time=end_time_str,
            elapsed_time=elapsed_time_str,
            test_case_names=', '.join(self.test_data.results.keys()),
            total_count=len(self.test_data.results),
            pass_count=pass_count,
            skip_count=skip_count,
            fail_count=fail_count,
            fail_cases='Nothing' if not fail_cases else ','.join(fail_cases),
            total_steps=self.test_data.num_lines
        )

    def _generate_project_html_report(self, df_summary: pd.DataFrame):
        """Generate HTML report for project"""
        try:
            df_version = self.version.set_index(keys='Module')
            project_version = df_version.loc[self.config.project, 'Version']
            make_pjt_HTML(
                df_sum=df_summary,
                project=os.path.basename(self.py_output_path),
                version=project_version,
                dict_tc=self.test_data.project_tc,
                tc_script=self.test_data.script,
                tc_in_out=self.test_data.in_out,
                export_path=self.py_output_path
            )

        except Exception as e:
            print(f"Warning: Failed to generate HTML report: {e}")

    def _generate_final_report(self, total_results: Dict[str, Dict[str, str]]):
        """Generate final test report"""
        try:
            make_home_HTML(
                data=total_results,
                export_path=self.config.result_path,
                df_ver=self.version
            )
        except Exception as e:
            print(f"Warning: Failed to generate final report: {e}")

    def _cleanup_and_archive(self):
        """Cleanup and create archive"""
        self.config.project = ''  # Reset for single mode

        try:
            archive_path = Configure.set['system']['archive_path']
            zip_name = f'{TestConstants.ARCHIVE_PREFIX}{os.path.basename(self.config.result_path)}'

            if os.path.exists(archive_path):
                shutil.rmtree(archive_path)

            shutil.make_archive(
                os.path.join(archive_path, zip_name),
                'zip',
                self.config.result_path
            )

            end_time_str = time.strftime("%a, %d-%b-%Y %I:%M:%S", time.localtime(time.time()))
            print(f'Ending at: {end_time_str}')
            print(f"[INFO] {zip_name}.zip has been created\n")

        except Exception as e:
            print(f"Warning: Failed to create archive: {e}")

        time.sleep(1)

    def _get_software_version(self) -> pd.DataFrame:
        """
        Get software version information from target system

        Returns:
            DataFrame with module versions
        """
        try:
            debug.wait_for_ready(timeout=TestConstants.TIMEOUT_DEFAULT)
            version_list = []

            for module in self.test_map.keys():
                try:
                    if module == 'BSW':
                        version = self._get_bsw_version()
                    else:
                        version = self._get_module_version(module)

                    version_list.append([module, version])

                except Exception as e:
                    print(f"Warning: Failed to get version for module {module}: {e}")
                    version_list.append([module, "Unknown"])

            return pd.DataFrame(
                np.array(version_list, dtype=object),
                columns=['Module', 'Version']
            )

        except Exception as e:
            print(f"Error getting software version: {e}")
            return pd.DataFrame(columns=['Module', 'Version'])

    def _get_bsw_version(self) -> str:
        """Get BSW module version"""
        try:
            version_values = []
            for var in TestConstants.BSW_VERSION_VARS[:-1]:
                value = debug.read_symbol(symbol=var)
                version_values.append(chr(int(value)))

            # Last value is formatted differently
            last_value = int(debug.read_symbol(symbol=TestConstants.BSW_VERSION_VARS[-1]))
            version_values.append(last_value)

            return TestConstants.BSW_VERSION_FORMAT.format(*version_values)

        except Exception as e:
            raise AutoTestError(f"Failed to get BSW version: {e}")

    def _get_module_version(self, module: str) -> str:
        """Get version for non-BSW module"""
        try:
            sw_ver_symbol = self.test_map[module].get('version')
            if sw_ver_symbol != 'N/A':
                version_hex = hex(int(debug.read_symbol(symbol=sw_ver_symbol)))
                version_str = version_hex[TestConstants.VERSION_FORMAT_LENGTH:]

                if len(version_str) >= 5:
                    return TestConstants.OTHER_VERSION_FORMAT.format(
                        version_str[0], version_str[1], version_str[2],
                        version_str[3], version_str[4]
                    )
            return "Unknown"

        except Exception as e:
            raise AutoTestError(f"Failed to get version for module {module}: {e}")

    def update_test_case(self, project: str, test_numbers: List[str]):
        """
        Update test case selection for specific project

        Args:
            project: Project name
            test_numbers: List of test numbers to execute
        """
        self.config.project = project

        try:
            map_file_path = os.path.join(
                TestConstants.DATA_DIRECTORY,
                TestConstants.INPUT_DIRECTORY,
                TestConstants.SCRIPT_DIRECTORY,
                project,
                TestConstants.SET_DIRECTORY,
                TestConstants.MAP_SCRIPT_FILE
            )

            with open(map_file_path, encoding='utf-8') as f:
                temp_map = yaml.safe_load(f)

            # Create reverse mapping
            test_case_dict = {str(value): key for key, value in temp_map.items()}

            # Update test case list
            self.test_case = [test_case_dict[num] for num in test_numbers if num in test_case_dict]

        except FileNotFoundError:
            raise ConfigurationError(f"Test case mapping file not found for project {project}")
        except Exception as e:
            raise ConfigurationError(f"Failed to update test cases: {e}")

    def update_map_mode(self, project: str) -> Dict[str, str]:
        """
        Update test mode mapping for project

        Args:
            project: Project name

        Returns:
            Dictionary of test mode mapping
        """
        map_mode_path = os.path.join(
            TestConstants.DATA_DIRECTORY,
            TestConstants.INPUT_DIRECTORY,
            TestConstants.SCRIPT_DIRECTORY,
            project,
            TestConstants.SET_DIRECTORY,
            TestConstants.MAP_TEST_MODE_FILE
        )

        try:
            if os.path.isfile(map_mode_path):
                with open(map_mode_path, encoding='utf-8') as f:
                    return yaml.safe_load(f) or {'N/A': '0'}
            else:
                print(f"Test mode map file not found: {map_mode_path}")
                return {'N/A': '0'}

        except Exception as e:
            print(f"Error loading test mode map: {e}")
            return {'N/A': '0'}

    def stop(self):
        """Stop test execution and cleanup - backward compatibility method"""
        self._cleanup_and_archive()

    def test_module(self):
        """Execute project tests - backward compatibility method"""
        self._execute_project_tests()

    # Utility methods
    @staticmethod
    def validate_project_structure(project_path: str) -> bool:
        """
        Validate project directory structure

        Args:
            project_path: Path to project directory

        Returns:
            True if structure is valid
        """
        required_dirs = [TestConstants.SET_DIRECTORY]
        required_files = [TestConstants.MAP_SCRIPT_FILE]

        for dir_name in required_dirs:
            if not os.path.isdir(os.path.join(project_path, dir_name)):
                return False

        set_path = os.path.join(project_path, TestConstants.SET_DIRECTORY)
        for file_name in required_files:
            if not os.path.isfile(os.path.join(set_path, file_name)):
                return False

        return True

    def get_available_projects(self) -> List[str]:
        """
        Get list of available test projects

        Returns:
            List of project names
        """
        return list(self.test_map.keys()) if self.test_map else []

    def get_project_test_cases(self, project: str) -> List[str]:
        """
        Get test cases for specific project

        Args:
            project: Project name

        Returns:
            List of test case names
        """
        return self.test_map[project].get('case', [])

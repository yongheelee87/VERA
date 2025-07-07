import os
import time
import queue
from threading import Thread, Lock
from typing import Dict, Any, Optional, Union, List, Tuple
from dataclasses import dataclass
from enum import IntEnum

import lauterbach.trace32.rcl as trace32
from lauterbach.trace32.rcl import CommandError
from Lib.Common import check_task_open


class SystemState(IntEnum):
    """System state enumeration"""
    DOWN = 0
    READY = 2
    RUNNING = 3


class CommandType(IntEnum):
    """Command type enumeration for worker thread"""
    READ = 0x01
    WRITE = 0x02
    RESET = 0x03
    RESUME = 0x04


class Trace32Constants:
    """Trace32 protocol constants"""
    DEFAULT_PORT = 20001
    DEFAULT_HOST = 'localhost'
    DEFAULT_PROTOCOL = 'TCP'
    DEFAULT_PACKLEN = 1024
    DEFAULT_TIMEOUT = 10.0
    DEFAULT_COMMAND_TIMEOUT = 10
    MAX_FLASH_TIMEOUT = 10
    MAX_RESET_TIMEOUT = 5
    AUTO_CONNECT_TIMEOUT = 12
    WORKER_RESPONSE_TIMEOUT = 0.2
    READY_COUNT_THRESHOLD = 10
    READY_CHECK_INTERVAL = 0.5
    PROCESS_START_DELAY = 3
    REINIT_DELAY = 0.5


@dataclass
class Trace32Config:
    """Trace32 configuration data class"""
    api_path: str
    auto_open: bool


class Trace32Error(Exception):
    """Custom exception for Trace32 errors"""
    pass


class Trace32ConnectionError(Trace32Error):
    """Custom exception for Trace32 connection errors"""
    pass


class Trace32CommandError(Trace32Error):
    """Custom exception for Trace32 command errors"""
    pass


class Trace32:
    """
    Optimized Trace32 class for debugging and system control
    """

    def __init__(self, config_sys: Dict[str, Any]):
        self.config_sys = config_sys
        self.trace32_config = self._parse_trace32_config()

        # Core components
        self.device: Optional[Any] = None
        self.status = False

        # Thread-safe queues for command processing
        self.command_queue: queue.Queue = queue.Queue()
        self.response_queue: queue.Queue = queue.Queue()
        self.in_reset = False
        self._lock = Lock()
        self._worker_thread: Optional[Thread] = None

        # Initialize if Trace32 is configured
        if self.trace32_config:
            self._initialize_trace32()

    def _parse_trace32_config(self) -> Optional[Trace32Config]:
        """Parse and validate Trace32 configuration"""
        if 'TRACE32' not in self.config_sys:
            return None

        config = self.config_sys['TRACE32']
        required_fields = ['api_path', 'auto_open']

        for field in required_fields:
            if field not in config:
                print(f"Warning: Missing required Trace32 config field: {field}")
                return None

        return Trace32Config(
            api_path=config['api_path'],
            auto_open=config.get('auto_open', False)
        )

    def _initialize_trace32(self):
        """Initialize Trace32 connection and worker thread"""
        try:
            self.connect_dev()

            if self.trace32_config.auto_open and not self._is_trace32_running():
                self._start_trace32_process()
                self.wait_for_connection(timeout=Trace32Constants.AUTO_CONNECT_TIMEOUT)

            # Start worker thread
            self._worker_thread = Thread(target=self._rcl_worker, daemon=True)
            self._worker_thread.start()

            print("Trace32 initialized successfully")

        except Exception as e:
            print(f"Failed to initialize Trace32: {e}")

    def connect_dev(self):
        """
        Establish connection to Trace32 device with improved error handling
        """
        try:
            self.device = trace32.connect(
                node=Trace32Constants.DEFAULT_HOST,
                port=Trace32Constants.DEFAULT_PORT,
                protocol=Trace32Constants.DEFAULT_PROTOCOL,
                packlen=Trace32Constants.DEFAULT_PACKLEN,
                timeout=Trace32Constants.DEFAULT_TIMEOUT
            )
            self.status = True
            print("Trace32 device connected successfully")

        except ConnectionRefusedError as e:
            self.status = False
            print('Error: TRACE32 CONNECTION')
            print('CHECK IF TRACE32 POWERVIEW IS OPENED AND RETRY THE CONNECTION')
            raise Trace32ConnectionError(f"Connection refused: {e}")
        except Exception as e:
            self.status = False
            print(f"Failed to connect to Trace32 device: {e}")
            raise Trace32ConnectionError(f"Connection failed: {e}")

    def check_status(self) -> bool:
        """
        Check and display connection status

        Returns:
            bool: True if connected, False otherwise
        """
        if self.status:
            print('Success: TRACE32 CONNECTION')
            return True
        else:
            print('[INFO] TRACE32 is NOT CONNECTED with HOST')
            print('IF YOU WANT TO USE TRACE32, CHECK IF TRACE32 POWERVIEW IS OPENED AND RETRY THE CONNECTION')
            return False

    def _is_trace32_running(self) -> bool:
        """Check if Trace32 process is currently running"""
        return check_task_open(name="t32mppc.exe")

    def _start_trace32_process(self):
        """Start Trace32 executable process"""
        if not self.trace32_config:
            raise Trace32Error("Trace32 configuration not available")

        t32_exe_path = os.path.join(
            self.trace32_config.api_path,
            'bin',
            'windows64',
            't32mppc.exe'
        )

        if not os.path.exists(t32_exe_path):
            raise Trace32Error(f"Trace32 executable not found: {t32_exe_path}")

        try:
            os.startfile(t32_exe_path)
            time.sleep(Trace32Constants.PROCESS_START_DELAY)
            print('Success: OPEN Trace32')
        except Exception as e:
            raise Trace32Error(f"Failed to start Trace32 process: {e}")

    def wait_for_connection(self, timeout: int):
        """
        Wait for Trace32 connection with timeout

        Args:
            timeout: Maximum time to wait for connection
        """
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            try:
                self.connect_dev()
                if self.status:
                    print("Trace32 connection established")
                    return
            except Trace32ConnectionError:
                pass  # Continue trying

            time.sleep(1)  # Wait before retrying

        raise Trace32ConnectionError(f"Failed to connect within {timeout} seconds")

    def execute_command(self, command: str, timeout: int = Trace32Constants.DEFAULT_COMMAND_TIMEOUT):
        """
        Execute Trace32 command with improved error handling

        Args:
            command: Trace32 command string
            timeout: Command timeout in seconds
        """
        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            self.device.cmd(command)
            self.wait_for_command_completion(timeout=timeout)
        except CommandError as e:
            error_msg = f'Error executing command "{command}": {e}'
            print(error_msg)
            raise Trace32CommandError(error_msg)
        except Exception as e:
            error_msg = f'Unexpected error executing command "{command}": {e}'
            print(error_msg)
            raise Trace32Error(error_msg)

    def change_directory_and_execute(self, script_path: str):
        """
        Change directory and execute script with path validation

        Args:
            script_path: Path to script file including arguments
        """
        script_file = script_path.split()[0]

        if not os.path.exists(script_file):
            error_msg = f'Error: Script file not found: {script_file}'
            print(error_msg)
            raise FileNotFoundError(error_msg)

        try:
            self.execute_command(f"CD.DO {script_path}")
        except Trace32CommandError:
            raise  # Re-raise with original context

    def flash_binary(self, flash_command: str):
        """
        Flash binary with comprehensive error handling and status monitoring

        Args:
            flash_command: Flash command string
        """
        script_file = flash_command.split()[0]

        if not os.path.exists(script_file):
            error_msg = f'Error: Flash script not found: {script_file}'
            print(error_msg)
            raise FileNotFoundError(error_msg)

        try:
            # Execute flash command
            self.device.cmd(f"CD.DO {flash_command}")
            print(f'Flash: CD.DO {flash_command}')

        except Exception as e:
            print(f"Flash command failed, attempting reconnection: {e}")
            self.wait_for_connection(timeout=10)
            self.device.cmd(f"CD.DO {flash_command}")

        # Wait for system to be ready
        self._wait_for_system_ready()

        # Start execution
        self.execute_command('Go')

    def _wait_for_system_ready(self):
        """Wait for system to reach ready state"""
        start_time = time.time()
        ready_count = 0

        while (time.time() - start_time) < Trace32Constants.MAX_FLASH_TIMEOUT:
            if self._get_system_state() == SystemState.READY:
                ready_count += 1
                if ready_count >= Trace32Constants.READY_COUNT_THRESHOLD:
                    print("System ready for execution")
                    return
            else:
                ready_count = 0  # Reset counter if not ready

            time.sleep(Trace32Constants.READY_CHECK_INTERVAL)

        print("Warning: System ready timeout reached")

    def write_symbol(self, symbol: str, value: Union[int, float]):
        """
        Write value to symbol with improved validation

        Args:
            symbol: Symbol name in loaded ELF
            value: Value to write
        """
        if value is None:
            print(f"Warning: Attempted to write None value to symbol '{symbol}'")
            return

        if not symbol.strip():
            raise ValueError("Symbol name cannot be empty")

        try:
            if not self.in_reset:
                self.command_queue.put((CommandType.WRITE, (symbol, value)))
        except Exception as e:
            error_msg = f"Failed to queue write command for symbol '{symbol}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def read_symbol(self, symbol: str) -> Any:
        """
        Read symbol value with improved error handling

        Args:
            symbol: Symbol name in loaded ELF

        Returns:
            Symbol value (scalar types only)
        """
        if not symbol.strip():
            raise ValueError("Symbol name cannot be empty")

        try:
            if not self.in_reset:
                self.command_queue.put((CommandType.READ, symbol))
                result = self.response_queue.get(timeout=Trace32Constants.WORKER_RESPONSE_TIMEOUT)
                return result
            else:
                return 0
        except queue.Empty:
            error_msg = f"Timeout reading symbol '{symbol}'"
            print(error_msg)
            raise Trace32Error(error_msg)
        except Exception as e:
            error_msg = f"Failed to read symbol '{symbol}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def read_symbol_array(self, symbol: str) -> str:
        """
        Read symbol with structure and array support

        Args:
            symbol: Symbol name in loaded ELF

        Returns:
            Raw string value including structures and arrays
        """
        if not symbol.strip():
            raise ValueError("Symbol name cannot be empty")

        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            result = self.device.library.t32_readvariablestring(symbol)
            return result[:-1] if result.endswith('\0') else result
        except Exception as e:
            error_msg = f"Failed to read symbol array '{symbol}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def reset_target(self):
        """Reset target system"""
        try:
            self.command_queue.put((CommandType.RESET, ''))
            self.execute_command('System.ResetTarget')
        except Trace32CommandError:
            raise  # Re-raise with original context

    def reset_and_run(self):
        """Reset target and start execution"""
        try:
            self.reset_target()

            start_time = time.time()
            while (time.time() - start_time) < Trace32Constants.MAX_RESET_TIMEOUT:
                self.execute_command('Go')
                if self._get_system_state() == SystemState.RUNNING:
                    self.command_queue.put((CommandType.RESUME, ''))
                    return

            print("Warning: Target may not be running after reset")

        except Trace32CommandError:
            raise  # Re-raise with original context

    def get_breakpoint_list(self) -> List[str]:
        """
        Get list of active breakpoint names

        Returns:
            List of breakpoint symbol names
        """
        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            breakpoints = []
            for bp in self.device.breakpoint.list():
                try:
                    symbol = self.device.symbol.query_by_address(address=bp.address)
                    breakpoints.append(symbol.name)
                except Exception:
                    # If symbol lookup fails, use address
                    breakpoints.append(f"0x{bp.address:08X}")
            return breakpoints
        except Exception as e:
            error_msg = f"Failed to get breakpoint list: {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def set_breakpoint(self, symbol_name: str) -> bool:
        """
        Set breakpoint at symbol location

        Args:
            symbol_name: Symbol name for breakpoint

        Returns:
            True if successful
        """
        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            symbol = self.device.symbol.query_by_name(name=symbol_name)
            self.device.breakpoint.set(address=symbol.address)
            print(f"Breakpoint set at '{symbol_name}'")
            return True
        except Exception as e:
            error_msg = f"Failed to set breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def delete_breakpoint(self, symbol_name: str) -> bool:
        """
        Delete breakpoint at symbol location

        Args:
            symbol_name: Symbol name for breakpoint

        Returns:
            True if successful
        """
        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            symbol = self.device.symbol.query_by_name(name=symbol_name)
            self.device.breakpoint.delete(address=symbol.address)
            print(f"Breakpoint deleted at '{symbol_name}'")
            return True
        except Exception as e:
            error_msg = f"Failed to delete breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def disable_breakpoint(self, symbol_name: str) -> bool:
        """
        Disable breakpoint at symbol location

        Args:
            symbol_name: Symbol name for breakpoint

        Returns:
            True if successful
        """
        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            symbol = self.device.symbol.query_by_name(name=symbol_name)
            self.device.breakpoint.disable(address=symbol.address)
            print(f"Breakpoint disabled at '{symbol_name}'")
            return True
        except Exception as e:
            error_msg = f"Failed to disable breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def enable_breakpoint(self, symbol_name: str) -> bool:
        """
        Enable breakpoint at symbol location

        Args:
            symbol_name: Symbol name for breakpoint

        Returns:
            True if successful
        """
        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            symbol = self.device.symbol.query_by_name(name=symbol_name)
            self.device.breakpoint.enable(address=symbol.address)
            print(f"Breakpoint enabled at '{symbol_name}'")
            return True
        except Exception as e:
            error_msg = f"Failed to enable breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def reinitialize(self):
        """Reinitialize target system"""
        try:
            time.sleep(Trace32Constants.REINIT_DELAY)
            self.reset_and_run()
        except Exception as e:
            error_msg = f"Failed to reinitialize: {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def wait_for_command_completion(self, timeout: int):
        """
        Wait for command completion with timeout

        Args:
            timeout: Maximum time to wait
        """
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            try:
                practice_state = self.device.library.t32_getpracticestate()
                if practice_state == 0:  # Command completed
                    return
            except Exception as e:
                print(f"Error checking practice state: {e}")
                break

            time.sleep(0.1)  # Small delay to prevent excessive polling

        print(f"Warning: Command completion timeout after {timeout} seconds")

    def _get_system_state(self) -> SystemState:
        """
        Get current system state

        Returns:
            Current system state
        """
        if not self.status:
            return SystemState.DOWN

        try:
            state_bytes = self.device.get_state()
            state_value = int.from_bytes(state_bytes, "big")
            return SystemState(state_value)
        except Exception as e:
            print(f"Error getting system state: {e}")
            return SystemState.DOWN

    def _rcl_worker(self):
        """
        Worker thread for handling read/write commands
        Enhanced with better error handling and logging
        """
        print("Trace32 RCL worker thread started")

        while True:
            try:
                command_type, args = self.command_queue.get(timeout=1.0)

                if command_type == CommandType.READ:
                    try:
                        result = self.device.variable.read(args).value
                        self.response_queue.put(result)
                    except Exception as e:
                        print(f"Error reading variable '{args}': {e}")
                        self.response_queue.put(None)

                elif command_type == CommandType.WRITE:
                    try:
                        symbol_name, value = args
                        self.device.variable.write(symbol_name, value)
                    except Exception as e:
                        print(f"Error writing variable '{args[0]}': {e}")

                elif command_type == CommandType.RESET:
                    self.in_reset = True

                elif command_type == CommandType.RESUME:
                    self.in_reset = False

                else:
                    print(f"Unknown command type: {command_type}")

                self.command_queue.task_done()

            except queue.Empty:
                continue  # Normal timeout, continue loop
            except Exception as e:
                print(f"Unexpected error in RCL worker: {e}")
                break

        print("Trace32 RCL worker thread stopped")

    def disconnect(self):
        """Safely disconnect from Trace32"""
        try:
            if self.device:
                # Clear any pending commands
                while not self.command_queue.empty():
                    try:
                        self.command_queue.get_nowait()
                        self.command_queue.task_done()
                    except queue.Empty:
                        break

                self.device = None
                self.status = False
                print("Trace32 disconnected successfully")
        except Exception as e:
            print(f"Error during disconnect: {e}")

    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            self.disconnect()
        except:
            pass

    # Compatibility methods for backward compatibility
    def cmd(self, str_cmd: str, time_out: int = Trace32Constants.DEFAULT_COMMAND_TIMEOUT):
        """Backward compatibility method for execute_command"""
        return self.execute_command(str_cmd, time_out)

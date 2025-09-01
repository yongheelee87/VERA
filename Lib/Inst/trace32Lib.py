import os
import time
import queue
from threading import Thread, Event, Lock
from typing import Dict, Any, Optional, Union, List, Callable
from contextlib import contextmanager
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
    READ = 1
    WRITE = 2
    RESET = 3
    RESUME = 4


@dataclass(frozen=True)
class Trace32Constants:
    """Trace32 protocol constants - using dataclass for better memory usage"""
    DEFAULT_PORT: int = 20001
    DEFAULT_HOST: str = 'localhost'
    DEFAULT_PROTOCOL: str = 'TCP'
    DEFAULT_PACKLEN: int = 1024
    DEFAULT_TIMEOUT: float = 10.0
    DEFAULT_COMMAND_TIMEOUT: int = 10
    MAX_FLASH_TIMEOUT: int = 10
    MAX_RESET_TIMEOUT: int = 5
    AUTO_CONNECT_TIMEOUT: int = 12
    WORKER_RESPONSE_TIMEOUT: float = 0.2
    WORKER_QUEUE_TIMEOUT: float = 1.0
    READY_COUNT_THRESHOLD: int = 10
    READY_CHECK_INTERVAL: float = 0.5
    PROCESS_START_DELAY: int = 3
    REINIT_DELAY: float = 0.5
    POLL_INTERVAL: float = 0.1
    MAX_RETRIES: int = 3
    CONNECTION_RETRY_DELAY: float = 1.0


@dataclass
class Trace32Config:
    """Trace32 configuration data class"""
    api_path: str
    auto_open: bool


class Trace32Error(Exception):
    """Base exception for Trace32 errors"""
    pass


class Trace32ConnectionError(Trace32Error):
    """Exception for Trace32 connection errors"""
    pass


class Trace32CommandError(Trace32Error):
    """Exception for Trace32 command errors"""
    pass


class Trace32TimeoutError(Trace32Error):
    """Exception for Trace32 timeout errors"""
    pass


class Trace32:
    """
    Optimized Trace32 class for debugging and system control

    Key optimizations:
    - Pre-cached method references for hot paths
    - Improved thread safety with proper synchronization
    - Reduced memory allocations in critical sections
    - Enhanced error handling and recovery mechanisms
    """

    __slots__ = (
        'config', 'trace32_config', 'device', 'status', 'command_queue',
        'response_queue', 'in_reset', '_worker_thread', '_shutdown_event',
        '_reset_lock', '_handlers', '_cached_refs'
    )

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.trace32_config = self._parse_trace32_config()

        # Core components
        self.device: Optional[Any] = None
        self.status = False

        # Thread synchronization
        self.command_queue: queue.Queue = queue.Queue()
        self.response_queue: queue.Queue = queue.Queue()
        self.in_reset = False
        self._worker_thread: Optional[Thread] = None
        self._shutdown_event = Event()
        self._reset_lock = Lock()

        # Initialize if Trace32 is configured
        if self.trace32_config:
            self._initialize_trace32()

        # Setup cached references and handlers
        self._cached_refs = {}
        self._setup_cached_references()
        self._handlers = self._setup_handlers()

    def _parse_trace32_config(self) -> Optional[Trace32Config]:
        """Parse and validate Trace32 configuration"""
        required_fields = ['api_path', 'auto_open']

        missing_fields = [field for field in required_fields if field not in self.config]
        if missing_fields:
            print(f"Warning: Missing required Trace32 config fields: {missing_fields}")
            return None

        return Trace32Config(
            api_path=self.config['api_path'],
            auto_open=self.config.get('auto_open', False)
        )

    def _setup_cached_references(self) -> None:
        """Pre-cache frequently used method references for performance"""
        if not self.device:
            return

        try:
            self._cached_refs.update({
                'device_read': self.device.variable.read,
                'device_write': self.device.variable.write,
                'queue_put': self.response_queue.put,
                'library': self.device.library,
                'breakpoint': self.device.breakpoint,
                'symbol': self.device.symbol,
            })
        except AttributeError:
            # Device not fully initialized yet
            pass

    def _setup_handlers(self) -> Dict[int, Callable]:
        """Setup optimized command handlers"""
        return {
            CommandType.READ: self._handle_read,
            CommandType.WRITE: self._handle_write,
            CommandType.RESET: self._handle_reset,
            CommandType.RESUME: self._handle_resume,
        }

    def _handle_read(self, symbol_name: str) -> None:
        """Optimized read handler with cached references"""
        try:
            if 'device_read' in self._cached_refs:
                result = self._cached_refs['device_read'](symbol_name).value
                self._cached_refs['queue_put'](result)
            else:
                self.response_queue.put(None)
        except Exception as e:
            print(f"Error reading variable '{symbol_name}': {e}")
            self.response_queue.put(None)

    def _handle_write(self, args: tuple) -> None:
        """Optimized write handler with cached references"""
        try:
            symbol_name, value = args
            if 'device_write' in self._cached_refs:
                self._cached_refs['device_write'](symbol_name, value)
        except Exception as e:
            print(f"Error writing variable '{args[0]}': {e}")

    def _handle_reset(self, _: Any) -> None:
        """Thread-safe reset handler"""
        with self._reset_lock:
            self.in_reset = True

    def _handle_resume(self, _: Any) -> None:
        """Thread-safe resume handler"""
        with self._reset_lock:
            self.in_reset = False

    def _initialize_trace32(self) -> None:
        """Initialize Trace32 connection and worker thread"""
        try:
            self.connect_dev()

            if self.trace32_config.auto_open and not self._is_trace32_running():
                self._start_trace32_process()
                self.wait_for_connection(timeout=Trace32Constants.AUTO_CONNECT_TIMEOUT)

            self._start_worker_thread()
            print("Trace32 initialized successfully")

        except Exception as e:
            print(f"Failed to initialize Trace32: {e}")
            raise

    def _start_worker_thread(self) -> None:
        """Start the worker thread with proper error handling"""
        self._worker_thread = Thread(target=self._rcl_worker, daemon=True)
        self._worker_thread.start()

    def connect_dev(self) -> None:
        """Establish connection to Trace32 device with improved error handling"""
        try:
            self.device = trace32.connect(
                node=Trace32Constants.DEFAULT_HOST,
                port=Trace32Constants.DEFAULT_PORT,
                protocol=Trace32Constants.DEFAULT_PROTOCOL,
                packlen=Trace32Constants.DEFAULT_PACKLEN,
                timeout=Trace32Constants.DEFAULT_TIMEOUT
            )

            # Setup cached references after successful connection
            self._setup_cached_references()

            self.status = True
            print("Trace32 device connected successfully")

        except ConnectionRefusedError as e:
            self._handle_connection_error("Connection refused - check if Trace32 PowerView is opened")
            raise Trace32ConnectionError(f"Connection refused: {e}")
        except Exception as e:
            self._handle_connection_error(f"Connection failed: {e}")
            raise Trace32ConnectionError(f"Connection failed: {e}")

    def _handle_connection_error(self, message: str) -> None:
        """Handle connection errors with consistent messaging"""
        self.status = False
        print(f'Error: TRACE32 CONNECTION - {message}')
        print('CHECK IF TRACE32 POWERVIEW IS OPENED AND RETRY THE CONNECTION')

    def check_status(self) -> bool:
        """Check and display connection status"""
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

    def _start_trace32_process(self) -> None:
        """Start Trace32 executable process with improved error handling"""
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

    def wait_for_connection(self, timeout: int) -> None:
        """Wait for Trace32 connection with timeout and retry logic"""
        start_time = time.time()
        last_error = None

        while (time.time() - start_time) < timeout:
            if self._shutdown_event.is_set():
                raise Trace32ConnectionError("Shutdown requested during connection wait")

            try:
                self.connect_dev()
                if self.status:
                    print("Trace32 connection established")
                    return
            except Trace32ConnectionError as e:
                last_error = e
                time.sleep(Trace32Constants.CONNECTION_RETRY_DELAY)

        error_msg = f"Failed to connect within {timeout} seconds"
        if last_error:
            error_msg += f". Last error: {last_error}"
        raise Trace32ConnectionError(error_msg)

    @contextmanager
    def _reset_context(self):
        """Context manager for reset state"""
        with self._reset_lock:
            yield self.in_reset

    def execute_command(self, command: str, timeout: int = Trace32Constants.DEFAULT_COMMAND_TIMEOUT) -> None:
        """Execute Trace32 command with improved error handling and retry logic"""
        if not self.status:
            raise Trace32Error("Device not connected")

        for attempt in range(Trace32Constants.MAX_RETRIES):
            try:
                self.device.cmd(command)
                self.wait_for_ready(timeout=timeout)
                return
            except CommandError as e:
                if attempt == Trace32Constants.MAX_RETRIES - 1:
                    error_msg = f'Error executing command "{command}": {e}'
                    print(error_msg)
                    raise Trace32CommandError(error_msg)
                print(f"Command attempt {attempt + 1} failed, retrying: {e}")
            except Exception as e:
                error_msg = f'Unexpected error executing command "{command}": {e}'
                print(error_msg)
                raise Trace32Error(error_msg)

    def change_directory_and_execute(self, script_path: str) -> None:
        """Change directory and execute script with path validation"""
        script_file = script_path.split()[0]

        if not os.path.exists(script_file):
            error_msg = f'Error: Script file not found: {script_file}'
            print(error_msg)
            raise FileNotFoundError(error_msg)

        self.execute_command(f"CD.DO {script_path}")

    def flash_binary(self, flash_command: str) -> None:
        """Flash binary with comprehensive error handling and status monitoring"""
        script_file = flash_command.split()[0]

        if not os.path.exists(script_file):
            error_msg = f'Error: Flash script not found: {script_file}'
            print(error_msg)
            raise FileNotFoundError(error_msg)

        try:
            self.device.cmd(f"CD.DO {flash_command}")
            print(f'Flash: CD.DO {flash_command}')
        except Exception as e:
            print(f"Flash command failed, attempting reconnection: {e}")
            self.wait_for_connection(timeout=10)
            self.device.cmd(f"CD.DO {flash_command}")

        # Wait for system to be ready and start execution
        self._wait_for_system_ready()
        self.execute_command('Go')

    def _wait_for_system_ready(self) -> None:
        """Wait for system to reach ready state with improved logic"""
        start_time = time.time()
        ready_count = 0

        while (time.time() - start_time) < Trace32Constants.MAX_FLASH_TIMEOUT:
            if self._shutdown_event.is_set():
                return

            if self._get_system_state() == SystemState.READY:
                ready_count += 1
                if ready_count >= Trace32Constants.READY_COUNT_THRESHOLD:
                    print("System ready for execution")
                    return
            else:
                ready_count = 0  # Reset counter if not ready

            time.sleep(Trace32Constants.READY_CHECK_INTERVAL)

        print("Warning: System ready timeout reached")

    def write_symbol(self, symbol: str, value: Union[int, float]) -> None:
        """Write value to symbol with improved validation and performance"""
        if value is None:
            print(f"Warning: Attempted to write None value to symbol '{symbol}'")
            return

        if not symbol or not symbol.strip():
            raise ValueError("Symbol name cannot be empty")

        with self._reset_context() as in_reset:
            if not in_reset:
                try:
                    self.command_queue.put((CommandType.WRITE, (symbol, value)), block=False)
                except queue.Full:
                    raise Trace32Error(f"Command queue full - cannot write symbol '{symbol}'")
                except Exception as e:
                    raise Trace32Error(f"Failed to queue write command for symbol '{symbol}': {e}")

    def read_symbol(self, symbol: str) -> Any:
        """Read symbol value with improved error handling and timeout"""
        if not symbol or not symbol.strip():
            raise ValueError("Symbol name cannot be empty")

        with self._reset_context() as in_reset:
            if in_reset:
                return 0

            try:
                self.command_queue.put((CommandType.READ, symbol), block=False)
                result = self.response_queue.get(timeout=Trace32Constants.WORKER_RESPONSE_TIMEOUT)
                return result
            except queue.Full:
                raise Trace32Error(f"Command queue full - cannot read symbol '{symbol}'")
            except queue.Empty:
                raise Trace32TimeoutError(f"Timeout reading symbol '{symbol}'")
            except Exception as e:
                raise Trace32Error(f"Failed to read symbol '{symbol}': {e}")

    def read_symbol_array(self, symbol: str) -> str:
        """Read symbol with structure and array support"""
        if not symbol or not symbol.strip():
            raise ValueError("Symbol name cannot be empty")

        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            if 'library' in self._cached_refs:
                result = self._cached_refs['library'].t32_readvariablestring(symbol)
            else:
                result = self.device.library.t32_readvariablestring(symbol)
            return result[:-1] if result.endswith('\0') else result
        except Exception as e:
            error_msg = f"Failed to read symbol array '{symbol}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def reset_target(self) -> None:
        """Reset target system with improved error handling"""
        try:
            self.command_queue.put((CommandType.RESET, ''))
            self.execute_command('System.ResetTarget')
        except Exception as e:
            raise Trace32Error(f"Failed to reset target: {e}")

    def reset_and_run(self) -> None:
        """Reset target and start execution with better state monitoring"""
        try:
            self.reset_target()

            start_time = time.time()
            while (time.time() - start_time) < Trace32Constants.MAX_RESET_TIMEOUT:
                if self._shutdown_event.is_set():
                    return

                self.execute_command('Go')
                if self._get_system_state() == SystemState.RUNNING:
                    self.command_queue.put((CommandType.RESUME, ''))
                    return
                time.sleep(Trace32Constants.POLL_INTERVAL)

            print("Warning: Target may not be running after reset")

        except Exception as e:
            raise Trace32Error(f"Failed to reset and run: {e}")

    def get_breakpoint_list(self) -> List[str]:
        """Get list of active breakpoint names with improved error handling"""
        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            breakpoints = []
            bp_handler = self._cached_refs.get('breakpoint', self.device.breakpoint)
            symbol_handler = self._cached_refs.get('symbol', self.device.symbol)

            for bp in bp_handler.list():
                try:
                    symbol = symbol_handler.query_by_address(address=bp.address)
                    breakpoints.append(symbol.name)
                except Exception:
                    # If symbol lookup fails, use address
                    breakpoints.append(f"0x{bp.address:08X}")
            return breakpoints
        except Exception as e:
            error_msg = f"Failed to get breakpoint list: {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def _execute_breakpoint_operation(self, operation: str, symbol_name: str, method_name: str) -> bool:
        """Common breakpoint operation handler"""
        if not self.status:
            raise Trace32Error("Device not connected")

        try:
            symbol_handler = self._cached_refs.get('symbol', self.device.symbol)
            bp_handler = self._cached_refs.get('breakpoint', self.device.breakpoint)

            symbol = symbol_handler.query_by_name(name=symbol_name)
            method = getattr(bp_handler, method_name)
            method(address=symbol.address)

            print(f"Breakpoint {operation} at '{symbol_name}'")
            return True
        except Exception as e:
            error_msg = f"Failed to {operation} breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise Trace32Error(error_msg)

    def set_breakpoint(self, symbol_name: str) -> bool:
        """Set breakpoint at symbol location"""
        return self._execute_breakpoint_operation("set", symbol_name, "set")

    def delete_breakpoint(self, symbol_name: str) -> bool:
        """Delete breakpoint at symbol location"""
        return self._execute_breakpoint_operation("deleted", symbol_name, "delete")

    def disable_breakpoint(self, symbol_name: str) -> bool:
        """Disable breakpoint at symbol location"""
        return self._execute_breakpoint_operation("disabled", symbol_name, "disable")

    def enable_breakpoint(self, symbol_name: str) -> bool:
        """Enable breakpoint at symbol location"""
        return self._execute_breakpoint_operation("enabled", symbol_name, "enable")

    def reinitialize(self) -> None:
        """Reinitialize target system with retry logic"""
        for attempt in range(Trace32Constants.MAX_RETRIES):
            try:
                time.sleep(Trace32Constants.REINIT_DELAY)
                self.reset_and_run()
                return
            except Exception as e:
                if attempt == Trace32Constants.MAX_RETRIES - 1:
                    raise Trace32Error(f"Failed to reinitialize after {Trace32Constants.MAX_RETRIES} attempts: {e}")
                print(f"Reinitialize attempt {attempt + 1} failed: {e}")

    def wait_for_ready(self, timeout: int) -> bool:
        """Wait for command completion with timeout and better error handling"""
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            if self._shutdown_event.is_set():
                return False

            try:
                library_handler = self._cached_refs.get('library', self.device.library)
                practice_state = library_handler.t32_getpracticestate()
                if practice_state == 0:  # Command completed
                    return True
            except Exception as e:
                print(f"Error checking practice state: {e}")
                break

            time.sleep(Trace32Constants.POLL_INTERVAL)

        print(f"Warning: Command completion timeout after {timeout} seconds")
        return False

    def _get_system_state(self) -> SystemState:
        """Get current system state with improved error handling"""
        if not self.status:
            return SystemState.DOWN

        try:
            state_bytes = self.device.get_state()
            state_value = int.from_bytes(state_bytes, "big")
            return SystemState(state_value)
        except Exception as e:
            print(f"Error getting system state: {e}")
            return SystemState.DOWN

    def _rcl_worker(self) -> None:
        """Optimized worker thread with better error handling and shutdown support"""
        try:
            while not self._shutdown_event.is_set():
                try:
                    command_type, args = self.command_queue.get(
                        timeout=Trace32Constants.WORKER_QUEUE_TIMEOUT
                    )

                    # Use pre-cached handlers for better performance
                    handler = self._handlers.get(command_type)
                    if handler:
                        handler(args)
                    else:
                        print(f"Unknown command type: {command_type}")

                    self.command_queue.task_done()

                except queue.Empty:
                    continue  # Normal timeout, check shutdown flag
                except Exception as e:
                    print(f"Error in RCL worker: {e}")

        except Exception as e:
            print(f"Fatal error in RCL worker: {e}")
        finally:
            print("Trace32 RCL worker thread stopped")

    def disconnect(self) -> None:
        """Safely disconnect from Trace32 with improved cleanup"""
        try:
            print("Disconnecting from Trace32...")

            # Clear any pending commands
            while not self.command_queue.empty():
                try:
                    self.command_queue.get_nowait()
                    self.command_queue.task_done()
                except queue.Empty:
                    break

            # Clear cached references
            self._cached_refs.clear()

            if self.device:
                self.device = None

            self.status = False
            print("Trace32 disconnected successfully")

        except Exception as e:
            print(f"Error during disconnect: {e}")

    def shutdown(self) -> None:
        """Graceful shutdown of the Trace32 connection and worker thread"""
        print("Shutting down Trace32...")
        self._shutdown_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            if self._worker_thread.is_alive():
                print("Warning: Worker thread did not shut down gracefully")

        self.disconnect()
        print("Trace32 shutdown complete")

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup"""
        self.shutdown()

    def __del__(self):
        """Cleanup when object is destroyed"""
        try:
            self.shutdown()
        except:
            pass

    # Compatibility methods for backward compatibility
    def cmd(self, str_cmd: str, time_out: int = Trace32Constants.DEFAULT_COMMAND_TIMEOUT):
        """Backward compatibility method for execute_command"""
        return self.execute_command(str_cmd, time_out)

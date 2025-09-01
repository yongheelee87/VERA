import time
import queue
from threading import Thread, Event, Lock
from typing import Any, Optional, Union, Dict, Tuple, Callable
from contextlib import contextmanager
from dataclasses import dataclass
import isystem.connect as ic
from enum import IntEnum

# Type conversion mapping - moved to module level for better performance
TYPE_CONVERT = {
    'b': 1,  # ic.SType.tUnsigned
    'u': 1,  # ic.SType.tUnsigned
    'i': 2,  # ic.SType.tSigned
    'f': 3  # ic.SType.tFloat
}

# Pre-compiled constants for better performance
DEFAULT_TYPE = 1  # unsigned


class CommandType(IntEnum):
    """Command type enumeration for worker thread"""
    READ = 1
    WRITE = 2
    RESET = 3
    RESUME = 4


@dataclass(frozen=True)
class BlueBoxConstants:
    """BlueBox protocol constants - using dataclass for better memory usage"""
    WORKER_RESPONSE_TIMEOUT: float = 0.2
    REINIT_DELAY: float = 0.5
    WORKER_QUEUE_TIMEOUT: float = 1.0
    POLL_INTERVAL: float = 0.1
    MAX_RETRIES: int = 3


class BlueBoxError(Exception):
    """Base exception for BlueBox errors"""
    pass


class BlueBoxConnectionError(BlueBoxError):
    """Exception for BlueBox connection errors"""
    pass


class BlueBoxTimeoutError(BlueBoxError):
    """Exception for BlueBox timeout errors"""
    pass


class BlueBox:
    """
    Optimized BlueBox class for debugging and system control

    Key optimizations:
    - Pre-cached method references for hot paths
    - Optimized variable lookup with dict caching
    - Improved thread safety with proper synchronization
    - Reduced memory allocations in critical sections
    """

    __slots__ = (
        'device', 'exec', 'data', 'address', 'bp', 'status', 'wksFilePath',
        'command_queue', 'response_queue', 'in_reset', '_worker_thread',
        '_shutdown_event', '_reset_lock', 'vars', '_handlers', '_cached_refs'
    )

    def __init__(self, wks_path: str):
        # Core components
        self.device: Optional[Any] = None
        self.exec: Optional[Any] = None
        self.data: Optional[Any] = None
        self.address: Optional[Any] = None
        self.bp: Optional[Any] = None
        self.status = False
        self.wksFilePath = wks_path

        # Thread synchronization
        self.command_queue: queue.Queue = queue.Queue()
        self.response_queue: queue.Queue = queue.Queue()
        self.in_reset = False
        self._worker_thread: Optional[Thread] = None
        self._shutdown_event = Event()
        self._reset_lock = Lock()

        # Initialize connection and worker
        self._initialize_bluebox()

        # Cache variables after initialization
        self.vars = self._get_inout_variables()

        # Pre-cache frequently used references
        self._cached_refs = self._setup_cached_references()

        # Setup command handlers
        self._handlers = self._setup_handlers()

    def _setup_cached_references(self) -> Dict[str, Any]:
        """Pre-cache frequently used method references for performance"""
        if not self.data or not self.address:
            return {}

        return {
            'valType': ic.SType(),
            'addr_get': self.address.getVariableAddress,
            'data_read': self.data.readValue,
            'data_write': self.data.writeValue,
            'queue_put': self.response_queue.put,
            'realtime_flag': ic.IConnectDebug.fRealTime,
            'tricore_flag': ic.maPhysicalTriCore,
        }

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
            var_info = self.vars.get(symbol_name)
            if not var_info:
                self._cached_refs['queue_put'](None)
                return

            val_type = self._cached_refs['valType']
            val_type.m_byType = var_info[0]
            val_type.m_byBitSize = int(var_info[1] * 8)

            address = self._cached_refs['addr_get'](symbol_name).getAddress()
            result = self._cached_refs['data_read'](
                self._cached_refs['realtime_flag'],
                self._cached_refs['tricore_flag'],
                address,
                val_type
            ).getInt()

            self._cached_refs['queue_put'](result)

        except Exception as e:
            print(f"Error reading variable '{symbol_name}': {e}")
            self._cached_refs['queue_put'](None)

    def _handle_write(self, args: Tuple[str, Union[int, float]]) -> None:
        """Optimized write handler with cached references"""
        try:
            symbol_name, value = args
            var_info = self.vars.get(symbol_name)
            if not var_info:
                return

            val_type = self._cached_refs['valType']
            val_type.m_byType = var_info[0]
            val_type.m_byBitSize = int(var_info[1] * 8)

            address = self._cached_refs['addr_get'](symbol_name).getAddress()
            self._cached_refs['data_write'](
                self._cached_refs['realtime_flag'],
                self._cached_refs['tricore_flag'],
                address,
                ic.CValueType(val_type, value)
            )

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

    def _get_inout_variables(self) -> Dict[str, Tuple[int, float]]:
        """Optimized variable discovery with better filtering"""
        if not self.data:
            return {}

        var_vector = ic.VariableVector()
        self.data.getVariables(0, var_vector)

        # Use dict comprehension for better performance
        return {
            var.getName(): (
                TYPE_CONVERT.get(var.getType()[0].lower(), DEFAULT_TYPE),
                var.getSize()
            )
            for var in var_vector
            if var.getName().startswith(('Drv', 'Est'))
        }

    def _initialize_bluebox(self) -> None:
        """Initialize BlueBox connection and worker thread"""
        try:
            self.connect_device()
            self._start_worker_thread()
            print("BlueBox initialized successfully")
        except Exception as e:
            print(f"Failed to initialize BlueBox: {e}")
            raise

    def _start_worker_thread(self) -> None:
        """Start the worker thread with proper error handling"""
        self._worker_thread = Thread(target=self._rcl_worker, daemon=True)
        self._worker_thread.start()

    def connect_device(self) -> None:
        """Establish connection to BlueBox device with improved error handling"""
        try:
            # Initialize connection components
            self.device = ic.ConnectionMgr()
            self.device.connect(ic.CConnectionConfig())

            # Initialize controllers
            wks_ctrl = ic.CWorkspaceController(self.device)
            self.exec = ic.CExecutionController(self.device)
            self.data = ic.CDataController(self.device)
            self.address = ic.CAddressController(self.device)
            self.bp = ic.CBreakpointController(self.device)

            # Open workspace
            wks_ctrl.open(self.wksFilePath)

            # Configure CPU state
            self._configure_cpu_state()

            self.status = True
            print("BlueBox device connected successfully")

        except ConnectionRefusedError as e:
            self._handle_connection_error("Connection refused - check if BlueBox PowerView is opened")
            raise BlueBoxConnectionError(f"Connection refused: {e}")
        except Exception as e:
            self._handle_connection_error(f"Connection failed: {e}")
            raise BlueBoxConnectionError(f"Connection failed: {e}")

    def _configure_cpu_state(self) -> None:
        """Configure initial CPU state"""
        if self.exec.getCPUStatus(False).isRunning():
            self.exec.resetAndRun()
            print("Reset and run CPU (not expecting STOP state)")
        else:
            self.exec.run()
            print("CPU started in RUN state")

    def _handle_connection_error(self, message: str) -> None:
        """Handle connection errors with consistent messaging"""
        self.status = False
        print(f'Error: BlueBox CONNECTION - {message}')
        print('CHECK IF BlueBox POWERVIEW IS OPENED AND RETRY THE CONNECTION')

    def check_status(self) -> bool:
        """Check and display connection status"""
        if self.status:
            print('Success: BlueBox CONNECTION')
            return True
        else:
            print('[INFO] BlueBox is NOT CONNECTED with HOST')
            print('IF YOU WANT TO USE BlueBox, CHECK IF BlueBox POWERVIEW IS OPENED AND RETRY THE CONNECTION')
            return False

    @contextmanager
    def _reset_context(self):
        """Context manager for reset state"""
        with self._reset_lock:
            if self.in_reset:
                yield True
            else:
                yield False

    def write_symbol(self, symbol: str, value: Union[int, float]) -> None:
        """Write value to symbol with improved validation and performance"""
        if value is None or not symbol or not symbol.strip():
            return

        with self._reset_context() as in_reset:
            if not in_reset:
                try:
                    self.command_queue.put((CommandType.WRITE, (symbol, value)), block=False)
                except queue.Full:
                    raise BlueBoxError(f"Command queue full - cannot write symbol '{symbol}'")
                except Exception as e:
                    raise BlueBoxError(f"Failed to queue write command for symbol '{symbol}': {e}")

    def read_symbol(self, symbol: str) -> Any:
        """Read symbol value with improved error handling and timeout"""
        if not symbol or not symbol.strip():
            raise ValueError("Symbol name cannot be empty")

        with self._reset_context() as in_reset:
            if in_reset:
                return 0

            try:
                self.command_queue.put((CommandType.READ, symbol), block=False)
                result = self.response_queue.get(timeout=BlueBoxConstants.WORKER_RESPONSE_TIMEOUT)
                return result
            except queue.Full:
                raise BlueBoxError(f"Command queue full - cannot read symbol '{symbol}'")
            except queue.Empty:
                raise BlueBoxTimeoutError(f"Timeout reading symbol '{symbol}'")
            except Exception as e:
                raise BlueBoxError(f"Failed to read symbol '{symbol}': {e}")

    def reinitialize(self) -> None:
        """Reinitialize target system with retry logic"""
        for attempt in range(BlueBoxConstants.MAX_RETRIES):
            try:
                time.sleep(BlueBoxConstants.REINIT_DELAY)
                self.exec.resetAndRun()
                return
            except Exception as e:
                if attempt == BlueBoxConstants.MAX_RETRIES - 1:
                    raise BlueBoxError(f"Failed to reinitialize after {BlueBoxConstants.MAX_RETRIES} attempts: {e}")
                print(f"Reinitialize attempt {attempt + 1} failed: {e}")

    def wait_for_ready(self, timeout: int) -> bool:
        """Wait for command completion with timeout and better error handling"""
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            if self._shutdown_event.is_set():
                return False

            try:
                if self.exec.getCPUStatus(False).isRunning():
                    return True
            except Exception as e:
                print(f"Error checking CPU state: {e}")
                break

            time.sleep(BlueBoxConstants.POLL_INTERVAL)

        print(f"Warning: Command completion timeout after {timeout} seconds")
        return False

    def set_breakpoint(self, symbol_name: str, bp_condition: str = '') -> bool:
        """Set breakpoint at symbol location with improved error handling"""
        try:
            bp_handle = self.bp.set_BP_symbol(symbol_name)
            print(f"Breakpoint set at '{symbol_name}'")

            if bp_condition:
                self.bp.set_BP_condition(bp_handle, 1, bp_condition)
                print(f"Condition '{bp_condition}' set for breakpoint at '{symbol_name}'")

            return True
        except Exception as e:
            raise BlueBoxError(f"Failed to set breakpoint at '{symbol_name}': {e}")

    def delete_breakpoint(self, symbol_name: str) -> bool:
        """Delete breakpoint at symbol location"""
        try:
            self.bp.deleteBP(symbol_name)
            print(f"Breakpoint deleted at '{symbol_name}'")
            return True
        except Exception as e:
            raise BlueBoxError(f"Failed to delete breakpoint at '{symbol_name}': {e}")

    def _find_breakpoint_by_location(self, symbol_name: str) -> Optional[Any]:
        """Find breakpoint by symbol location - optimized lookup"""
        try:
            for bp in self.bp.get_BPs():
                if bp.location() == symbol_name:
                    return bp
            return None
        except Exception:
            return None

    def disable_breakpoint(self, symbol_name: str) -> bool:
        """Disable breakpoint at symbol location"""
        try:
            bp = self._find_breakpoint_by_location(symbol_name)
            if bp:
                self.bp.set_BP_enabled(bp, False)
                print(f"Breakpoint disabled at '{symbol_name}'")
                return True
            return False
        except Exception as e:
            raise BlueBoxError(f"Failed to disable breakpoint at '{symbol_name}': {e}")

    def enable_breakpoint(self, symbol_name: str) -> bool:
        """Enable breakpoint at symbol location"""
        try:
            bp = self._find_breakpoint_by_location(symbol_name)
            if bp:
                self.bp.set_BP_enabled(bp, True)
                print(f"Breakpoint enabled at '{symbol_name}'")
                return True
            return False
        except Exception as e:
            raise BlueBoxError(f"Failed to enable breakpoint at '{symbol_name}': {e}")

    def _rcl_worker(self) -> None:
        """Optimized worker thread with better error handling and shutdown support"""
        try:
            while not self._shutdown_event.is_set():
                try:
                    command_type, args = self.command_queue.get(
                        timeout=BlueBoxConstants.WORKER_QUEUE_TIMEOUT
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
            print("BlueBox RCL worker thread stopped")

    def shutdown(self) -> None:
        """Graceful shutdown of the BlueBox connection and worker thread"""
        print("Shutting down BlueBox...")
        self._shutdown_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
            if self._worker_thread.is_alive():
                print("Warning: Worker thread did not shut down gracefully")

        self.status = False
        print("BlueBox shutdown complete")

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit with cleanup"""
        self.shutdown()

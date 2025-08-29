import time
import queue
from threading import Thread
from typing import Any, Optional, Union
import isystem.connect as ic
from enum import IntEnum

TYPE_CONVERT = {'b': 1,  # ic.SType.tUnsigned
                'u': 1,  # ic.SType.tUnsigned
                'i': 2,  # ic.SType.tSigned
                'f': 3  # ic.SType.tFloat
                }


class CommandType(IntEnum):
    """Command type enumeration for worker thread"""
    READ = 0x01
    WRITE = 0x02
    RESET = 0x03
    RESUME = 0x04


class BlueBoxConstants:
    """BlueBox protocol constants"""
    WORKER_RESPONSE_TIMEOUT = 0.2
    REINIT_DELAY = 0.5


class BlueBoxError(Exception):
    """Custom exception for BlueBox errors"""
    pass


class BlueBoxConnectionError(BlueBoxError):
    """Custom exception for BlueBox connection errors"""
    pass


class BlueBox:
    """
    Optimized BlueBox class for debugging and system control
    """
    def __init__(self, wks_path: str):
        # Core components
        self.device: Optional[Any] = None
        self.exec: Optional[Any] = None
        self.data: Optional[Any] = None
        self.address: Optional[Any] = None
        self.bp: Optional[Any] = None
        self.status = False
        self.wksFilePath = wks_path

        # Thread-safe queues for command processing
        self.command_queue: queue.Queue = queue.Queue()
        self.response_queue: queue.Queue = queue.Queue()
        self.in_reset = False
        self._worker_thread: Optional[Thread] = None

        # Initialize if BlueBox is configured
        self._initialize_bluebox()

        self.vars = self._get_inout_variables()

        # 반복적으로 사용할 속성 및 함수 참조 캐싱
        valType = ic.SType()
        addr_get = self.address.getVariableAddress
        data_read = self.data.readValue
        data_write = self.data.writeValue
        queue_put = self.response_queue.put

        def read_handler(args):
            try:
                valType.m_byType = self.vars[args][0]
                valType.m_byBitSize = int(self.vars[args][1] * 8)
                address = addr_get(args).getAddress()
                result = data_read(ic.IConnectDebug.fRealTime,
                                   ic.maPhysicalTriCore,
                                   address,
                                   valType).getInt()
                queue_put(result)
            except Exception as e:
                print(f"Error reading variable '{args}': {e}")
                queue_put(None)

        def write_handler(args):
            try:
                symbol_name, value = args
                valType.m_byType = self.vars[args][0]
                valType.m_byBitSize = int(self.vars[args][1] * 8)
                address = addr_get(args).getAddress()
                data_write(ic.IConnectDebug.fRealTime,
                           ic.maPhysicalTriCore,
                           address,
                           ic.CValueType(valType, value))
            except Exception as e:
                print(f"Error writing variable '{args[0]}': {e}")

        self._handlers = {
            CommandType.READ: read_handler,
            CommandType.WRITE: write_handler,
            CommandType.RESET: lambda args: setattr(self, 'in_reset', True),
            CommandType.RESUME: lambda args: setattr(self, 'in_reset', False),
        }

        self._default = lambda args: print(f"Unknown command type: {args}")

    def _get_inout_variables(self):
        varVector = ic.VariableVector()
        self.data.getVariables(0, varVector)

        variables = {}

        for varData in varVector:
            VarData: ic.CVariable
            name = varData.getName()
            if name.startswith(('Drv', 'Est')):
                data_type = TYPE_CONVERT.get(varData.getType()[0].lower())
                if data_type is None:
                    data_type = 1  # unsigned
                variables[name] = (data_type, varData.getSize())
        return variables

    def _initialize_bluebox(self):
        """Initialize BlueBox connection and worker thread"""
        try:
            self.connect_device()

            # Start worker thread
            self._worker_thread = Thread(target=self._rcl_worker, daemon=True)
            self._worker_thread.start()

            print("BlueBox initialized successfully")

        except Exception as e:
            print(f"Failed to initialize BlueBox: {e}")

    def connect_device(self):
        """
        Establish connection to BlueBox device with improved error handling
        """
        try:
            self.device = ic.ConnectionMgr()
            self.device.connect(ic.CConnectionConfig())
            wksCtrl = ic.CWorkspaceController(self.device)
            self.exec = ic.CExecutionController(self.device)
            self.data = ic.CDataController(self.device)
            self.address = ic.CAddressController(self.device)
            self.bp = ic.CBreakpointController(self.device)

            wksCtrl.open(self.wksFilePath)

            isRunning = self.exec.getCPUStatus(False).isRunning()
            if isRunning is True:
                self.exec.resetAndRun()
                print("'resetandRun' the CPU without timeout (not expecting 'STOP' state)...")
            else:
                self.exec.run()
                print("CPU start 'RUN' state")

            self.status = True
            print("BlueBox device connected successfully")

        except ConnectionRefusedError as e:
            self.status = False
            print('Error: BlueBox CONNECTION')
            print('CHECK IF BlueBox POWERVIEW IS OPENED AND RETRY THE CONNECTION')
            raise BlueBoxConnectionError(f"Connection refused: {e}")
        except Exception as e:
            self.status = False
            print(f"Failed to connect to BlueBox device: {e}")
            raise BlueBoxConnectionError(f"Connection failed: {e}")

    def check_status(self) -> bool:
        """
        Check and display connection status

        Returns:
            bool: True if connected, False otherwise
        """
        if self.status:
            print('Success: BlueBox CONNECTION')
            return True
        else:
            print('[INFO] BlueBox is NOT CONNECTED with HOST')
            print('IF YOU WANT TO USE BlueBox, CHECK IF BlueBox POWERVIEW IS OPENED AND RETRY THE CONNECTION')
            return False

    def write_symbol(self, symbol: str, value: Union[int, float]):
        """
        Write value to symbol with improved validation

        Args:
            symbol: Symbol name in loaded ELF
            value: Value to write
        """
        if value is None:
            return

        if not symbol.strip():
            raise ValueError("Symbol name cannot be empty")

        try:
            if not self.in_reset:
                self.command_queue.put((CommandType.WRITE, (symbol, value)))
        except Exception as e:
            error_msg = f"Failed to queue write command for symbol '{symbol}': {e}"
            print(error_msg)
            raise BlueBoxError(error_msg)

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
                result = self.response_queue.get(timeout=BlueBoxConstants.WORKER_RESPONSE_TIMEOUT)
                return result
            else:
                return 0
        except queue.Empty:
            error_msg = f"Timeout reading symbol '{symbol}'"
            print(error_msg)
            raise BlueBoxError(error_msg)
        except Exception as e:
            error_msg = f"Failed to read symbol '{symbol}': {e}"
            print(error_msg)
            raise BlueBoxError(error_msg)

    def reinitialize(self):
        """Reinitialize target system"""
        try:
            time.sleep(BlueBoxConstants.REINIT_DELAY)
            self.exec.resetAndRun()
        except Exception as e:
            error_msg = f"Failed to reinitialize: {e}"
            print(error_msg)
            raise BlueBoxError(error_msg)

    def wait_for_ready(self, timeout: int):
        """
        Wait for command completion with timeout

        Args:
            timeout: Maximum time to wait
        """
        start_time = time.time()

        while (time.time() - start_time) < timeout:
            try:
                isRunning = self.exec.getCPUStatus(False).isRunning()
                if isRunning is True:  # cpu is ready
                    return
            except Exception as e:
                print(f"Error checking practice state: {e}")
                break

            time.sleep(0.1)  # Small delay to prevent excessive polling

        print(f"Warning: Command completion timeout after {timeout} seconds")

    def set_breakpoint(self, symbol_name: str, bp_condition: str = '') -> bool:
        """
        Set breakpoint at symbol location

        Args:
            symbol_name: Symbol name for breakpoint
            bp_condition: breakpoint condition

        Returns:
            True if successful
        """
        try:
            bp_handle = self.bp.set_BP_symbol(symbol_name)
            print(f"Breakpoint set at '{symbol_name}'")
            if bp_condition != '':
                self.bp.set_BP_condition(bp_handle, 1, bp_condition)
                print(f"Condition '{bp_condition}' is set for breakpoint at '{symbol_name}'")
            return True
        except Exception as e:
            error_msg = f"Failed to set breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise BlueBoxError(error_msg)

    def delete_breakpoint(self, symbol_name: str) -> bool:
        """
        Delete breakpoint at symbol location

        Args:
            symbol_name: Symbol name for breakpoint

        Returns:
            True if successful
        """
        try:
            self.bp.deleteBP(symbol_name)
            print(f"Breakpoint deleted at '{symbol_name}'")
            return True
        except Exception as e:
            error_msg = f"Failed to delete breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise BlueBoxError(error_msg)

    def disable_breakpoint(self, symbol_name: str) -> bool:
        """
        Disable breakpoint at symbol location

        Args:
            symbol_name: Symbol name for breakpoint

        Returns:
            True if successful
        """
        try:
            for bp in self.bp.get_BPs():
                if bp.location() == symbol_name:
                    self.bp.set_BP_enabled(bp, False)
                    print(f"Breakpoint disabled at '{symbol_name}'")
                    return True
            return False
        except Exception as e:
            error_msg = f"Failed to disable breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise BlueBoxError(error_msg)

    def enable_breakpoint(self, symbol_name: str) -> bool:
        """
        Enable breakpoint at symbol location

        Args:
            symbol_name: Symbol name for breakpoint

        Returns:
            True if successful
        """
        try:
            for bp in self.bp.get_BPs():
                if bp.location() == symbol_name:
                    self.bp.set_BP_enabled(bp, True)
                    print(f"Breakpoint enabled at '{symbol_name}'")
                    return True
            return False
        except Exception as e:
            error_msg = f"Failed to enable breakpoint at '{symbol_name}': {e}"
            print(error_msg)
            raise BlueBoxError(error_msg)

    def _rcl_worker(self):
        """
        Worker thread for handling read/write commands
        Enhanced with better error handling and logging
        """
        print("BlueBox RCL worker thread started")

        while True:
            try:
                command_type, args = self.command_queue.get(timeout=1.0)
                # .value를 사용하여 정수 비교 (더 빠름)
                self._handlers.get(command_type.value, self._default)(args)
                self.command_queue.task_done()

            except queue.Empty:
                continue  # Normal timeout, continue loop
            except Exception as e:
                print(f"Unexpected error in RCL worker: {e}")
                break

        print("BlueBox RCL worker thread stopped")

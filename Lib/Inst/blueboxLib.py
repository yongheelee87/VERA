import time
import queue
from threading import Thread
from typing import Any, Optional, Union
import isystem.connect as ic
from enum import IntEnum


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

    def _get_inout_variables(self):
        varVector = ic.VariableVector()
        self.data.getVariables(0, varVector)

        variables = {}

        for varData in varVector:
            VarData: ic.CVariable
            name = varData.getName()
            if name.startswith(('Drv', 'Est')):
                variables[name] = varData.getSize()
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

    def _rcl_worker(self):
        """
        Worker thread for handling read/write commands
        Enhanced with better error handling and logging
        """
        print("BlueBox RCL worker thread started")
        valType = ic.SType()
        valType.m_byType = ic.SType.tUnsigned
        valType.m_byBitSize = 0

        while True:
            try:
                command_type, args = self.command_queue.get(timeout=1.0)

                if command_type == CommandType.READ:
                    try:
                        valType.m_byBitSize = int(self.vars[args] * 8)
                        address = self.address.getVariableAddress(args).getAddress()
                        result = self.data.readValue(ic.IConnectDebug.fRealTime,
                                                     ic.maPhysicalTriCore,
                                                     address,
                                                     valType).getInt()
                        self.response_queue.put(result)
                    except Exception as e:
                        print(f"Error reading variable '{args}': {e}")
                        self.response_queue.put(None)

                elif command_type == CommandType.WRITE:
                    try:
                        symbol_name, value = args
                        valType.m_byBitSize = int(self.vars[symbol_name] * 8)
                        cval = ic.CValueType(valType, value)
                        address = self.address.getVariableAddress(symbol_name).getAddress()
                        self.data.writeValue(ic.IConnectDebug.fRealTime,
                                             ic.maPhysicalTriCore,
                                             address,
                                             cval)
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

        print("BlueBox RCL worker thread stopped")

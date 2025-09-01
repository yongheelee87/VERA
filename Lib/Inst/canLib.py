import os
from typing import Dict, List, Optional, Union, Any, Set
from threading import Thread, Event, Lock
from dataclasses import dataclass
from cantools import database
from can import interface, broadcastmanager, Notifier, BufferedReader, Message, CanError

# Status constants
CAN_ERR: int = 0
CAN_DEV: int = 1
CAN_IN_USE: int = 2
CAN_EXTENDED: int = 0xFF


@dataclass(frozen=True)
class CANConstants:
    """CAN protocol constants - using dataclass for better memory usage"""
    DEFAULT_TIMEOUT: float = 0.2
    DEFAULT_PERIOD: float = 0.02
    PERIODIC_SEND_TIMEOUT: float = 1.0
    CONNECTION_TEST_TIMEOUT: float = 0.2
    THREAD_JOIN_TIMEOUT: float = 2.0
    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 0.1


class CANError(Exception):
    """Base exception for CAN errors"""
    pass


class CANConnectionError(CANError):
    """Exception for CAN connection errors"""
    pass


class CANMessageError(CANError):
    """Exception for CAN message errors"""
    pass


def _get_message(msg: Message) -> Message:
    """Message callback function - kept simple for performance"""
    return msg


class CANRxThread(Thread):
    """
    Optimized CAN RX message handler thread

    Key optimizations:
    - Reduced memory allocations
    - Better error handling
    - Graceful shutdown support
    """

    __slots__ = ('rx_buffer', 'msg_dict', '_shutdown_event', '_stats')

    def __init__(self, buffer: BufferedReader) -> None:
        super().__init__(daemon=True)
        self.rx_buffer: BufferedReader = buffer
        self.msg_dict: Dict[int, Message] = {}
        self._shutdown_event = Event()
        self._stats = {'received': 0, 'errors': 0}

    def run(self) -> None:
        """Main thread loop for receiving CAN messages with improved error handling"""
        try:
            while not self._shutdown_event.is_set():
                try:
                    msg: Optional[Message] = self.rx_buffer.get_message(timeout=0.1)
                    if msg:
                        self.msg_dict[msg.arbitration_id] = msg
                        self._stats['received'] += 1
                except Exception as e:
                    self._stats['errors'] += 1
                    if self._stats['errors'] % 100 == 0:  # Log every 100 errors
                        print(f"CAN RX error count: {self._stats['errors']}")
                    # Clear on communication error
                    self.msg_dict.clear()

        except Exception as e:
            print(f"Fatal error in CAN RX thread: {e}")
        finally:
            print("CAN RX thread stopped")

    def shutdown(self) -> None:
        """Graceful shutdown of RX thread"""
        self._shutdown_event.set()

    def get_stats(self) -> Dict[str, int]:
        """Get thread statistics"""
        return self._stats.copy()


class CANDev:
    """
    Optimized CAN device handler for bus and message operations

    Key optimizations:
    - Pre-cached database queries and method references
    - Improved message handling with duplicate detection
    - Enhanced error handling and recovery mechanisms
    - Memory-efficient data structures
    """

    __slots__ = (
        'config', 'bus', 'buffer', 'notifier', 'status', 'db_path', 'db',
        'sig_val', 'rx', 'tx_data', 'tx_period', 'event_time', '_shutdown_event',
        '_tx_lock', '_cached_msgs', '_cached_signals'
    )

    def __init__(self, name: str, config_can: Dict[str, Any], git_path: str) -> None:
        self.config: Dict[str, Any] = config_can
        self.bus: Optional[interface.Bus] = None
        self.buffer: BufferedReader = BufferedReader()
        self.notifier: Optional[Notifier] = None
        self.status: int = CAN_ERR
        self._shutdown_event = Event()
        self._tx_lock = Lock()

        # Initialize database with caching
        self.db_path: str = self._get_dbc(name, git_path)
        self.db: database.Database = database.load_file(self.db_path)
        self.sig_val: Dict[str, Dict[int, Union[str, int]]] = self._get_decode_val()

        # Pre-cache frequently accessed message and signal data
        self._cached_msgs: Dict[str, Any] = {}
        self._cached_signals: Dict[str, Set[str]] = {}
        self._build_message_cache()

        # Connect and start RX thread
        self.connect_dev()
        self.rx: CANRxThread = CANRxThread(self.buffer)
        self.rx.start()

        # Initialize TX data structures with thread safety
        self.tx_data: Dict[str, Dict[str, Union[int, float, None]]] = {}
        self.tx_period: Dict[str, broadcastmanager.CyclicSendTaskABC] = {}
        self.event_time: float = 0

    def _build_message_cache(self) -> None:
        """Pre-build cache of message objects and signal trees for performance"""
        try:
            for msg in self.db.messages:
                self._cached_msgs[msg.name] = msg
                self._cached_signals[msg.name] = msg.signal_tree
        except Exception as e:
            print(f"Warning: Failed to build message cache: {e}")

    def connect_dev(self) -> None:
        """Establish CAN bus connection with improved error handling"""
        if not self.bus:
            self._initial_connection()
        else:
            self._test_existing_connection()

    def _initial_connection(self) -> None:
        """Initial CAN bus connection"""
        try:
            self.bus = interface.Bus(
                bustype=self.config['bus_type'],
                channel=self.config['channel'],
                bitrate=int(self.config['bit_rate']),
                app_name=self.config['app_type'],
                data_bitrate=int(self.config['data_rate']),
                fd=True
            )
            self.notifier = Notifier(self.bus, [_get_message, self.buffer])
            self.status = CAN_DEV
            print(f"CAN device connected successfully on channel {self.config['channel']}")
        except CanError as e:
            print(f"Error: CAN connection failed - {e}")
            self.status = CAN_ERR

    def _test_existing_connection(self) -> None:
        """Test existing CAN connection"""
        try:
            # Test connection with dummy message
            test_msg = Message(
                arbitration_id=0,
                data=[0x00],
                is_extended_id=False,
                is_fd=True
            )
            self.bus.send(test_msg, timeout=CANConstants.CONNECTION_TEST_TIMEOUT)
            self.status = CAN_IN_USE
        except (AttributeError, CanError) as e:
            print(f"Error: CAN test failed - {e}")
            self.status = CAN_ERR
            self.bus = None

    def clear_msg(self) -> None:
        """Clear all received messages"""
        self.rx.msg_dict.clear()

    def read_msg_by_id(self, can_id: int, decode_on: bool = True) -> Dict[str, Union[int, float, str]]:
        """Read message by CAN ID with improved error handling"""
        try:
            msg = self.rx.msg_dict.get(can_id)
            if msg:
                return self.db.decode_message(can_id, msg.data, decode_choices=decode_on)
            return {}
        except Exception as e:
            print(f"Error decoding message ID {can_id}: {e}")
            return {}

    def read_msg_by_frame(self, frame_name: str, decode_on: bool = True) -> Dict[str, Union[int, float, str]]:
        """Read message by frame name with cached message lookup"""
        try:
            # Use cached message if available
            if frame_name in self._cached_msgs:
                can_id = self._cached_msgs[frame_name].frame_id
            else:
                can_id = self.db.get_message_by_name(frame_name).frame_id
            return self.read_msg_by_id(can_id, decode_on)
        except Exception as e:
            print(f"Error reading frame '{frame_name}': {e}")
            return {}

    def read_event_msg(self, frame_name: str, decode_on: bool = True) -> Dict[str, Union[int, float, str]]:
        """Read message only if timestamp changed (event-driven) with optimization"""
        try:
            # Use cached message if available
            if frame_name in self._cached_msgs:
                can_id = self._cached_msgs[frame_name].frame_id
            else:
                can_id = self.db.get_message_by_name(frame_name).frame_id

            msg = self.rx.msg_dict.get(can_id)
            if msg and self.event_time != msg.timestamp:
                self.event_time = msg.timestamp
                return self.db.decode_message(can_id, msg.data, decode_choices=decode_on)
            return {}
        except Exception as e:
            print(f"Error reading event message '{frame_name}': {e}")
            return {}

    def _validate_signal_value(self, frame_name: str, sig_name: str, value: Union[int, float]) -> bool:
        """Validate signal value against database constraints"""
        try:
            if frame_name in self._cached_msgs:
                msg_tx = self._cached_msgs[frame_name]
                if sig_name in msg_tx.signals_by_name:
                    signal = msg_tx.signals_by_name[sig_name]
                    if hasattr(signal, 'minimum') and hasattr(signal, 'maximum'):
                        return signal.minimum <= value <= signal.maximum
            return True  # No validation data available, assume valid
        except Exception:
            return True  # Default to valid if validation fails

    def send_signal(self, frame_name: str, sig_name: str, value: Union[int, float],
                    timeout: float = CANConstants.DEFAULT_TIMEOUT, is_extended: bool = False) -> None:
        """Send single signal message with validation and caching"""
        if value is None:
            return

        if not self._validate_signal_value(frame_name, sig_name, value):
            print(f"Warning: Signal value {value} may be out of range for {sig_name}")

        try:
            # Use cached message if available
            if frame_name in self._cached_msgs:
                msg_tx = self._cached_msgs[frame_name]
                signal_tree = self._cached_signals[frame_name]
            else:
                msg_tx = self.db.get_message_by_name(frame_name)
                signal_tree = msg_tx.signal_tree

            # Create signal dictionary with default zeros (optimized)
            msg_raw_data: Dict[str, Union[int, float]] = {signal: 0 for signal in signal_tree}
            msg_raw_data[sig_name] = value

            can_message = Message(
                arbitration_id=msg_tx.frame_id,
                data=msg_tx.encode(msg_raw_data),
                is_extended_id=is_extended,
                is_fd=True
            )
            self.bus.send(can_message, timeout=timeout)

        except Exception as e:
            raise CANMessageError(f"Failed to send CAN message '{frame_name}': {e}")

    def send_periodic_signal(self, frame_name: str, sig_name: str, value: Union[int, float],
                             period: float = CANConstants.DEFAULT_PERIOD, is_extended: bool = False) -> None:
        """Send periodic single signal message with improved duplicate detection"""
        if value is None:
            return

        if not self._validate_signal_value(frame_name, sig_name, value):
            print(f"Warning: Signal value {value} may be out of range for {sig_name}")

        with self._tx_lock:
            try:
                # Use cached message if available
                if frame_name in self._cached_msgs:
                    msg_tx = self._cached_msgs[frame_name]
                    signal_tree = self._cached_signals[frame_name]
                else:
                    msg_tx = self.db.get_message_by_name(frame_name)
                    signal_tree = msg_tx.signal_tree

                if frame_name in self.tx_data:
                    # Check if value actually changed
                    if value == self.tx_data[frame_name].get(sig_name):
                        return  # No change, exit early
                    else:
                        self.tx_data[frame_name][sig_name] = value
                        self._stop_overlap_msg(frame_name)
                else:
                    # Create new signal dictionary
                    msg_raw_data: Dict[str, Union[int, float]] = {signal: 0 for signal in signal_tree}
                    msg_raw_data[sig_name] = value
                    self.tx_data[frame_name] = msg_raw_data

                can_message = Message(
                    arbitration_id=msg_tx.frame_id,
                    data=msg_tx.encode(self.tx_data[frame_name]),
                    is_extended_id=is_extended,
                    is_fd=True
                )
                self.tx_period[frame_name] = self.bus.send_periodic(can_message, period)

            except Exception as e:
                raise CANMessageError(f"Failed to send periodic CAN message '{frame_name}': {e}")

    def send_frame_msg(self, frame_name: str, sig_names: List[str], values: List[Union[int, float, None]],
                       timeout: float = CANConstants.DEFAULT_TIMEOUT, is_extended: bool = False) -> None:
        """Send multiple signals in one frame with improved validation"""
        # Early exit if all values are None
        if all(val is None for val in values):
            return

        # Filter out None values efficiently
        signal_data: Dict[str, Union[int, float]] = {
            sig: val for sig, val in zip(sig_names, values) if val is not None
        }

        if not signal_data:
            return

        try:
            # Use cached message if available
            if frame_name in self._cached_msgs:
                msg_tx = self._cached_msgs[frame_name]
                signal_tree = self._cached_signals[frame_name]
            else:
                msg_tx = self.db.get_message_by_name(frame_name)
                signal_tree = msg_tx.signal_tree

            # Create signal dictionary with default zeros
            msg_raw_data: Dict[str, Union[int, float]] = {signal: 0 for signal in signal_tree}
            msg_raw_data.update(signal_data)

            can_message = Message(
                arbitration_id=msg_tx.frame_id,
                data=msg_tx.encode(msg_raw_data),
                is_extended_id=is_extended,
                is_fd=True
            )
            self.bus.send(can_message, timeout=timeout)

        except Exception as e:
            raise CANMessageError(f"Failed to send CAN frame message '{frame_name}': {e}")

    def send_periodic_frame_msg(self, frame_name: str, sig_names: List[str],
                                values: List[Union[int, float, None]],
                                period: float = CANConstants.DEFAULT_PERIOD, is_extended: bool = False) -> None:
        """Send periodic multiple signals message with optimized change detection"""
        # Early exit if all values are None
        if all(val is None for val in values):
            return

        # Filter out None values efficiently
        signal_data: Dict[str, Union[int, float]] = {
            sig: val for sig, val in zip(sig_names, values) if val is not None
        }

        if not signal_data:
            return

        with self._tx_lock:
            try:
                # Use cached message if available
                if frame_name in self._cached_msgs:
                    msg_tx = self._cached_msgs[frame_name]
                    signal_tree = self._cached_signals[frame_name]
                else:
                    msg_tx = self.db.get_message_by_name(frame_name)
                    signal_tree = msg_tx.signal_tree

                if frame_name in self.tx_data:
                    # Optimized change detection using set operations
                    current_items = set(self.tx_data[frame_name].items())
                    new_items = set(signal_data.items())
                    if new_items.issubset(current_items):
                        return  # No changes needed
                    else:
                        self.tx_data[frame_name].update(signal_data)
                        self._stop_overlap_msg(frame_name)
                else:
                    # Create new signal dictionary
                    msg_raw_data: Dict[str, Union[int, float]] = {signal: 0 for signal in signal_tree}
                    msg_raw_data.update(signal_data)
                    self.tx_data[frame_name] = msg_raw_data

                can_message = Message(
                    arbitration_id=msg_tx.frame_id,
                    data=msg_tx.encode(self.tx_data[frame_name]),
                    is_extended_id=is_extended,
                    is_fd=True
                )
                self.tx_period[frame_name] = self.bus.send_periodic(can_message, period)

            except Exception as e:
                raise CANMessageError(f"Failed to send periodic CAN frame message '{frame_name}': {e}")

    def send_raw_msg(self, frame_id: int, msg_data: List[int],
                     timeout: float = CANConstants.DEFAULT_TIMEOUT, is_extended: bool = False) -> None:
        """Send raw CAN message with improved validation"""
        if not msg_data or len(msg_data) > 64:  # CAN FD max data length
            raise ValueError("Invalid message data length")

        try:
            can_message = Message(
                arbitration_id=frame_id,
                data=msg_data,
                is_extended_id=is_extended,
                is_fd=True
            )
            self.bus.send(can_message, timeout=timeout)
        except Exception as e:
            raise CANMessageError(f"Failed to send raw CAN message {frame_id}: {e}")

    def disable_periodic_msgs(self) -> None:
        """Stop all periodic messages with improved error handling"""
        with self._tx_lock:
            try:
                if self.bus:
                    self.bus.stop_all_periodic_tasks()
                self.tx_period.clear()
                self.tx_data.clear()
            except CanError as e:
                raise CANError(f"Failed to stop periodic messages: {e}")

    def get_msg_name(self, msg_id: int) -> str:
        """Get message name by ID with error handling"""
        try:
            return self.db.get_message_by_frame_id(msg_id).name
        except Exception as e:
            raise CANError(f"Message ID {msg_id} not found: {e}")

    def get_msg_id(self, frame_name: str) -> int:
        """Get message ID by name with cached lookup"""
        try:
            if frame_name in self._cached_msgs:
                return self._cached_msgs[frame_name].frame_id
            else:
                return self.db.get_message_by_name(frame_name).frame_id
        except Exception as e:
            raise CANError(f"Message '{frame_name}' not found: {e}")

    def get_active_messages(self) -> List[str]:
        """Get list of currently active periodic messages"""
        with self._tx_lock:
            return list(self.tx_data.keys())

    def get_rx_stats(self) -> Dict[str, int]:
        """Get RX thread statistics"""
        return self.rx.get_stats()

    def _stop_overlap_msg(self, frame_name: str) -> None:
        """Stop existing periodic message for the same frame"""
        try:
            if frame_name in self.tx_period:
                self.tx_period[frame_name].stop()
        except Exception as e:
            print(f"Warning: Failed to stop overlapping message '{frame_name}': {e}")

    def _get_dbc(self, name: str, git_path: str) -> str:
        """Get DBC file path with improved error handling"""
        db_path: str = self.config['DBC_file_path']

        if db_path == 'git':
            ref_path = os.path.join(git_path, 'References', 'DB')
            try:
                if os.path.exists(ref_path):
                    for file in os.listdir(ref_path):
                        if '.dbc' in file and name in file:
                            return os.path.join(ref_path, file)
                print(f"Warning: DBC file for '{name}' not found in git path")
            except OSError as e:
                print(f"Error accessing DBC directory: {e}")

        if not os.path.exists(db_path):
            raise FileNotFoundError(f"DBC file not found: {db_path}")

        return db_path

    def _get_decode_val(self) -> Dict[str, Dict[int, Union[str, int]]]:
        """Parse decode values from DBC file with improved parsing"""
        decode_dict: Dict[str, Dict[int, Union[str, int]]] = {}

        try:
            with open(self.db_path, "r", encoding="utf8", errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    if line.startswith('VAL_'):
                        try:
                            val_info: List[str] = [i.strip() for i in line[5:].split('"')]
                            if len(val_info) >= 3:
                                val_head: List[str] = val_info[0::2][0].split() + val_info[0::2][1:]
                                if len(val_head) >= 2:
                                    signal_name: str = val_head[1]
                                    values: List[str] = val_head[2:]
                                    decode_values: List[str] = val_info[1::2]

                                    decode_dict[signal_name] = {}
                                    for val, decode in zip(values, decode_values):
                                        try:
                                            int_val = int(val)
                                            decode_dict[signal_name][int_val] = decode if '~' not in decode else int_val
                                        except ValueError:
                                            continue  # Skip invalid values
                        except (ValueError, IndexError) as e:
                            print(f"Warning: Error parsing DBC line {line_num}: {e}")
                            continue
        except (OSError, UnicodeDecodeError) as e:
            print(f"Warning: Error reading DBC file: {e}")

        return decode_dict

    def shutdown(self) -> None:
        """Graceful shutdown of CAN device"""
        print("Shutting down CAN device...")

        # Signal shutdown
        self._shutdown_event.set()

        # Stop all periodic messages
        try:
            self.disable_periodic_msgs()
        except Exception as e:
            print(f"Error stopping periodic messages: {e}")

        # Stop RX thread
        if hasattr(self, 'rx') and self.rx.is_alive():
            self.rx.shutdown()
            self.rx.join(timeout=CANConstants.THREAD_JOIN_TIMEOUT)
            if self.rx.is_alive():
                print("Warning: RX thread did not shut down gracefully")

        # Close bus connection
        try:
            if self.notifier:
                self.notifier.stop()
            if self.bus:
                self.bus.shutdown()
        except Exception as e:
            print(f"Error closing CAN bus: {e}")

        self.status = CAN_ERR
        print("CAN device shutdown complete")

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


class CANBus:
    """
    Optimized CAN bus manager for multiple devices

    Key optimizations:
    - Improved device management and monitoring
    - Enhanced error handling and recovery
    - Better resource management
    """

    __slots__ = ('config', 'devs', 'lst_dev', '_shutdown_event')

    def __init__(self, config: Dict[str, Any], git_path: str) -> None:
        self.config: Dict[str, Any] = config
        self.devs: Dict[str, CANDev] = {}
        self.lst_dev: List[str] = self._find_can()
        self._shutdown_event = Event()

        # Initialize all CAN devices with error handling
        self._initialize_devices(git_path)

    def _initialize_devices(self, git_path: str) -> None:
        """Initialize all CAN devices with improved error handling"""
        failed_devices = []

        for dev in self.lst_dev:
            try:
                self.devs[dev] = CANDev(name=dev, config_can=self.config[dev], git_path=git_path)
                print(f"CAN device '{dev}' initialized successfully")
            except Exception as e:
                print(f"Failed to initialize CAN device '{dev}': {e}")
                failed_devices.append(dev)

        if failed_devices:
            print(f"Warning: Failed to initialize devices: {failed_devices}")

    def check_status(self) -> List[str]:
        """Check connection status of all CAN devices with detailed reporting"""
        failed_devs: List[str] = []
        connected_devs: List[str] = []
        in_use_devs: List[str] = []

        for dev in self.lst_dev:
            if dev not in self.devs:
                failed_devs.append(dev)
                continue

            device_status = self.devs[dev].status
            if device_status == CAN_ERR:
                failed_devs.append(dev)
            elif device_status == CAN_DEV:
                connected_devs.append(dev)
            elif device_status == CAN_IN_USE:
                in_use_devs.append(dev)

        # Report status
        if connected_devs:
            print(f"CAN STATUS: Connected devices: {connected_devs}")
        if in_use_devs:
            print(f"CAN STATUS: In-use devices: {in_use_devs}")
        if failed_devs:
            print(f'CAN STATUS: Failed devices: {failed_devs}')
            print('Check if CAN devices are available in hardware manager')

        return failed_devs

    def stop_all_period_msg(self) -> None:
        """Stop all periodic messages across all devices"""
        for dev_name, dev in self.devs.items():
            try:
                dev.disable_periodic_msgs()
                dev.clear_msg()
            except Exception as e:
                print(f"Error stopping periodic messages for device '{dev_name}': {e}")

    def get_all_period_msg(self) -> Dict[str, Dict[str, Union[int, float, None]]]:
        """Get all active periodic messages from all devices"""
        all_msgs: Dict[str, Dict[str, Union[int, float, None]]] = {}
        for dev_name, dev in self.devs.items():
            try:
                all_msgs.update(dev.tx_data)
            except Exception as e:
                print(f"Error getting periodic messages from device '{dev_name}': {e}")
        return all_msgs

    def get_all_rx_stats(self) -> Dict[str, Dict[str, int]]:
        """Get RX statistics from all devices"""
        all_stats: Dict[str, Dict[str, int]] = {}
        for dev_name, dev in self.devs.items():
            try:
                all_stats[dev_name] = dev.get_rx_stats()
            except Exception as e:
                print(f"Error getting RX stats from device '{dev_name}': {e}")
                all_stats[dev_name] = {'received': 0, 'errors': -1}
        return all_stats

    def reconnect_failed_devices(self) -> List[str]:
        """Attempt to reconnect failed devices"""
        failed_devs = self.check_status()
        reconnected = []

        for dev_name in failed_devs:
            if dev_name in self.devs:
                try:
                    self.devs[dev_name].connect_dev()
                    if self.devs[dev_name].status != CAN_ERR:
                        reconnected.append(dev_name)
                        print(f"Successfully reconnected CAN device '{dev_name}'")
                except Exception as e:
                    print(f"Failed to reconnect CAN device '{dev_name}': {e}")

        return reconnected

    def get_device(self, device_name: str) -> Optional[CANDev]:
        """Get specific CAN device by name"""
        return self.devs.get(device_name)

    def _find_can(self) -> List[str]:
        """Find all CAN device configurations"""
        return list(self.config.keys())

    def shutdown(self) -> None:
        """Graceful shutdown of all CAN devices"""
        print("Shutting down CAN bus...")
        self._shutdown_event.set()

        for dev_name, dev in self.devs.items():
            try:
                dev.shutdown()
                print(f"CAN device '{dev_name}' shut down")
            except Exception as e:
                print(f"Error shutting down CAN device '{dev_name}': {e}")

        self.devs.clear()
        print("CAN bus shutdown complete")

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


# Convenience functions for backward compatibility
def create_can_bus(config: Dict[str, Any], git_path: str) -> CANBus:
    """Create and return optimized CAN bus instance"""
    return CANBus(config, git_path)


def create_can_device(name: str, config_can: Dict[str, Any], git_path: str) -> CANDev:
    """Create and return optimized CAN device instance"""
    return CANDev(name, config_can, git_path)

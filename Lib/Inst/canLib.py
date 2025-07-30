import os
from typing import Dict, List, Optional, Union, Any
from cantools import database
from can import interface, broadcastmanager, Notifier, BufferedReader, Message, CanError
from threading import Thread
from Lib.Common import Configure

# Status constants
CAN_ERR: int = 0
CAN_DEV: int = 1
CAN_IN_USE: int = 2

CAN_EXTENDED: int = 0xFF


def _get_message(msg: Message) -> Message:
    return msg


class CANDev:
    """Optimized CAN device handler for bus and message operations"""

    __slots__ = ['config', 'bus', 'buffer', 'notifier', 'status', 'db_path',
                 'db', 'sig_val', 'rx', 'tx_data', 'tx_period', 'event_time']

    def __init__(self, name: str, config_can: Dict[str, Any]) -> None:
        self.config: Dict[str, Any] = config_can
        self.bus: Optional[interface.Bus] = None
        self.buffer: BufferedReader = BufferedReader()
        self.notifier: Optional[Notifier] = None
        self.status: int = CAN_ERR

        # Initialize database
        self.db_path: str = self._get_dbc(name)
        self.db: database.Database = database.load_file(self.db_path)
        self.sig_val: Dict[str, Dict[int, Union[str, int]]] = self._get_decode_val()

        # Connect and start RX thread
        self.connect_dev()
        self.rx: CANRxThread = CANRxThread(self.buffer)
        self.rx.start()

        # Initialize TX data structures
        self.tx_data: Dict[str, Dict[str, Union[int, float, None]]] = {}
        self.tx_period: Dict[str, broadcastmanager.CyclicSendTaskABC] = {}  # CAN tx period data 선언; 메모리 보관
        self.event_time: float = 0

    def connect_dev(self) -> None:
        """Establish CAN bus connection"""
        if not self.bus:
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
            except CanError as e:
                print(f"Error: CAN connection failed - {e}")
                self.status = CAN_ERR
        else:
            try:
                # Test connection with dummy message
                test_msg = Message(arbitration_id=0, data=[0x00], is_extended_id=False, is_fd=True)
                self.bus.send(test_msg, timeout=0.2)
                self.status = CAN_IN_USE
            except (AttributeError, CanError) as e:
                print(f"Error: CAN test failed - {e}")
                self.status = CAN_ERR
                self.bus = None

    def clear_msg(self) -> None:
        """Clear all received messages"""
        self.rx.msg_dict.clear()

    def read_msg_by_id(self, can_id: int, decode_on: bool = True) -> Dict[str, Union[int, float, str]]:
        """Read message by CAN ID"""
        msg = self.rx.msg_dict.get(can_id)
        if msg:
            return self.db.decode_message(can_id, msg.data, decode_choices=decode_on)
        return {}

    def read_msg_by_frame(self, frame_name: str, decode_on: bool = True) -> Dict[str, Union[int, float, str]]:
        """Read message by frame name"""
        can_id = self.db.get_message_by_name(frame_name).frame_id
        return self.read_msg_by_id(can_id, decode_on)

    def read_event_msg(self, frame_name: str, decode_on: bool = True) -> Dict[str, Union[int, float, str]]:
        """Read message only if timestamp changed (event-driven)"""
        can_id = self.db.get_message_by_name(frame_name).frame_id
        msg = self.rx.msg_dict.get(can_id)

        if msg and self.event_time != msg.timestamp:
            self.event_time = msg.timestamp
            return self.db.decode_message(can_id, msg.data, decode_choices=decode_on)
        return {}

    def send_signal(self, frame_name: str, sig_name: str, value: Union[int, float],
                    timeout: float = 0.2, is_extended: bool = False) -> None:
        """Send single signal message"""
        if value is None:
            return

        msg_tx = self.db.get_message_by_name(frame_name)  # 해당 CAN message frame 정보 가져오기
        # Create signal dictionary with default zeros
        msg_raw_data: Dict[str, Union[int, float]] = {signal: 0 for signal in msg_tx.signal_tree}
        msg_raw_data[sig_name] = value  # 해당 signal 값 업데이트

        try:
            can_message = Message(
                arbitration_id=msg_tx.frame_id,
                data=msg_tx.encode(msg_raw_data),
                is_extended_id=is_extended,
                is_fd=True
            )
            self.bus.send(can_message, timeout=timeout)

        except Exception as e:
            print(f"Error: Failed to send CAN message '{frame_name}' - {e}")

    def send_periodic_signal(self, frame_name: str, sig_name: str, value: Union[int, float],
                             period: float = 0.02, is_extended: bool = False) -> None:
        """Send periodic single signal message"""
        if value is None:
            return

        msg_tx = self.db.get_message_by_name(frame_name)  # 해당 CAN message frame 정보 가져오기

        if frame_name in self.tx_data:
            if value == self.tx_data[frame_name].get(sig_name):  # 같은 시그널 값 요청시 동작 불필요
                return
            else:
                self.tx_data[frame_name].update({sig_name: value})  # 다른 시그널 값 업데이트
                self._stop_overlap_msg(frame_name)
        else:
            # Create signal dictionary with default zeros
            msg_raw_data: Dict[str, Union[int, float]] = {signal: 0 for signal in msg_tx.signal_tree}
            msg_raw_data.update(self.tx_data[frame_name])  # 해당 frame signal 값 업데이트
            self.tx_data[frame_name] = msg_raw_data  # Frame 및 signal 생성

        try:
            can_message = Message(
                arbitration_id=msg_tx.frame_id,
                data=msg_tx.encode(self.tx_data[frame_name]),
                is_extended_id=is_extended,
                is_fd=True
            )
            self.tx_period[frame_name] = self.bus.send_periodic(can_message, period)
        except Exception as e:
            print(f"Error: Failed to send CAN message '{frame_name}' - {e}")
            
    def send_frame_msg(self, frame_name: str, sig_names: List[str], values: List[Union[int, float, None]],
                       timeout: float = 0.02, is_extended: bool = False) -> None:
        """Send multiple signals in one frame"""
        if values == ([None] * len(values)):
            return

        signal_data: Dict[str, Union[int, float]] = {
            sig: val for sig, val in zip(sig_names, values) if val is not None
        }

        msg_tx = self.db.get_message_by_name(frame_name)  # 해당 CAN message frame 정보 가져오기
        # Create signal dictionary with default zeros
        msg_raw_data: Dict[str, Union[int, float]] = {signal: 0 for signal in msg_tx.signal_tree}
        msg_raw_data.update(signal_data)  # 해당 frame signal 값 업데이트

        try:
            can_message = Message(
                arbitration_id=msg_tx.frame_id,
                data=msg_tx.encode(msg_raw_data),
                is_extended_id=is_extended,
                is_fd=True
            )
            self.bus.send(can_message, timeout=timeout)

        except Exception as e:
            print(f"Error: Failed to send CAN message '{frame_name}' - {e}")

    def send_periodic_frame_msg(self, frame_name: str, sig_names: List[str],
                                values: List[Union[int, float, None]],
                                period: float = 0.02, is_extended: bool = False) -> None:
        """Send periodic multiple signals message"""
        if values == ([None] * len(values)):
            return

        signal_data: Dict[str, Union[int, float]] = {
            sig: val for sig, val in zip(sig_names, values) if val is not None
        }

        msg_tx = self.db.get_message_by_name(frame_name)  # 해당 CAN message frame 정보 가져오기
        if frame_name in self.tx_data:
            if all(item in self.tx_data[frame_name].items() for item in signal_data.items()): # 모든 key-value 쌍이 종속되어 있을ㄸ
                return
            else:
                self.tx_data[frame_name].update(signal_data)  # 다른 시그널 값 업데이트
                self._stop_overlap_msg(frame_name)
        else:
            # Create signal dictionary with default zeros
            msg_raw_data: Dict[str, Union[int, float]] = {signal: 0 for signal in msg_tx.signal_tree}
            msg_raw_data.update(signal_data)  # 해당 frame signal 값 업데이트
            self.tx_data[frame_name] = msg_raw_data  # Frame 및 signal 생성

        try:
            can_message = Message(
                arbitration_id=msg_tx.frame_id,
                data=msg_tx.encode(self.tx_data[frame_name]),
                is_extended_id=is_extended,
                is_fd=True
            )
            self.tx_period[frame_name] = self.bus.send_periodic(can_message, period)
        except Exception as e:
            print(f"Error: Failed to send CAN message '{frame_name}' - {e}")

    def send_raw_msg(self, frame_id: int, msg_data: List[int],
                     timeout: float = 0.02, is_extended: bool = False) -> None:
        """Send raw CAN message"""
        try:
            can_message = Message(
                arbitration_id=frame_id,
                data=msg_data,
                is_extended_id=is_extended,
                is_fd=True
            )
            self.bus.send(can_message, timeout=timeout)
        except Exception as e:
            print(f"Error: Failed to send raw CAN message {frame_id} - {e}")

    def disable_periodic_msgs(self) -> None:
        """Stop all periodic messages"""
        try:
            if self.bus:
                self.bus.stop_all_periodic_tasks()
            self.tx_period.clear()
            self.tx_data.clear()
        except CanError as e:
            print(f"Error: Failed to stop periodic messages - {e}")

    def get_msg_name(self, msg_id: int) -> str:
        """Get message name by ID"""
        return self.db.get_message_by_frame_id(msg_id).name

    def get_msg_id(self, frame_name: str) -> int:
        """Get message ID by name"""
        return self.db.get_message_by_name(frame_name).frame_id

    def _stop_overlap_msg(self, frame_name: str) -> None:
        """Stop existing periodic message for the same frame"""
        self.tx_period[frame_name].stop()

    def _get_dbc(self, name: str) -> str:
        """Get DBC file path"""
        db_path: str = self.config['DBC_file_path']
        if db_path == 'git':
            ref_path = os.path.join(Configure.set['system']['git_path'], 'References', 'DB')
            try:
                for file in os.listdir(ref_path):
                    if '.dbc' in file and name in file:
                        return os.path.join(ref_path, file)
            except OSError:
                pass
        return db_path

    def _get_decode_val(self) -> Dict[str, Dict[int, Union[str, int]]]:
        """Parse decode values from DBC file"""
        decode_dict: Dict[str, Dict[int, Union[str, int]]] = {}
        try:
            with open(self.db_path, "r", encoding="utf8", errors='ignore') as f:
                for line in f:
                    if line.startswith('VAL_'):
                        val_info: List[str] = [i.strip() for i in line[5:].split('"')]
                        if len(val_info) >= 3:
                            val_head: List[str] = val_info[0::2][0].split() + val_info[0::2][1:]
                            if len(val_head) >= 2:
                                signal_name: str = val_head[1]
                                values: List[str] = val_head[2:]
                                decode_values: List[str] = val_info[1::2]
                                decode_dict[signal_name] = {
                                    int(val): decode if '~' not in decode else int(val)
                                    for val, decode in zip(values, decode_values)
                                }
        except (OSError, ValueError, IndexError):
            pass
        return decode_dict


# CAN RX Msg Thread로 받기
class CANRxThread(Thread):
    """Optimized CAN RX message handler thread"""

    __slots__ = ['rx_buffer', 'msg_dict']

    def __init__(self, buffer: BufferedReader) -> None:
        super().__init__()
        self.rx_buffer: BufferedReader = buffer
        self.msg_dict: Dict[int, Message] = {}

    def run(self) -> None:
        """Main thread loop for receiving CAN messages"""
        while True:
            msg: Optional[Message] = self.rx_buffer.get_message()
            if msg:
                self.msg_dict[msg.arbitration_id] = msg
            else:
                # Clear on communication error
                self.msg_dict.clear()


class CANBus:
    """Optimized CAN bus manager for multiple devices"""

    __slots__ = ['config', 'devs', 'lst_dev']

    def __init__(self, config_sys: Dict[str, Any]) -> None:
        self.config: Dict[str, Any] = config_sys
        self.devs: Dict[str, CANDev] = {}
        self.lst_dev: List[str] = self._find_can()

        # Initialize all CAN devices
        for dev in self.lst_dev:
            self.devs[dev] = CANDev(name=dev, config_can=self.config[dev])

    def check_status(self) -> List[str]:
        """Check connection status of all CAN devices"""
        failed_devs: List[str] = []
        connected_devs: List[str] = []

        for dev in self.lst_dev:
            if self.devs[dev].status == CAN_ERR:
                failed_devs.append(dev)
            else:
                connected_devs.append(dev)

        if connected_devs:
            print(f"CAN STATUS: Connected devices: {connected_devs}")

        if failed_devs:
            print(f'CAN STATUS: Failed to connect: {failed_devs}')
            print('Check if CAN devices are available in hardware manager')

        return failed_devs

    def stop_all_period_msg(self) -> None:
        """Stop all periodic messages across all devices"""
        for dev in self.lst_dev:
            self.devs[dev].disable_periodic_msgs()
            self.devs[dev].clear_msg()

    def get_all_period_msg(self) -> Dict[str, Dict[str, Union[int, float]]]:
        """Get all active periodic messages from all devices"""
        all_msgs: Dict[str, Dict[str, Union[int, float, None]]] = {}
        for dev in self.lst_dev:
            all_msgs.update(self.devs[dev].tx_data)
        return all_msgs

    def _find_can(self) -> List[str]:
        """Find all CAN device configurations"""
        return [
            dev for dev in list(self.config.keys())[1:]
            if self.config[dev].get('type', '').lower() == 'can'
        ]

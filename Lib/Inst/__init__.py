# ///////////////////////////////////////////////////////////////
#
# BY: YONGHEE LEE
# PROJECT MADE WITH: measurement with script command
# V: 1.0.0
#
# This project can be used freely for all uses, as long as they maintain the
# respective credits only in the Python scripts, any information in the visual
# interface (GUI) can be modified without any implication.
#
# ///////////////////////////////////////////////////////////////
import numpy as np
import pandas as pd
from Lib.Common import Configure

# basic library
# from . xcpLib import *
# from . telnetLib import *
# from . serialLib import *


# 같은 'type'에 따라 항목을 묶기
def group_by_type(data):
    grouped_data = {}

    for key, value in data.items():
        if 'type' in value:
            type_key = value['type']
            if type_key not in grouped_data:
                grouped_data[type_key] = {}
            grouped_data[type_key][key] = value

    return grouped_data


def get_inst_status() -> pd.DataFrame:
    lst_inst_data = []
    for device_name, device_settings in grouped_device.items():
        if device_name == 'T32' or device_name == 'BlueBox':
            lst_inst_data.append([device_name, 'Not Connected' if debug.status is False else 'Connected'])

        elif device_name == 'can':
            for name in device_settings.keys():
                lst_inst_data.append([name, 'Not Connected' if canBus.devs[name].status is False else 'Connected'])

    return pd.DataFrame(np.array(lst_inst_data, dtype=object), columns=['Name', 'Connect'])


grouped_device = group_by_type(Configure.set)
for device_type, device_config in grouped_device.items():
    if device_type == 'T32':
        from .trace32Lib import Trace32
        debug = Trace32(config=grouped_device['T32']['DEBUGGER'])  # TRACE32 연결; 전역 변수로 사용

    elif device_type == 'BlueBox':
        from .blueboxLib import BlueBox
        debug = BlueBox(wks_path=grouped_device['BlueBox']['DEBUGGER']['flash_file'])  # BlueBox 연결; 전역 변수로 사용

    elif device_type == 'can':
        from .canLib import CANBus
        canBus = CANBus(config=grouped_device['can'],
                        git_path=Configure.set['system']['git_path'])  # CAN BUS 연결; 전역 변수로 사용

    elif device_type == 'visa':
        from .visaLib import VisaDev
        visa = VisaDev(config=grouped_device['visa'])  # ViSA 연결; 전역 변수로 사용

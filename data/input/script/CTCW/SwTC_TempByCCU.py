import pandas as pd
import numpy as np
from threading import Thread
from tqdm import tqdm
import time
from Lib.Common import export_csv_list
from Lib.Inst import canBus, t32
from Lib.DataProcess import signal_step_graph, judge_final_result, find_out_signals_for_col

OUTPUT_PATH = ''

title = ['SwTC_101']
outcome = [title]

input_data = [[1, 3, 3, i, None, None, 1] for i in range(5, 31)]  # Set temp
dev_in_sigs = [['HS-RGW_T1', 'CC_01_200ms', 'ACSetSta', 0.2],
               ['HS-RGW_T1', 'CC_01_200ms', 'ACSetTemp', 0.2],
               ['HS-RGW_T1', 'CC_01_200ms', 'ACCurtemp_1', 0.2],
               ['HS_M', 'CCU_CCS_01_00ms_2', 'SetCargoWrngValue', 0.5],
               ['HS_M', 'IVI_USM_E_01', 'IVI_ACTempWrngValCtrl', 0.5],
               ['HS_M', 'IVI_USM_E_01', 'IVI_ACUSMReset', 0.5]]
dev_out_sigs = [['HS_M', 'PBVDC_04_200ms_1', 'ACTempWrngSta'],
               ['HS_M', 'PBVDC_04_200ms_1', 'ACTempWrngVal']]
dev_all_sigs = [msg[:3] for msg in dev_in_sigs + dev_out_sigs]

in_col = [f'In: {sig[2]}' for sig in dev_in_sigs]
out_col = [f'Out: {sig[2]}' for sig in dev_out_sigs]
data_col = in_col + out_col
total_col = ['Elapsed_Time'] + data_col
outcome.append(total_col)

final_result = 'Pass'


class LogThread(Thread):
    def __init__(self, can_bus):
        super().__init__()
        self.can = can_bus
        self.in_data = [None for _ in range(6)]
        self.log_state = False
        self.log_lst = []
        self.sample_rate = 0.01
        self.start_test = time.time()

    def run(self):
        while True:
            if self.log_state:
                can_out = self.can.devs['HS_M'].read_msg_by_frame('PBVDC_04_200ms_1', decode_on=False)
                if can_out:
                    wrngSta = can_out['ACTempWrngSta']
                    wrngVal = can_out['ACTempWrngVal']
                else:
                    wrngSta = None
                    wrngVal = None
                elapsed = round((time.time() - self.start_test), 2)
                self.log_lst.append([elapsed] + self.in_data + [wrngSta, wrngVal])
            time.sleep(self.sample_rate)


canBus.stop_all_period_msg()
t32.reset_go()
time.sleep(0.5)

# 초기화
canBus.devs['HS-RGW_T1'].send_periodic_signal('CC_01_200ms', 'ACSetSta', 1, 0.2)  # 냉동기 작동
canBus.devs['HS_M'].send_signal('CCU_CCS_01_00ms_2', 'SetCargoWrngValue', 3, 0.5, True)  # NVM 초기화 값
time.sleep(1)

# Measure Data Thread 설정
log_th = LogThread(can_bus=canBus)
log_th.start()
log_th.log_state = True

for i in tqdm(input_data,
              total=len(input_data),  # 전체 진행수
              desc='Running',  # 진행률 앞쪽 출력 문장
              ncols=100,  # 진행률 출력 폭 조절
              leave=True,  # True 반복문 완료시 진행률 출력 남김. False 남기지 않음.
              colour='green'  # Bar 색
              ):
    if i[0] != 255:
        canBus.devs['HS-RGW_T1'].send_periodic_signal('CC_01_200ms', 'ACSetSta', i[0], 0.2)
        canBus.devs['HS-RGW_T1'].send_periodic_signal('CC_01_200ms', 'ACSetTemp', i[1], 0.2)
        canBus.devs['HS-RGW_T1'].send_periodic_signal('CC_01_200ms', 'ACCurtemp_1', i[2], 0.2)
        canBus.devs['HS_M'].send_signal('CCU_CCS_01_00ms_2', 'SetCargoWrngValue', i[3], 0.5, True)
        canBus.devs['HS_M'].send_signal('IVI_USM_E_01', 'IVI_ACTempWrngValCtrl', i[4], 0.5, True)
        canBus.devs['HS_M'].send_signal('IVI_USM_E_01', 'IVI_ACUSMReset', i[5], 0.5, True)
    else:
        canBus.stop_all_period_msg()
        log_th.in_data = [None for _ in range(6)]
        t32.reset_go()
        canBus.devs['HS-RGW_T1'].send_periodic_signal('CC_01_200ms', 'ACSetSta', 1, 0.2)  # 냉동기 작동
        time.sleep(4)
        i[0] = None

    log_th.in_data = i[:6]

    time.sleep(i[-1])

log_th.log_state = False

for log_lst in log_th.log_lst:
    outcome.append(log_lst)

df_log = pd.DataFrame(np.array(log_th.log_lst, dtype=np.float32), columns=total_col)
signal_step_graph(df=df_log.copy(), sigs=dev_all_sigs, x_col='Elapsed_Time', filepath=OUTPUT_PATH, filename=title[0])

outcome.append(['Result', final_result])

export_csv_list(OUTPUT_PATH, title[0], outcome)

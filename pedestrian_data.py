import os
import json
import codecs
from collections.abc import Iterable
from functools import reduce

import pandas as pd
import torch
from torch.utils.data import Dataset
from torch.utils.data.dataset import T_co

with codecs.open(r"config/config.json", 'r', 'utf-8') as config_file:
    config_data = json.load(config_file)
    PEDESTRIAN_DATA_PATH = config_data["Data-Path"]

__SCENARIOS_FILTERED = {".git"}
_scenarios = {scenario: [sample for sample in os.listdir(os.path.join(PEDESTRIAN_DATA_PATH, scenario))
                         if os.path.isdir(os.path.join(PEDESTRIAN_DATA_PATH, scenario, sample))] for scenario in
              filter(lambda f: f not in __SCENARIOS_FILTERED, os.listdir(PEDESTRIAN_DATA_PATH))
              if os.path.isdir(os.path.join(PEDESTRIAN_DATA_PATH, scenario))}


class PedestrianDataset(Iterable):

    def __init__(self, scenarios: list, window_size=200):
        self.locuses = dict()

        for paths in (zip(_scenarios[s],
                          [os.path.join(PEDESTRIAN_DATA_PATH, s, f) for f in _scenarios[s]])
                      for s in scenarios):
            for k, path in paths:
                self.locuses[k] = PedestrianLocus(path, window_size)

    def __len__(self):
        return len(self.locuses)

    def __getitem__(self, index):
        return self.locuses[index]

    def __iter__(self):
        return ((k, v) for k, v in self.locuses.items())


class PedestrianLocus(Dataset):

    def __init__(self, path, window_size, approximately_match=True):
        # 第一个的时间戳将作为最终的时间戳
        x_frame_names = ["Accelerometer", "Gyroscope",
                         "Magnetometer", "Linear Acceleration"]

        x_sub_frames = {f: pd.read_csv(os.path.join(path, f) + ".csv", encoding="utf-8") for f in x_frame_names}
        self.y_frame = pd.read_csv(os.path.join(path, "Location.csv"), encoding="utf-8")
        self.window_size = window_size

        if approximately_match:
            self.x_frame = reduce(lambda left, right: pd.merge_asof(left, right, on="Time (s)", direction="nearest"),
                                  x_sub_frames.values())
        else:
            self.x_frame = reduce(lambda left, right: pd.merge(left, right, on="Time (s)", how="inner"),
                                  x_sub_frames.values())

        time_table = pd.DataFrame({"Time (s)": self.x_frame["Time (s)"],
                                   "nearest_time": self.x_frame["Time (s)"]})
        self.y_frame = pd.merge_asof(self.y_frame, time_table, on="Time (s)", direction="nearest")
        self.y_frame.rename(columns={"Time (s)": "location_time"}, inplace=True)

        self.frame = pd.merge(self.x_frame, self.y_frame, how="left",
                              left_on="Time (s)", right_on="nearest_time")

        self.data_columns = {k: sub_frame.columns for k, sub_frame in x_sub_frames.items()}
        self.data = {k: self.frame[sub_frame.columns].to_numpy(dtype=float)
                     for k, sub_frame in x_sub_frames.items()}
        self.data["Location"] = self.frame[self.y_frame.columns].to_numpy(dtype=float)
        self.data_columns["Location"] = self.y_frame.columns

    def __getitem__(self, index):
        return {k: v[index: index + self.window_size] for k, v in self.data.items()}

    def __len__(self):
        return len(self.frame) - self.window_size + 1

    def __iter__(self):
        return (self[i] for i in range(len(self)))

    def columns_info(self):
        return self.data_columns


if __name__ == "__main__":
    dataset = PedestrianDataset(["Hand-Walk", "Pocket-Walk"])

    for name, locus in dataset:
        print("正在遍历移动轨迹{}... \n".format(name))

        for sample in locus:
            for k, v in sample.items():
                print(k + ":" + str(v.shape))
            break

        print(locus.columns_info())
        break

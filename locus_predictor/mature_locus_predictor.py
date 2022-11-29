import numpy as np
from numpy import cos, sin

from scipy.signal import find_peaks
from scipy.interpolate import interp1d
from scipy.spatial.transform import Rotation

from locus_predictor.helper import measure_initial_attitude, measure_initial_attitude_advanced
from pedestrian_data import PedestrianLocus, PedestrianDataset

# 50Hz 我们假设，人1s内不会迈太多步
MIN_PERIOD = 20
PROMINENCE = (0.05, None)
# 假设步幅为0.8m
PACE_STEP = 0.8
Magic_A=0.37
Magic_B=0.000155
Magic_C=0.1638

def locus_predictor(attitude=None, walk_direction_bias=0,
                    magic=None, pace_inference=None, transform=None, euler="ZXY"):
    """
    一个朴素的预测模型（对于p的预测还不是很准，但是对于姿态预测不错）
    即使不涉及姿态，p仍然不准，比如在桌面上画正方形，加入卡尔曼滤波试试看

    :param euler:
    :param attitude: (theta, phi) 从世界坐标系，旋转到当前坐标系的极角（手机头与地磁的夹角），
    旋转到当前坐标系的滚角（手机头与地平面的夹角）
    :param walk_direction_bias: 手动偏移
    :param magic: pace_inference神奇公式需要的参数
    :param pace_inference:步幅推断器
    :param transform:
    :return:一个预测器
    """
    if magic is None:
        magic = [Magic_A, Magic_B, Magic_C]

    def predict(locus: PedestrianLocus):
        theta, phi = attitude if attitude else measure_initial_attitude(locus, 30)
        # 这里的姿态矩阵定义是：R^{EARTH}_{IMU}，因此p^{EARTH} = R^{EARTH}_{IMU} p^{IMU}
        imu_to_earth = Rotation.from_euler("ZYX", [theta, 0, phi])
        # imu_to_earth = measure_initial_attitude_advanced(locus, 30)

        # 提取传感器信息
        gyroscope_imu_frame, magnetometer_imu_frame, acceleration_imu_frame = locus.data["Gyroscope"][:, 1:], \
            locus.data["Magnetometer"][:, 1:], locus.data["Linear Acceleration"][:, 1:]
        time_frame = locus.data["Gyroscope"][:, 0]

        # 记录力学信息
        info = __record_movement(locus, imu_to_earth, gyroscope_imu_frame,
                                 magnetometer_imu_frame, acceleration_imu_frame, time_frame,
                                 walk_direction_bias, euler=euler)

        info["magic"] = magic
        info["bias"]={
            'test1':[ 1.3220182439646506 ,  0.3731370122755645 ,  -0.002788113290323491 ,  0.03915316431412718 ],#换euler
            'test2': [ 0 ,  0.37 ,  0.000155 ,  0.1638 ],#翻转
            'test3': [0.0681082114306805, 0.1014283955679003, -0.0037350530192257216 ,-0.7657642038598802],
            'test4': [ 3 ,  0.4943875462957725 ,  -0.030123552013203034 ,  -6.794281849340825 ],
            'test5': [ 0.6960844466428142 ,  0.4642259602247386 ,  -0.0062636714640778674 ,  -1.391308642698473 ],
            'test6': [ 0.11488087290831708 ,  0.36846546288830645 ,  5.9447627996637794e-05 ,  0.15989680171856857 ],#换euler
            'test7': [ -0.46918666294603983 ,  2.487404071534488 ,  0.04179098671703162 ,  6.513396041090186 ],
            'test8': [ 0.11961377772316462 ,  0.3694707544354912 ,  -8.348216938939907e-05 ,  0.1610173376714257 ],
            'test9': [ 0.32683416459432657 ,  0.30712775535639186 ,  -0.00289204322924796 ,  -0.03692321568652859 ],
            'test10': [ 0.27601886373030504 ,  0.432988923071056 ,  -0.006236157699263183 ,  0.21087218363432172 ],
        }
        print('magic:[', walk_direction_bias, ", ", magic[0], ", ", magic[1], ", ", magic[2], "]")
        # 行人路经预推演
        info["inference_times"] = 0
        inference = pace_inference(info) if pace_inference else lambda x, y: PACE_STEP
        walk_positions, walk_directions = __simulated_walk(locus, info, inference, walk_direction_bias)
        info["gps_positions_temp"], info["gps_directions_temp"] = __aligned_with_gps(locus, info, walk_positions,
                                                                                     walk_directions)
        # if info["gps_positions_temp"] > 0:
        #     info["gps_positions_temp"] -= info["gps_positions_temp"][0]

        # 行人路经最终推演
        info["inference_times"] = 1
        inference = pace_inference(info) if pace_inference else lambda x, y: PACE_STEP
        walk_positions, walk_directions = __simulated_walk(locus, info, inference, walk_direction_bias)
        # if info["gps_positions_temp"] > 0:
        #     info["gps_positions_temp"] -= (info["gps_positions_temp"][locus.latest_gps_index])

        # 插值
        r = __aligned_with_gps(locus, info, walk_positions, walk_directions)
        if transform is not None:
            r = transform(locus, r)
        return r, info

    return predict


def __record_movement(locus, imu_to_earth, gyroscope_imu_frame,
                      magnetometer_imu_frame, acceleration_imu_frame, time_frame,
                      walk_direction_bias, euler="ZXY"):
    p, v = np.zeros(3), np.zeros(3)  # 获取一个初态

    thetas, phis, alphas, directions = [np.empty(len(time_frame) - 2) for _ in range(4)]
    speeds, accelerations, y_directions = [np.empty((len(time_frame) - 2, 3)) for _ in range(3)]
    for index, (gyroscope_imu, acceleration_imu, magnetometer_imu) in enumerate(
            zip(gyroscope_imu_frame[1: -1], acceleration_imu_frame[1: -1], magnetometer_imu_frame[1: -1])):
        delta_t = (time_frame[index + 2] - time_frame[index]) / 2
        # 姿态变化
        imu_to_earth = imu_to_earth * Rotation.from_euler("xyz", delta_t * gyroscope_imu)

        # 计算姿态角
        if euler == "ZYX":
            thetas[index], phis[index], alphas[index] = imu_to_earth.as_euler("ZYX")
        # 可以解决摆手机问题
        if euler == "ZXY":
            thetas[index], alphas[index], phis[index] = imu_to_earth.as_euler("ZXY")
        # y_directions[index] = imu_to_earth.apply(np.array([0, 1, 0]))

        # 牛顿力学
        acceleration_earth = imu_to_earth.apply(acceleration_imu)
        p += v * delta_t + acceleration_earth * (delta_t ** 2) / 2
        v += acceleration_earth * delta_t

        # 记录运动学信息
        speeds[index] = v
        accelerations[index] = acceleration_earth
        directions[index] = thetas[index]

    peaks_index, _ = find_peaks(speeds[:, 2], distance=MIN_PERIOD, prominence=PROMINENCE)

    info = {"speeds": speeds, "accelerations": accelerations,
            "thetas": thetas, "phis": phis, "time": time_frame[1:-1],
            "peaks": peaks_index, "directions": directions,
            "walk_time": time_frame[1 + peaks_index], "locus": locus,"walk_direction_bias":walk_direction_bias}

    return info


def __simulated_walk(locus, info, inference, walk_direction_bias):
    peaks_index = info["peaks"]
    directions = info["directions"]

    walk_positions = np.zeros((len(peaks_index) + 1, 2))
    walk_directions = np.zeros(len(peaks_index))
    p = np.zeros(2)
    for index, peak in enumerate(peaks_index):
        direction = directions[peak-2: peak+3].mean()
        walk_directions[index] = direction + walk_direction_bias
        pace = inference(index, peak)
        p += pace * np.asarray([cos(np.pi / 2 + walk_directions[index]), sin(np.pi / 2 + walk_directions[index])])
        # y_direction = y_directions[peak][:2]
        # p += pace * y_direction / np.sqrt(y_direction[0] ** 2 + y_direction[1] ** 2)
        walk_positions[index + 1] = p

    info["walk_positions"] = walk_positions
    info["walk_directions"] = walk_directions

    return walk_positions, walk_directions


def __aligned_with_gps(locus, info, walk_positions, walk_directions):
    peaks_index = info["peaks"]
    walk_time = info["walk_time"]

    # 插值
    if len(peaks_index) > 3:
        positions = interp1d(np.concatenate((np.array([0]), walk_time)),
                             walk_positions, kind='cubic', axis=0, fill_value="extrapolate")\
            (locus.y_frame["location_time"])
        directions = interp1d(walk_time, walk_directions, kind='cubic', axis=0, fill_value="extrapolate")\
            (locus.y_frame["location_time"])
    else:
        positions = None
        directions = None

    return positions, directions


if __name__ == "__main__":
    dataset = PedestrianDataset(["Magnetometer"])
    locus_predictor = locus_predictor()
    locus_predictor(dataset["图书馆2"])

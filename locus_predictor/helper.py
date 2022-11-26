from cmath import pi, cos, sin

import numpy as np
from numpy import arctan2

from pedestrian_data import PedestrianLocus
from scipy.spatial.transform import Rotation


# TODO: 适配更多姿态的测量
@np.vectorize
def calculate_phi_from_gravity(x, y, z):
    return pi/2 - np.arctan2(z, np.sqrt(x ** 2 + y ** 2))
    # return np.arccos((x * 0 + y * 0 + z * 1) / np.sqrt(x ** 2 + y ** 2 + z ** 2))

@np.vectorize
def calculate_theta_from_magnetometer(x, y):
    # 手机将长轴作为y轴
    return arctan2(x, y)


"""
在这个函数里，我们希望用两个向量矫正三个自由度的系统，这是不可能的。
因此，我们限制人看手机的姿势（沿着y轴无转动）。
"""
def measure_initial_attitude(locus: PedestrianLocus, window_size):
    gravity_frame = locus.data["Accelerometer"] - locus.data["Linear Acceleration"]
    magnetometer_frame = locus.data["Magnetometer"]
    # 这里得到的phi是沿x轴转动的row
    initial_phi = calculate_phi_from_gravity(gravity_frame[:window_size, 1].mean(),
                                 gravity_frame[:window_size, 2].mean(),
                                 gravity_frame[:window_size, 3].mean())

    # 这里得到的theta是沿z轴转动的yaw
    north = Rotation.from_euler("X", initial_phi).apply(magnetometer_frame[:window_size, 1:].mean(axis=0))
    initial_theta = calculate_theta_from_magnetometer(north[0], north[1])

    # TODO: 下面我们要利用GPS数据做一个纠偏
    # gps_moving_direction = locus.y_frame[""]

    return initial_theta, initial_phi

def __rotation_x(theta):
    return np.matrix([[1, 0, 0],
                      [0, cos(theta), -sin(theta)],
                      [0, sin(theta), cos(theta)]])

def __rotation_y(theta):
    return np.matrix([[cos(theta), 0, sin(theta)],
                      [0, 1, 0],
                      [-sin(theta), 0, cos(theta)]])

def __rotation_z(theta):
    return np.matrix([[cos(theta), -sin(theta), 0],
                      [sin(theta), cos(theta), 0],
                      [0, 0, 1]])

CONV_SIZE = 30
def moving_avg(x):
    return np.convolve(x, np.logspace(0.1, 0.5, CONV_SIZE, endpoint=True) /
                               sum(np.logspace(0.1, 0.5, CONV_SIZE, endpoint=True)), mode="same")
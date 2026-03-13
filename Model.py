from __future__ import annotations  # 放在文件最开头
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from enum import Enum
import numpy as np
from datetime import datetime, timedelta

# --- 枚举定义 ---
class ShipType(Enum):
    """船舶类型，决定观测需求的频率"""
    TYPE_A = "A"  # 只需搜索识别（一次过）
    TYPE_B = "B"  # 低频跟踪 2h
    TYPE_C = "C"  # 高频跟踪 30min

class TaskType(Enum):
    """任务类型"""
    SEEK = "Seek"  # 搜索
    IDENTIFY= "Identify"          # 识别
    TRACK = "Track"        # 跟踪

# 船舶类型到任务类型的映射
SHIP_TO_TASK_TYPE = {
   ShipType.TYPE_A: TaskType.SEEK,
   ShipType.TYPE_B: TaskType.IDENTIFY,
   ShipType.TYPE_C: TaskType.TRACK
}
@dataclass
class TimeWindow:
    """
    可见时间窗口类
    文献参考: 快速计算卫星对目标的可见窗口是规划的前提 [citation:1][citation:9]
    """
    def __init__(
        self,
        satellite_id: int,
        ship_id: int,
        start_time: float,
        end_time: float,
        win_type:str
    ):
        self.satellite_id = satellite_id
        self.ship_id = ship_id
        self.start_time = start_time
        self.end_time = end_time
        # duration 由 start_time 和 end_time 自动计算（总秒数）
        self.duration = end_time - start_time
        # === 新增：占用状态 ===
        self.occupied_intervals: List[Tuple[float, float]] = []  # 已被占用的区间
        self.win_type = win_type

    def is_available(self, start: float, end: float) -> bool:
        """检查该时间段是否可用（C4+C5）"""
        for occ_start, occ_end in self.occupied_intervals:
            # 有重叠则不可用
            if not (end <= occ_start or start >= occ_end):
                return False
        return True

    def occupy(self, start: float, end: float):
        """占用该时间段"""
        self.occupied_intervals.append((start, end))
        self.occupied_intervals.sort()  # 保持有序

@dataclass

class Satellite:
    """
    卫星类
    包含轨道参数、能源约束等
    """
    def __init__(
        self,
        sat_id: int,
        # 轨道参数（简化）
        # 能源约束
        windows_seek: List[TimeWindow],
        windows_identify: List[TimeWindow],
        windows_track: List[TimeWindow],
        # 已规划的消耗（通常从0开始）

    ):

        self.sat_id = sat_id
        self.windows_seek = windows_seek
        self.windows_identify = windows_identify
        self.windows_track = windows_track

        self.sar_power_watts = 300  # 瓦
        self.orbit_period_minutes = 43200  # 12小时
        self.max_imaging_time_per_orbit = 7200  # 60分钟 一圈可以用3600s
        self.used_power = 0.0 #一开始还没用

        # === 新增：调度状态 ===
        self.scheduled_tasks: List[ScheduledTask] = []  # 已调度任务（按时间排序）

        self._orbit_used_time_cache: Dict[int, float] = {}
        self._cache_dirty = True  # 标记缓存是否过期

    def get_used_time_in_orbit(self, orbit_idx: int) -> float:
        """
        获取指定圈次的已用时间（秒）
        使用缓存优化性能
        """
        # 如果缓存有效且未过期，直接返回
        if not self._cache_dirty and orbit_idx in self._orbit_used_time_cache:
            return self._orbit_used_time_cache[orbit_idx]

        # 重新计算该圈已用时间
        orbit_start = orbit_idx * self.orbit_period_minutes
        orbit_end = orbit_start + self.orbit_period_minutes

        used = 0.0
        for st in self.scheduled_tasks:
            task_start = st.start_time
            task_end = st.end_time

            # 计算该任务与当前圈的重叠时间
            overlap_start = max(task_start, orbit_start)
            overlap_end = min(task_end, orbit_end)

            if overlap_start < overlap_end:  # 有重叠
                used += (overlap_end - overlap_start)

        # 更新缓存
        self._orbit_used_time_cache[orbit_idx] = used
        return used

    def invalidate_cache(self):
        """标记缓存过期（在添加/删除任务后调用）"""
        self._cache_dirty = True
        self._orbit_used_time_cache.clear()

    def add_scheduled_task(self, st: ScheduledTask):
        """添加任务并更新缓存状态"""
        self.scheduled_tasks.append(st)
        self.scheduled_tasks.sort(key=lambda x: x.start_time)
        self.invalidate_cache()  # 缓存失效

    def remove_scheduled_task(self, task_id: int):
        """删除任务并更新缓存状态"""
        self.scheduled_tasks = [st for st in self.scheduled_tasks
                                if st.task_id != task_id]
        self.invalidate_cache()  # 缓存失效

class Ship:
    """
    船舶目标类
    点目标通常用经纬度表示
    """

    def __init__(
            self,
            ship_id: int,  # 一共100个
            ship_type: ShipType,
            latitude: float,  # 纬度 (-90 to 90)
            longitude: float,  # 经度 (-180 to 180)
            priority: Optional[float] = None,  # 优先级，默认由 ship_type 决定
            tasks: Optional[List['Task']] = None
    ):
        self.ship_id = ship_id
        self.ship_type = ship_type
        self.latitude = latitude
        self.longitude = longitude
        self.tasks = tasks if tasks is not None else []

        # 根据类型赋予默认优先级（3.0最高，1.0最低）
        if priority is not None:
            self.priority = priority
        elif ship_type == ShipType.TYPE_C:
            self.priority = 3.0  # C类优先级最高
        elif ship_type == ShipType.TYPE_B:
            self.priority = 2.0  # B类次之
        else:
            self.priority = 1.0  # A类最低

@dataclass

class Task:
    """
    观测任务类
    每个任务对应于一个船舶的一次特定观测需求
    """

    def __init__(
        self,
        task_id: int,
        freq: int,
        ship: 'Ship',  # 传入Ship对象，自动关联类型
        duration: float,
        min_interval: float,  # 最小重复间隔（秒），对跟踪任务有效
        task_type: Optional[TaskType] = None,  # 可选自定义，默认由ship_type决定
        dependency_list: Optional[List['Task']] = None,  # 依赖任务列表，初始为空
        satellite: Satellite = None
    ):
        self.task_id = task_id
        self.freq = freq  # 第几次观察
        self.ship = ship  # 关联的船舶对象
        self.ship_id = ship.ship_id  # 方便直接访问
        self.duration = duration
        self.min_interval = min_interval
        self.real_start = -1  # 还未设置
        self.real_end = -1
        self.task_type = task_type
        # 依赖列表，如果传入None则初始化为空列表
        if dependency_list is None:
            self.dependency_list = []
        else:
            self.dependency_list = dependency_list

        self.satellite = satellite
        if task_type==TaskType.SEEK:
            self.profit = 1
        elif task_type==TaskType.IDENTIFY:
            self.profit = 2
        elif task_type==TaskType.TRACK:
            self.profit = 3
        #任务是否被观测
        self.if_scheduled = False

        # === 新增：时间约束相关 ===
        self.earliest_start: float = -1 # 最早可开始时间（由依赖和跟踪约束决定）
        self.latest_start: float = -1  # 最晚可开始时间

        # === 新增：跟踪任务专用 ===
        self.prev_track_task: Optional['Task'] = None  # 上一次跟踪任务（用于C1约束）

        # === 新增：解中填充 ===
        self.assigned_satellite: Optional[int] = None  # 分配的卫星ID
        self.assigned_window: Optional[TimeWindow] = None  # 分配的具体窗口

#-----解的表示----
class ScheduledTask:
    def __init__(self, demand_task: Task, satellite_id: int, start_time: float, end_time: float):
        self.dependency_list = demand_task.dependency_list
        self.task_id = demand_task.task_id   # 直接引用原任务的ID
        self.demand_task = demand_task
        self.satellite_id = satellite_id
        self.start_time = start_time
        self.end_time = end_time
        # 临时标记，用于破坏算子
        self.marked_for_removal = False
        self.profit = demand_task.profit
        self.window = None


class Solution:
    """ALNS解"""
    def __init__(self):
        # 按卫星ID存储已调度的任务列表（按时间升序）
        self.satellite_schedules: Dict[int, List[ScheduledTask]] = {} #卫星id + 卫星完成的任务
        # 快速查找：任务ID -> ScheduledTask（用于依赖检查）
        self.task_id_to_scheduled: Dict[int, ScheduledTask] = {}
        # 总收益（可缓存）
        self.total_profit: float = 0.0

    def add_task(self, sat_id: int, scheduled_task: ScheduledTask):
        """向解中添加一个任务（插入到对应卫星的列表中，保持时间顺序）"""
        if sat_id not in self.satellite_schedules: #如果这个卫星一个任务也没有
            self.satellite_schedules[sat_id] = [] #建一个空的
        # 按开始时间插入
        tasks = self.satellite_schedules[sat_id] #也有可能不是空的
        idx = 0
        while idx < len(tasks) and tasks[idx].start_time < scheduled_task.start_time:
            idx += 1
        tasks.insert(idx, scheduled_task) #列表插入
        self.task_id_to_scheduled[scheduled_task.task_id] = scheduled_task #两个字典都要处理
        self.total_profit += scheduled_task.profit

    def remove_task(self, task_id: int) -> Optional[ScheduledTask]:
        """从解中移除指定任务，返回被移除的任务对象（如果存在）"""
        if task_id not in self.task_id_to_scheduled:
            return None
        st = self.task_id_to_scheduled[task_id]
        sat_id = st.satellite_id
        if sat_id in self.satellite_schedules:
            self.satellite_schedules[sat_id].remove(st)
        del self.task_id_to_scheduled[task_id]
        self.total_profit -= st.profit
        return st

    def remove_tasks(self, task_ids: List[int]) -> List[ScheduledTask]:
        """批量移除任务，返回移除的任务列表"""
        removed = []
        for tid in task_ids:
            st = self.remove_task(tid)
            if st:
                removed.append(st)
        return removed

    def clone(self) -> 'Solution':
        """深拷贝解，用于产生新解"""
        new_sol = Solution()
        # 深拷贝各卫星的任务列表（注意任务对象本身不可变，可浅拷贝，但列表需复制）
        for sat_id, tasks in self.satellite_schedules.items():
            new_sol.satellite_schedules[sat_id] = tasks.copy()
        # 复制映射表
        new_sol.task_id_to_scheduled = self.task_id_to_scheduled.copy()
        new_sol.total_profit = self.total_profit
        return new_sol
    def calculate_total_profit(self) -> float:
        """
        重新计算解的总收益
        遍历所有ScheduledTask，累加profit
        """
        total = 0.0
        # 遍历所有卫星的任务列表
        for sat_id, tasks in self.satellite_schedules.items():
            for st in tasks:
                total += st.profit
        return total


class ConstraintChecker:
    """约束检查器，分层设计"""

    # ========== 第一层：窗口生成时过滤 ==========

    @staticmethod
    def filter_by_window_type(task: Task, windows: List[TimeWindow]) -> List[TimeWindow]:
        """C7 + C8：按任务类型、船舶ID、时间过滤窗口，过滤掉不行的，剩下的是可以插入的"""
        # 1. 第一步：按任务类型过滤窗口
        if task.task_type == TaskType.SEEK:
            type_windows = [w for w in windows if w.win_type == "SEEK"]
        elif task.task_type == TaskType.IDENTIFY:
            type_windows = [w for w in windows if w.win_type == "IDENTIFY"]
        else:  # TRACK
            type_windows = [w for w in windows if w.win_type == "TRACK"]
        # 2. 第二步：按船舶ID过滤窗口（原C8逻辑）
        ship_matched_windows = [w for w in type_windows if w.ship_id == task.ship_id]
        # 3. 第三步：新增时间维度过滤（核心逻辑）
        valid_time_windows = []
        for window in ship_matched_windows:
            # 任务最早开始时间 ≤ 窗口结束时间，且任务最晚开始时间 ≥ 窗口开始时间（有重叠可能）
            if task.earliest_start > window.end_time or task.latest_start < window.start_time:
                continue

            feasible_start = max(window.start_time, task.earliest_start)
            # 任务结束时间 = 可行开始时间 + 任务时长
            feasible_end = feasible_start + task.duration
            # 任务结束时间 ≤ min(窗口结束, 任务最晚开始 + 任务时长)
            if feasible_end > min(window.end_time, task.latest_start + task.duration):
                continue
            # 验证该时间段在窗口中是空闲的（调用TimeWindow的is_available方法）
            if window.is_available(feasible_start, feasible_end):
                valid_time_windows.append(window)

        # 返回最终过滤后的有效窗口
        return valid_time_windows

    #我不想这么生成，计算量有点大，一步一步走，不如直接沿着最前面放进去，但是可以作为一个创新点
    """
    @staticmethod
    def get_valid_slots(window: TimeWindow, task: Task) -> List[Tuple[float, float]]:
        ""C9 + C10：生成满足非负和完全包含的时段""
        # C9: start >= 0
        window_start = max(window.start_time, 0.0)
        window_end = window.end_time

        # C10: 任务必须完全在窗口内
        if window_end - window_start < task.duration:
            return []

        # 生成候选时段（可优化为只生成满足C1的，但C1需要全局信息）
        slots = []
        start = window_start
        while start + task.duration <= window_end:
            slots.append((start, start + task.duration))
            start += 1  # 或更大的步长

        return slots
    """
    # ========== 第二层：依赖检查 ==========

    @staticmethod
    def check_c3_dependency(task: Task, proposed_start: float, #应该开始的时间
                            solution: Solution) -> bool:
        """C3: 所有依赖任务必须已完成"""
        for dep in task.dependency_list:
            if dep.task_id not in solution.task_id_to_scheduled:
                return False
            dep_end = solution.task_id_to_scheduled[dep.task_id].end_time #上一个任务的结束时间
            if dep_end > proposed_start:
                return False
        return True

    # ========== 第三层：资源和冲突检查 ==========

    @staticmethod
    def check_c1_track_window(task: Task, proposed_start: float,
                              solution: Solution) -> bool:
        """C1: 跟踪任务时间窗约束"""
        if task.task_type != TaskType.TRACK or not task.prev_track_task:
            return True

        prev = task.prev_track_task
        if prev.task_id not in solution.task_id_to_scheduled:
            return False  # 前序未调度

        prev_start = solution.task_id_to_scheduled[prev.task_id].start_time
        expected = prev_start + task.min_interval
        return expected - 600 <= proposed_start <= expected + 600  #是否在这个范围内

    @staticmethod
    def check_c2_orbit_energy(satellite: Satellite, task: Task,
                              proposed_start: float) -> bool:
        """
        C2: 单圈能耗约束
        检查任务在proposed_start开始时，所在轨道周期的能耗是否超限
        跨圈任务需要检查两个周期
        """
        duration = task.duration
        proposed_end = proposed_start + duration
        orbit_period = satellite.orbit_period_minutes  # 43200秒 = 12小时

        # 计算任务开始时间所在的圈
        start_orbit_idx = int(proposed_start // orbit_period)
        start_orbit_start = start_orbit_idx * orbit_period
        start_orbit_end = start_orbit_start + orbit_period

        # 计算任务结束时间所在的圈
        end_orbit_idx = int(proposed_end // orbit_period)

        # ========== 情况1：任务不跨圈 ==========
        if start_orbit_idx == end_orbit_idx:
            # 只检查这一圈的已用时间
            used_in_orbit = satellite.get_used_time_in_orbit(start_orbit_idx)
            return used_in_orbit + duration <= satellite.max_imaging_time_per_orbit

        # ========== 情况2：任务跨圈 ==========
        else:
            # 第一部分：从开始到第一圈结束
            first_part_duration = start_orbit_end - proposed_start
            used_in_first_orbit = satellite.get_used_time_in_orbit(start_orbit_idx)

            # 第二部分：从第二圈开始到任务结束
            second_part_duration = proposed_end - (start_orbit_end)  # 即 proposed_end % orbit_period
            used_in_second_orbit = satellite.get_used_time_in_orbit(end_orbit_idx)

            # 两圈都要满足约束
            check_first = (used_in_first_orbit + first_part_duration <=
                           satellite.max_imaging_time_per_orbit)
            check_second = (used_in_second_orbit + second_part_duration <=
                            satellite.max_imaging_time_per_orbit)

            return check_first and check_second

    @staticmethod
    def check_c5_no_overlap(satellite: Satellite, start: float,
                            end: float) -> bool:
        """C5: 任务独占约束（无时间重叠）"""
        for st in satellite.scheduled_tasks:
            # 有重叠？
            if not (end <= st.start_time or start >= st.end_time):
                return False
        return True

    # ========== 第四层：解验证 ==========

    @staticmethod
    def verify_all(solution: Solution, satellites: List[Satellite]) -> Tuple[bool, List[str]]:
        """完整验证解的所有约束"""
        violations = []

        for sat_id, tasks in solution.satellite_schedules.items():
            sat = satellites[sat_id]

            # 按时间排序检查
            sorted_tasks = sorted(tasks, key=lambda x: x.start_time)

            for i, st in enumerate(sorted_tasks):
                task = st.demand_task

                # C3
                if not ConstraintChecker.check_c3_dependency(task, st.start_time, solution):
                    violations.append(f"Sat{sat_id} Task{task.task_id}: C3违反")

                # C1
                if not ConstraintChecker.check_c1_track_window(task, st.start_time, solution):
                    violations.append(f"Sat{sat_id} Task{task.task_id}: C1违反")

                # C2
                if not ConstraintChecker.check_c2_orbit_energy(sat, st.start_time,
                                                               st.end_time - st.start_time):
                    violations.append(f"Sat{sat_id} Task{task.task_id}: C2违反")

                # C5（与前面的任务）
                for prev_st in sorted_tasks[:i]:
                    if not (st.end_time <= prev_st.start_time or st.start_time >= prev_st.end_time):
                        violations.append(f"Sat{sat_id} Task{task.task_id}: C5与Task{prev_st.task_id}重叠")

        return len(violations) == 0, violations


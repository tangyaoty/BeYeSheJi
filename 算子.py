import random
from abc import ABC, abstractmethod
from typing import List, Set,Dict, Tuple, Optional
from Model import Satellite,Solution,ScheduledTask,Task,ConstraintChecker

#--------------------------破坏算子--------------------
class DestroyHeu(ABC):
    def __init__(self, heur_id: int):
        self.Heur_Id = heur_id
        self.CalledTimes = 0
        self.score = 0
        self.type = "Destroy"

    @abstractmethod
    def destroy(self, solution: Solution, size_of_bank: int,
                successor_map: Dict[int, List[int]], rng: random.Random) -> List[int]:
        """返回要删除的任务ID列表"""
        pass

class RandomDestroy(DestroyHeu):
    def __init__(self):
        super().__init__(0)

    def destroy(self, solution: Solution, size_of_bank: int,#想要删除的任务数量
                successor_map: Dict[int, List[int]], rng: random.Random) -> List[int]:
        # 获取所有已调度任务ID
        all_task_ids = list(solution.task_id_to_scheduled.keys())
        if not all_task_ids:
            return []

        # 随机打乱
        rng.shuffle(all_task_ids)
        to_remove = set()
        for tid in all_task_ids:
            if tid in to_remove:
                continue
            # 收集该任务及其所有后继
            cluster = self._collect_successors(tid, successor_map, solution) #后继映射表
            # 将cluster加入to_remove
            to_remove.update(cluster)
            if len(to_remove) >= size_of_bank:
                break
        # 如果还不够，继续从剩余任务中随机补充（不考虑后继，但可能导致依赖缺失？但我们已经尽力了）？？？
        # 为了简单，如果不够就返回当前收集的（可能略少）
        return list(to_remove)[:size_of_bank]

    def _collect_successors(self, start_tid: int, successor_map: Dict[int, List[int]],
                            solution: Solution) -> Set[int]:
        """递归收集所有后继（包括自身）""" #DFS（深度优先搜索） 找所有后继
        visited = set()
        stack = [start_tid] #栈
        while stack:
            tid = stack.pop()
            if tid in visited:
                continue
            visited.add(tid)
            for succ in successor_map.get(tid, []):
                if succ in solution.task_id_to_scheduled:  # 只考虑已调度的后继
                    stack.append(succ)
        return visited
'''
    前驱映射：predecessor_map: Dict[int, List[int]]
    后继映射：successor_map: Dict[int, List[int]]
    这个是由于我的任务具有这个特点，所以需要构建的东西
'''
class ProfitDestroy(DestroyHeu):
    def __init__(self):
        super().__init__(1)

    def destroy(self, solution: Solution, size_of_bank: int,
                successor_map: Dict[int, List[int]], rng: random.Random) -> List[int]:
        # 计算每个任务的收益，并加入随机扰动
        task_profits = []
        for tid, st in solution.task_id_to_scheduled.items():
            # 收益加随机扰动
            perturbed = st.profit * (1 + 0.1 * rng.random())  # 10%扰动
            task_profits.append((tid, perturbed))

        # 按扰动后收益升序排序（优先删收益低的）
        task_profits.sort(key=lambda x: x[1])

        to_remove = set()
        for tid, _ in task_profits:
            if tid in to_remove:
                continue
            cluster = self._collect_successors(tid, successor_map, solution)
            to_remove.update(cluster)
            if len(to_remove) >= size_of_bank:
                break
        return list(to_remove)[:size_of_bank]

    def _collect_successors(self, start_tid: int, successor_map: Dict[int, List[int]],
                            solution: Solution) -> Set[int]:
        visited = set()
        stack = [start_tid]
        while stack:
            tid = stack.pop()
            if tid in visited:
                continue
            visited.add(tid)
            for succ in successor_map.get(tid, []):
                if succ in solution.task_id_to_scheduled:
                    stack.append(succ)
        return visited

class RepairHeu(ABC):
    def __init__(self, heur_id: int):
        self.Heur_Id = heur_id
        self.CalledTimes = 0
        self.score = 0
        self.type = "Repair"

    @abstractmethod
    def repair(self, solution: Solution, bank: List[Task],satellites:List[Satellite],
               successor_map: Dict[int, List[int]], rng: random.Random) -> float:
        """
        将bank中的任务插入到solution中，返回本次插入新增的总收益
        注意：插入成功后，应从bank中移除该任务（或在外部由调用者处理）
        这里我们约定，repair方法会修改bank（移除已插入的任务），并修改solution
        """
        pass

class GreedyProfitRepair(RepairHeu):
    """按收益降序贪心插入，实时检查窗口、能源和冲突"""
    def __init__(self, satellites: List[Satellite]):
        super().__init__(0)

    def repair(self, solution: Solution, bank: List[Task],satellites:List[Satellite],
               successor_map: Dict[int, List[int]], rng: random.Random) -> float:
        # 按收益降序排序
        bank.sort(key=lambda t: t.profit, reverse=True)
        added_profit = 0.0
        i = 0
        while i < len(bank):
            task = bank[i]

            # 依赖检查：所有直接前驱必须在解中
            deps_ok = all(dep.task_id in solution.task_id_to_scheduled
                          for dep in task.dependency_list)
            if not deps_ok:
                i += 1
                continue

            # 计算任务的最早和最晚开始时间（基于依赖和跟踪约束）
            earliest, latest = self._compute_time_window(task, solution)

            # 尝试所有卫星的对应窗口
            best_sat = None
            best_window = None
            best_start = None

            for sat in satellites:
                # 根据任务类型获取窗口列表
                if task.task_type == "SEEK":
                    windows = sat.windows_seek
                elif task.task_type == "IDENTIFY":
                    windows = sat.windows_identify
                else:
                    windows = sat.windows_track

                # 初步过滤（类型、船舶、窗口空闲性、时间区间）
                valid_windows = ConstraintChecker.filter_by_window_type(task, windows)
                for window in valid_windows:
                    # 靠边策略确定候选开始时间
                    if earliest <= window.start_time:
                        cand_start = window.start_time
                    elif latest >= window.end_time:
                        cand_start = window.end_time - task.duration
                    else:
                        cand_start = earliest

                    # 检查是否完全在窗口内
                    if (cand_start < window.start_time or
                        cand_start + task.duration > window.end_time):
                        continue

                    # 检查窗口内该时段是否空闲（filter_by_window_type 可能只检查了最早点）
                    if not window.is_available(cand_start, cand_start + task.duration):
                        continue

                    # 检查卫星任务冲突 (C5)
                    if not ConstraintChecker.check_c5_no_overlap(sat, cand_start, cand_start + task.duration):
                        continue

                    # 检查能源约束 (C2)
                    if not ConstraintChecker.check_c2_orbit_energy(sat, task, cand_start):
                        continue

                    # 选择最早开始时间对应的窗口
                    if best_start is None or cand_start < best_start:
                        best_start = cand_start
                        best_sat = sat
                        best_window = window

            if best_sat is not None:
                # 执行插入
                end_time = best_start + task.duration
                best_window.occupy(best_start, end_time)          # 占用窗口时间段
                st = ScheduledTask(
                    demand_task=task,
                    satellite_id=best_sat.sat_id,
                    start_time=best_start,
                    end_time=end_time
                )
                best_sat.add_scheduled_task(st)                   # 更新卫星任务列表
                solution.add_task(best_sat.sat_id, st)            # 加入解
                added_profit += st.profit
                # 从 bank 中移除
                bank.pop(i)
                # 继续检查下一个（i 不变，因为 pop 后索引前移）
            else:
                i += 1
        return added_profit

    def _compute_time_window(self, task: Task, solution: Solution) -> Tuple[float, float]:
        """根据依赖和跟踪约束计算任务允许的开始时间范围"""
        # 默认周期为 86400 秒，可从外部传入，这里简单取全局最大值
        # 更精确的方式是从规划周期获取，我们假设任务类已有 plan_duration 或由外部传入
        # 这里简化：使用一个足够大的数（如 86400）
        plan_duration = 86400.0
        earliest = 0.0
        latest = plan_duration - task.duration

        # 依赖约束：必须在所有依赖结束后才能开始
        for dep in task.dependency_list:
            dep_st = solution.task_id_to_scheduled.get(dep.task_id)
            if dep_st:
                earliest = max(earliest, dep_st.end_time)

        # 跟踪任务特殊约束 (C1)
        if task.task_type == "TRACK" and task.prev_track_task:
            prev_st = solution.task_id_to_scheduled.get(task.prev_track_task.task_id)
            if prev_st:
                expected = prev_st.start_time + task.min_interval
                earliest = max(earliest, expected - 600)
                latest = min(latest, expected + 600)

        return earliest, latest


# ============================================================
# 新增破坏算子1：TimeWindowDestroy（时间窗集中破坏）
# ============================================================
class TimeWindowDestroy(DestroyHeu):
    """
    选取某颗卫星上任务最密集的时间区段，集中删除其中的任务。
    释放连续的窗口空间，为收益更高的任务批量插入创造机会。
    """
    def __init__(self):
        super().__init__(2)

    def destroy(self, solution: Solution, size_of_bank: int,
                successor_map: Dict[int, List[int]], rng: random.Random) -> List[int]:
        all_scheduled = list(solution.task_id_to_scheduled.values())
        if not all_scheduled:
            return []

        # 按卫星分组任务
        sat_tasks: Dict[int, List] = {}
        for st in all_scheduled:
            sat_tasks.setdefault(st.satellite_id, []).append(st)

        # 找出任务数最多的卫星（目标卫星随机加权选择）
        sat_ids = list(sat_tasks.keys())
        weights = [len(sat_tasks[s]) for s in sat_ids]
        total_w = sum(weights)
        r = rng.random() * total_w
        cum = 0.0
        target_sat_id = sat_ids[-1]
        for sid, w in zip(sat_ids, weights):
            cum += w
            if r <= cum:
                target_sat_id = sid
                break

        tasks_on_sat = sorted(sat_tasks[target_sat_id], key=lambda x: x.start_time)
        if not tasks_on_sat:
            return []

        # 随机选一个任务作为中心，扩展到指定数量
        center_idx = rng.randint(0, len(tasks_on_sat) - 1)
        center_time = tasks_on_sat[center_idx].start_time

        # 按距离中心时间排序，选最近的 size_of_bank 个
        sorted_by_dist = sorted(tasks_on_sat,
                                key=lambda x: abs(x.start_time - center_time))
        to_remove = set()
        for st in sorted_by_dist:
            if len(to_remove) >= size_of_bank:
                break
            cluster = self._collect_successors(st.task_id, successor_map, solution)
            to_remove.update(cluster)

        return list(to_remove)[:size_of_bank]

    def _collect_successors(self, start_tid: int, successor_map: Dict[int, List[int]],
                            solution: Solution) -> Set[int]:
        visited = set()
        stack = [start_tid]
        while stack:
            tid = stack.pop()
            if tid in visited:
                continue
            visited.add(tid)
            for succ in successor_map.get(tid, []):
                if succ in solution.task_id_to_scheduled:
                    stack.append(succ)
        return visited


# ============================================================
# 新增破坏算子2：ShipClusterDestroy（船舶链路破坏）
# ============================================================
class ShipClusterDestroy(DestroyHeu):
    """
    随机选一艘或多艘船，将其所有已调度任务（含后继链路）整体删除。
    为整条任务链重新规划提供机会，有效探索大幅变化的解空间。
    """
    def __init__(self):
        super().__init__(3)

    def destroy(self, solution: Solution, size_of_bank: int,
                successor_map: Dict[int, List[int]], rng: random.Random) -> List[int]:
        all_scheduled = list(solution.task_id_to_scheduled.values())
        if not all_scheduled:
            return []

        # 收集已调度任务中涉及的船舶ID
        ship_ids = list({st.demand_task.ship_id for st in all_scheduled})
        if not ship_ids:
            return []

        rng.shuffle(ship_ids)
        to_remove = set()

        for ship_id in ship_ids:
            if len(to_remove) >= size_of_bank:
                break
            # 找出该船的所有已调度任务
            ship_tasks = [st for st in all_scheduled
                          if st.demand_task.ship_id == ship_id
                          and st.task_id not in to_remove]
            for st in ship_tasks:
                cluster = self._collect_successors(st.task_id, successor_map, solution)
                to_remove.update(cluster)

        return list(to_remove)[:size_of_bank]

    def _collect_successors(self, start_tid: int, successor_map: Dict[int, List[int]],
                            solution: Solution) -> Set[int]:
        visited = set()
        stack = [start_tid]
        while stack:
            tid = stack.pop()
            if tid in visited:
                continue
            visited.add(tid)
            for succ in successor_map.get(tid, []):
                if succ in solution.task_id_to_scheduled:
                    stack.append(succ)
        return visited


# ============================================================
# 新增修复算子：RegretRepair（遗憾值修复）
# ============================================================
class RegretRepair(RepairHeu):
    """
    遗憾值修复算子：
    对bank中每个可安排的任务，计算其在所有可行位置中
    最优与次优插入收益之差（遗憾值）。
    优先插入遗憾值最大的任务，避免贪心策略的局部最优。
    """
    def __init__(self, satellites: List[Satellite], k: int = 2):
        super().__init__(1)
        self.k = k  # 考虑前k优位置

    def repair(self, solution: Solution, bank: List[Task], satellites: List[Satellite],
               successor_map: Dict[int, List[int]], rng: random.Random) -> float:
        added_profit = 0.0

        while bank:
            best_task_idx = None
            best_task_regret = -float('inf')
            best_task_insertion = None  # (sat, window, start, profit)

            scheduled_any = False

            for i, task in enumerate(bank):
                # 依赖检查
                deps_ok = all(dep.task_id in solution.task_id_to_scheduled
                              for dep in task.dependency_list)
                if not deps_ok:
                    continue

                # 计算时间窗
                earliest, latest = self._compute_time_window(task, solution)
                if earliest > latest:
                    continue

                # 更新 task 的 earliest/latest 以便 filter_by_window_type 使用
                task.earliest_start = earliest
                task.latest_start = latest

                # 枚举所有可行插入位置，按 profit/duration 降序取前 k 个
                candidates = []
                for sat in satellites:
                    if task.task_type.value == "Seek":
                        windows = sat.windows_seek
                    elif task.task_type.value == "Identify":
                        windows = sat.windows_identify
                    else:
                        windows = sat.windows_track

                    valid_windows = ConstraintChecker.filter_by_window_type(task, windows)
                    for window in valid_windows:
                        if earliest <= window.start_time:
                            cand_start = window.start_time
                        elif latest >= window.end_time:
                            cand_start = window.end_time - task.duration
                        else:
                            cand_start = earliest

                        if (cand_start < window.start_time or
                                cand_start + task.duration > window.end_time):
                            continue
                        if not window.is_available(cand_start, cand_start + task.duration):
                            continue
                        if not ConstraintChecker.check_c5_no_overlap(
                                sat, cand_start, cand_start + task.duration):
                            continue
                        if not ConstraintChecker.check_c2_orbit_energy(sat, task, cand_start):
                            continue

                        # 候选收益：任务本身profit（位置不影响profit，但可加位置权重）
                        candidates.append((task.profit, sat, window, cand_start))

                if not candidates:
                    continue

                scheduled_any = True
                # 按 profit 降序排序（同profit时取更早）
                candidates.sort(key=lambda x: (-x[0], x[3]))

                best_profit_val = candidates[0][0]
                # 次优：第 k 个（若不足则为0）
                kth_profit_val = candidates[min(self.k - 1, len(candidates) - 1)][0] \
                    if len(candidates) >= 2 else 0

                regret = best_profit_val - kth_profit_val

                if regret > best_task_regret:
                    best_task_regret = regret
                    best_task_idx = i
                    _, b_sat, b_win, b_start = candidates[0]
                    best_task_insertion = (b_sat, b_win, b_start)

            if best_task_idx is None or best_task_insertion is None:
                # 没有任何可安排的任务
                break

            # 执行插入
            task = bank[best_task_idx]
            b_sat, b_win, b_start = best_task_insertion
            end_time = b_start + task.duration
            b_win.occupy(b_start, end_time)
            st = ScheduledTask(
                demand_task=task,
                satellite_id=b_sat.sat_id,
                start_time=b_start,
                end_time=end_time
            )
            b_sat.add_scheduled_task(st)
            solution.add_task(b_sat.sat_id, st)
            added_profit += st.profit
            bank.pop(best_task_idx)

        return added_profit

    def _compute_time_window(self, task: Task, solution: Solution) -> Tuple[float, float]:
        """根据依赖和跟踪约束计算任务允许的开始时间范围"""
        plan_duration = 86400.0
        earliest = 0.0
        latest = plan_duration - task.duration

        for dep in task.dependency_list:
            dep_st = solution.task_id_to_scheduled.get(dep.task_id)
            if dep_st:
                earliest = max(earliest, dep_st.end_time)

        if task.task_type.value == "Track" and task.prev_track_task:
            prev_st = solution.task_id_to_scheduled.get(task.prev_track_task.task_id)
            if prev_st:
                expected = prev_st.start_time + task.min_interval
                earliest = max(earliest, expected - 600)
                latest = min(latest, expected + 600)

        return earliest, latest
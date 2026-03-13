import sys
sys.path.append(r"D:\desktop\毕设\pythonProject\Sea")
import random
import copy
from Model import (
    Ship, Satellite, Task, TaskType, TimeWindow,
    ScheduledTask, Solution, ConstraintChecker
)
from 算子 import (DestroyHeu, RandomDestroy, ProfitDestroy, TimeWindowDestroy, ShipClusterDestroy,
                   RepairHeu, GreedyProfitRepair, RegretRepair)
import math
from typing import List, Dict, Tuple, Optional
def insert_task_to_window(task: Task, window: TimeWindow) -> ScheduledTask:
    """
    极简版本：假设可行性已确认，直接计算并插入
    """
    duration = task.duration
    earliest_start = task.earliest_start

    # 靠边策略
    if earliest_start <= window.start_time:
        real_start = window.start_time  # 靠左
    elif task.latest_start >= window.end_time:
        real_start = window.end_time - duration  # 靠右
    else:
        real_start = earliest_start

    real_end = real_start + duration

    # 直接插入
    window.occupy(real_start, real_end)
    task.real_end = real_end
    task.if_scheduled = True

    return ScheduledTask(
        demand_task=task,
        satellite_id=window.satellite_id,
        start_time=real_start,
        end_time=real_end
    )

from 船和任务 import generate_ships_and_tasks   # 假设修正后的生成函数
from 卫星和窗口 import generate_satellites   # 假设卫星生成函数已定义

def initial_solution(
    csv_path = r"D:\desktop\data\全球\100艘船的航迹\ShipTraj.csv",
        num_ships: int = 100,
        plan_duration: float = 86400,  # 规划周期（秒），默认24小时
        num_satellites: int = 12
) -> Tuple[Solution, List[Satellite]]:
    """
    贪心构造初始可行解：
    - 按照船舶逐一处理，每艘船的任务按依赖顺序（SEEK → IDENTIFY → TRACK1 → TRACK2 …）处理
    - 对于每个任务，计算其可行时间窗口（依赖约束 + 跟踪约束）
    - 在所有卫星中寻找满足窗口类型、船舶ID、空闲区间、圈能耗约束的最早可用窗口
    - 若找到则调用 insert_task_to_window 插入，否则跳过该任务
    """
    # 1. 生成船舶及其任务
    ships = generate_ships_and_tasks(
        csv_path=csv_path,
        num_ships=num_ships,
        plan_duration=plan_duration,
        seed=42
    )

    # 2. 生成卫星
    satellites = generate_satellites(num_satellites)

    # 3. 创建空解
    solution = Solution()
    sat_dict = {sat.sat_id: sat for sat in satellites}

    # 4. 按船舶顺序处理任务（同一船舶内任务列表已按依赖顺序排列）
    for ship in ships:
        for task in ship.tasks:
            # ---- 依赖检查 ----
            # 所有依赖任务必须已在解中
            deps_scheduled = all(
                dep.task_id in solution.task_id_to_scheduled
                for dep in task.dependency_list
            )
            if not deps_scheduled:
                continue  # 依赖未完成，当前任务无法安排

            # ---- 计算任务的最早/最晚开始时间 ----
            # 默认最早为0，最晚为周期结束减去任务时长
            earliest = 0.0
            latest = plan_duration - task.duration

            if task.task_type == TaskType.SEEK:
                # SEEK 无特殊约束
                pass
            elif task.task_type == TaskType.IDENTIFY:
                # IDENTIFY 必须在依赖（SEEK）结束后开始
                dep = task.dependency_list[0]
                dep_end = solution.task_id_to_scheduled[dep.task_id].end_time
                earliest = max(earliest, dep_end)
            else:  # TRACK
                # TRACK 必须满足 C1 约束：开始时间 ∈ [expected-600, expected+600]
                dep = task.dependency_list[0]  # 依赖即为前一个任务
                prev_start = solution.task_id_to_scheduled[dep.task_id].start_time
                expected = prev_start + task.min_interval  # 理想开始时间
                earliest = max(earliest, dep.real_end, expected - 600)
                latest = min(latest, expected + 600)

            # 若时间窗已无可能，跳过
            if earliest > latest:
                continue
            task.earliest_start = earliest
            task.latest_start = latest

            # ---- 在所有卫星中寻找可用窗口 ----
            best_start = float('inf')
            best_sat_window = None  # 存储 (sat, window)

            for sat in satellites:
                # 根据任务类型获取对应窗口列表
                if task.task_type == TaskType.SEEK:
                    windows = sat.windows_seek
                elif task.task_type == TaskType.IDENTIFY:
                    windows = sat.windows_identify
                else:
                    windows = sat.windows_track

                # 调用约束检查器过滤出符合类型、船舶、空闲、时间约束的窗口
                valid_windows = ConstraintChecker.filter_by_window_type(task, windows)

                for window in valid_windows:
                    # ---- 确定具体的开始时间（靠边策略） ----
                    if task.earliest_start <= window.start_time:
                        proposed_start = window.start_time
                    elif task.latest_start >= window.end_time:
                        proposed_start = window.end_time - task.duration
                    else:
                        proposed_start = task.earliest_start

                    # 确保开始时间产生的区间完全在窗口内
                    if (proposed_start < window.start_time or
                            proposed_start + task.duration > window.end_time):
                        continue

                    # 再次检查该时间段在窗口内是否空闲（防止filter_by_window_type只检查了最左点）
                    if not window.is_available(proposed_start, proposed_start + task.duration):
                        continue
                        # 在确定 proposed_start 后，检查 C5
                    if not ConstraintChecker.check_c5_no_overlap(sat, proposed_start,
                                                                     proposed_start + task.duration):
                        continue
                    # 检查卫星单圈能耗约束（C2）
                    if not ConstraintChecker.check_c2_orbit_energy(sat, task, proposed_start):
                        continue

                    # 选择最早开始时间对应的窗口
                    if proposed_start < best_start:
                        best_start = proposed_start
                        best_sat_window = (sat, window)

            # ---- 若找到可行窗口，调用 insert_task_to_window 插入 ----
            if best_sat_window is not None:
                sat, window = best_sat_window
                st = insert_task_to_window(task, window)  # 此函数会占用窗口并返回 ScheduledTask
                sat.add_scheduled_task(st)  # 更新卫星的调度列表（缓存失效）
                solution.add_task(sat.sat_id, st)  # 将任务加入解

    return solution, satellites

def print_solution_summary(solution: Solution, satellites: list, plan_duration: float = 86400):
    """
    打印解的摘要：总收益、各卫星任务数及任务明细（包含船舶ID），
    并统计每个卫星在各轨道周期内的占用时间。
    """
    print("\n" + "=" * 70)
    print("初始解生成完成！")
    print(f"总收益 (Total Profit): {solution.total_profit:.2f}")
    print("=" * 70)

    total_tasks = 0
    for sat_id, tasks in solution.satellite_schedules.items():
        print(f"\n卫星 {sat_id}  (共 {len(tasks)} 个任务):")
        # 表头增加"船ID"列
        print(f"{'任务ID':<8}{'船ID':<6}{'类型':<10}{'开始时间(s)':<15}{'结束时间(s)':<15}{'收益':<6}")
        print("-" * 70)
        for st in tasks:
            task_type = st.demand_task.task_type.value
            ship_id = st.demand_task.ship.ship_id   # 从任务关联的船舶对象获取ID
            print(f"{st.task_id:<8}{ship_id:<6}{task_type:<10}{st.start_time:<15.2f}{st.end_time:<15.2f}{st.profit:<6}")
        total_tasks += len(tasks)

        # ---- 统计该卫星在各轨道圈次的占用时间 ----
        sat = satellites[sat_id]
        orbit_period = sat.orbit_period_minutes      # 轨道周期（秒），实际为43200秒
        max_per_orbit = sat.max_imaging_time_per_orbit  # 每圈最大成像时间（秒）

        # 计算规划周期内需要显示的圈次数量（向上取整）
        num_orbits = int(math.ceil(plan_duration / orbit_period))
        print(f"\n  卫星 {sat_id} 各圈占用时间（周期={orbit_period/3600:.1f}小时，最大{max_per_orbit/60:.1f}分钟/圈）：")
        print(f"  {'圈次':<6}{'占用时间(秒)':<15}{'占用率(%)':<10}{'剩余可用(秒)':<15}")
        for orbit_idx in range(num_orbits):
            orbit_start = orbit_idx * orbit_period
            if orbit_start >= plan_duration:
                break   # 超出规划周期范围，不再显示
            used = sat.get_used_time_in_orbit(orbit_idx)
            ratio = used / max_per_orbit * 100 if max_per_orbit > 0 else 0
            remaining = max_per_orbit - used
            print(f"  {orbit_idx:<6}{used:<15.2f}{ratio:<10.1f}{remaining:<15.2f}")

    print("\n" + "=" * 70)
    print(f"总计调度任务数: {total_tasks}")
    print("=" * 70)


# ---------- ALNS 主类 ----------
class ALNSOptimizer:
    def __init__(self,
                 satellites: List[Satellite],
                 successor_map: Dict[int, List[int]],
                 plan_duration: float = 86400,
                 random_seed: int = 42):
        self.satellites = satellites
        self.successor_map = successor_map
        self.plan_duration = plan_duration
        self.rng = random.Random(random_seed)

        # 初始化算子池（破坏：随机 / 低收益 / 时间窗集中 / 船链路；修复：贪心 / 遗憾值）
        self.destroy_ops = [
            RandomDestroy(),
            ProfitDestroy(),
            TimeWindowDestroy(),
            ShipClusterDestroy(),
        ]
        self.repair_ops = [
            GreedyProfitRepair(self.satellites),
            RegretRepair(self.satellites),
        ]

        # 算子权重和分数
        self.destroy_weights = [1.0] * len(self.destroy_ops)
        self.repair_weights = [1.0] * len(self.repair_ops)
        self.destroy_scores = [0.0] * len(self.destroy_ops)
        self.repair_scores = [0.0] * len(self.repair_ops)
        self.destroy_counts = [0] * len(self.destroy_ops)
        self.repair_counts = [0] * len(self.repair_ops)

        # 温度参数
        self.temperature = 1.0

    def _select_operator(self, weights: List[float]) -> int: #输出算子的标号
        """轮盘赌选择算子索引"""
        total = sum(weights)
        if total <= 0:
            return self.rng.randint(0, len(weights)-1)
        r = self.rng.random() * total
        cum = 0.0
        for i, w in enumerate(weights):
            cum += w
            if r <= cum:
                return i
        return len(weights)-1

    def _update_weights(self, weights: List[float], scores: List[float],
                         counts: List[int], decay: float = 0.8):
        """更新算子权重（使用反应式机制）"""
        for i in range(len(weights)):
            if counts[i] > 0:
                # 使用平均分数更新
                weights[i] = weights[i] * decay + (1 - decay) * (scores[i] / counts[i])
            else:
                weights[i] = weights[i] * decay
            # 重置分数和计数
            scores[i] = 0.0
            counts[i] = 0

    def run(self,
            initial_solution: Solution,
            max_iterations: int = 10000,
            inner_iterations: int = 100,
            initial_temperature_factor: float = 0.05,   # 升高：扩大早期探索接受率
            cooling_rate: float = 0.9998,               # 放缓：延长高温探索阶段
            destroy_min_ratio: float = 0.05,
            destroy_max_ratio: float = 0.4,
            sigma_global: float = 30,
            sigma_local: float = 20,
            sigma_bad: float = 5,
            no_improve_threshold: int = 150,            # 触发重启的阈值
            weight_update_frequency: int = 100) -> Solution:  # 更频繁更新权重
        """
        执行 ALNS 优化
        """
        # 初始化
        current_sol = initial_solution
        best_sol = copy.deepcopy(current_sol)
        current_profit = current_sol.total_profit
        best_profit = current_profit
        initial_profit = current_profit  # 记录初始收益，用于重启时参考

        # 设置初始温度（改进：更高温度保证早期探索）
        if current_profit > 0:
            self.temperature = (initial_temperature_factor * current_profit)
        else:
            self.temperature = 1.0
        initial_temperature = self.temperature

        destroy_ratio = destroy_min_ratio
        no_improve = 0
        restart_count = 0

        outer_iters = max_iterations // inner_iterations
        if outer_iters == 0:
            outer_iters = 1

        for outer in range(outer_iters):
            for inner in range(inner_iterations):
                iter_idx = outer * inner_iterations + inner

                # ---- 重启逃脱机制：连续不改进时从最优解做大扰动后重置 ----
                if no_improve >= no_improve_threshold:
                    restart_count += 1
                    print(f"Iter {iter_idx}: 触发重启 #{restart_count}（连续{no_improve}次未改进），"
                          f"当前最优={best_profit:.2f}")
                    # 从最优解出发，做一次较大规模的破坏->修复
                    current_sol = copy.deepcopy(best_sol)
                    self._sync_satellites(current_sol)
                    restart_size = max(1, int(len(current_sol.task_id_to_scheduled) * 0.25))
                    d_idx_r = self.rng.randint(0, len(self.destroy_ops) - 1)
                    r_idx_r = self.rng.randint(0, len(self.repair_ops) - 1)
                    ids_r = self.destroy_ops[d_idx_r].destroy(
                        current_sol, restart_size, self.successor_map, self.rng)
                    bank_r = []
                    for tid in ids_r:
                        st = current_sol.remove_task(tid)
                        if st:
                            self.satellites[st.satellite_id].remove_scheduled_task(tid)
                            if hasattr(st, 'window') and st.window:
                                interval = (st.start_time, st.end_time)
                                if interval in st.window.occupied_intervals:
                                    st.window.occupied_intervals.remove(interval)
                            bank_r.append(st.demand_task)
                    if bank_r:
                        self.repair_ops[r_idx_r].repair(
                            current_sol, bank_r, self.satellites, self.successor_map, self.rng)
                    current_profit = current_sol.calculate_total_profit()
                    # 重置温度（稍低于初始，防止完全退化）
                    self.temperature = initial_temperature * (0.5 ** restart_count)
                    no_improve = 0
                    destroy_ratio = destroy_min_ratio

                # 在每次迭代前备份当前解状态（用于拒绝时回滚）
                prev_sol = copy.deepcopy(current_sol)
                prev_profit = current_profit

                # 选择破坏和修复算子
                d_idx = self._select_operator(self.destroy_weights)
                r_idx = self._select_operator(self.repair_weights)
                destroy_op = self.destroy_ops[d_idx]
                repair_op = self.repair_ops[r_idx]

                # 计数
                self.destroy_counts[d_idx] += 1
                self.repair_counts[r_idx] += 1

                # 确定破坏数量
                current_size = len(current_sol.task_id_to_scheduled)
                remove_count = max(1, int(current_size * destroy_ratio))
                remove_count = min(remove_count, current_size)

                # ----- 破坏阶段 -----
                to_remove_ids = destroy_op.destroy(current_sol, remove_count,
                                                   self.successor_map, self.rng)

                bank = []
                for tid in to_remove_ids:
                    st = current_sol.remove_task(tid)
                    if st:
                        sat = self.satellites[st.satellite_id]
                        sat.remove_scheduled_task(tid)
                        if hasattr(st, 'window') and st.window:
                            interval = (st.start_time, st.end_time)
                            if interval in st.window.occupied_intervals:
                                st.window.occupied_intervals.remove(interval)
                        bank.append(st.demand_task)

                if not bank:
                    continue

                # ----- 修复阶段 -----
                repair_op.repair(current_sol, bank, self.satellites,
                                 self.successor_map, self.rng)

                # 计算新解收益
                new_profit = current_sol.calculate_total_profit()

                # ----- 接受准则（带模拟退火）-----
                accept = False
                delta = new_profit - current_profit

                if delta > 1e-6:
                    accept = True
                    self.destroy_scores[d_idx] += sigma_global
                    self.repair_scores[r_idx] += sigma_global
                elif new_profit >= best_profit - 1e-6:
                    accept = True
                    self.destroy_scores[d_idx] += sigma_global
                    self.repair_scores[r_idx] += sigma_global
                else:
                    if self.temperature > 1e-10:
                        prob = math.exp(delta / self.temperature)
                        if self.rng.random() < prob:
                            accept = True
                            self.destroy_scores[d_idx] += sigma_bad
                            self.repair_scores[r_idx] += sigma_bad

                if accept:
                    current_profit = new_profit
                    if current_profit > best_profit + 1e-6:
                        best_profit = current_profit
                        best_sol = copy.deepcopy(current_sol)
                        no_improve = 0
                        print('好解，接受了')
                        print(f"Iter {iter_idx}: ★ 新最优 profit = {best_profit:.2f}")
                    else:
                        print('虽然差但还是勉为其难接受了')
                        no_improve += 1
                else:
                    # 拒绝：回滚到本次迭代前的备份（prev_sol），而非始终回滚到全局最优
                    current_sol = prev_sol
                    current_profit = prev_profit
                    self._sync_satellites(current_sol)
                    no_improve += 1
                    print('挺差的然后我也没接受')

                # 更新温度
                self.temperature *= cooling_rate

                # 动态调整破坏比例
                if no_improve > 50:
                    destroy_ratio = min(destroy_ratio * 1.02, destroy_max_ratio)
                elif no_improve < 10:
                    destroy_ratio = max(destroy_ratio * 0.98, destroy_min_ratio)

                # 定期更新算子权重
                if (iter_idx + 1) % weight_update_frequency == 0:
                    self._update_weights(self.destroy_weights, self.destroy_scores,
                                         self.destroy_counts)
                    self._update_weights(self.repair_weights, self.repair_scores,
                                         self.repair_counts)

            # 外循环结束

        print(f"优化结束：共触发重启 {restart_count} 次，最终最优收益 = {best_profit:.2f}")
        return best_sol

    def _sync_satellites(self, sol: Solution):
        """将卫星的 scheduled_tasks 与 sol 同步（用于回滚后恢复卫星状态）"""
        for sat in self.satellites:
            sat.scheduled_tasks = []
            if sat.sat_id in sol.satellite_schedules:
                sat.scheduled_tasks = list(sol.satellite_schedules[sat.sat_id])
            sat.invalidate_cache()

# ---------- 使用示例 ----------
def run_alns_example():
    # 假设已经生成 initial_solution 和 satellites
    # 这里只是示例框架

    csv_path = r"D:\desktop\data\全球\100艘船的航迹\ShipTraj.csv"  # 船舶轨迹文件
    # 卫星数据存放目录（generate_satellites 内部会拼接具体文件名）

    # 参数设置
    num_ships = 100
    plan_duration = 86400  # 24小时（秒）
    num_satellites = 12

    print("正在生成初始解，请稍候...")
    init_sol, satellites = initial_solution(
        csv_path=csv_path,
        num_ships=num_ships,
        plan_duration=plan_duration,
        num_satellites=num_satellites
    )
    print("初始解是:",init_sol)
    # print_solution_summary(solution, satellites)
    # 可选：按船舶类型统计调度情况
    type_counts = {t: 0 for t in TaskType}
    scheduled_ids = set()
    for tasks in init_sol.satellite_schedules.values():
        for st in tasks:
            type_counts[st.demand_task.task_type] += 1
            scheduled_ids.add(st.task_id)

    print("\n按任务类型统计调度数量：")
    for tt, cnt in type_counts.items():
        print(f"  {tt.value}: {cnt}")

    # 统计总任务数（来自生成的所有船舶任务）
    ships = generate_ships_and_tasks(
        csv_path=csv_path,
        num_ships=num_ships,
        plan_duration=plan_duration,
        seed=42
    )
    total_all_tasks = sum(len(ship.tasks) for ship in ships)
    print(f"\n总任务需求数: {total_all_tasks}")
    print(f"调度覆盖率: {len(scheduled_ids) / total_all_tasks * 100:.2f}%")

    # 构建后继映射（任务依赖关系）
    all_tasks = [task for ship in ships for task in ship.tasks]  # ships 需要从生成函数返回
    successor_map = {task.task_id: [] for task in all_tasks}
    for task in all_tasks:
        for dep in task.dependency_list:
            successor_map[dep.task_id].append(task.task_id)
    # 创建优化器
    optimizer = ALNSOptimizer(
        satellites=satellites,
        successor_map=successor_map,
        plan_duration=plan_duration,
        random_seed=42
    )
    # 运行优化
    best_solution = optimizer.run(
        initial_solution=init_sol,
        max_iterations=5000,
        inner_iterations=100
    )
    print(f"优化完成，最优收益: {best_solution.total_profit:.2f}")
    return best_solution

if __name__ == "__main__":
    run_alns_example()
from enum import Enum
from Model import Task,Satellite,Ship,ShipType,TaskType,TimeWindow
import random
from typing import Optional, List, Tuple
import random
import pandas as pd
import sys
sys.path.append(r"D:\desktop\毕设\pythonProject\Sea")

# ==================== 任务生成函数 ====================
def generate_ships_and_tasks(
    csv_path: str,
    num_ships: int = 100,
    plan_duration: float = 86400,  # 规划周期（秒），默认24小时
    seed: int = 42
) -> List[Ship]:
    """
    从CSV读取船舶初始位置，生成任务列表，返回船舶列表（每艘船包含其所有任务）
    """
    random.seed(seed)

    # --- 1. 分配船舶类型（随机，但可复现）---
    ship_types = []
    counts = {
        ShipType.TYPE_A: int(num_ships * 0.2),
        ShipType.TYPE_B: int(num_ships * 0.4),
        ShipType.TYPE_C: int(num_ships * 0.4)
    }
    diff = num_ships - sum(counts.values())
    if diff != 0:
        counts[ShipType.TYPE_A] += diff

    for st, cnt in counts.items():
        ship_types.extend([st] * cnt)
    random.shuffle(ship_types)

    # --- 2. 从CSV读取船舶初始位置（第二行）---
    df = pd.read_csv(csv_path)
    row = df.iloc[1]  # 第二行数据（索引1），第一行是标题
    # 提取所有经纬度，按顺序：纬度、经度、纬度、经度...
    positions = []
    # 从索引1开始，步长为2取纬度，经度是下一个索引
    for i in range(1, len(row), 2):
        lat = row[i]        # 纬度
        lon = row[i + 1]    # 经度
        positions.append((lat, lon))

    assert len(positions) == num_ships, f"CSV中船舶数量应为{num_ships}，实际为{len(positions)}"

    # --- 3. 创建船舶对象（初始 tasks 为空）---
    ships = []
    for i, st in enumerate(ship_types, start=1):
        lat, lon = positions[i - 1]
        ships.append(Ship(ship_id=i, ship_type=st, latitude=lat, longitude=lon))

    # --- 4. 为每艘船生成任务并建立依赖 ---
    task_id_counter = 0  # 新增全局ID计数器
    for ship in ships:
        # ---- SEEK 任务 ----
        seek_task = Task(
            task_id=task_id_counter,
            freq=1,
            ship=ship,
            duration=60.0,
            min_interval=0.0,
            task_type=TaskType.SEEK,
            dependency_list=[]  # 无依赖
        )
        ship.tasks.append(seek_task)
        task_id_counter+=1
        # ---- IDENTIFY 任务（依赖于 SEEK） ----
        identify_task = Task(
            task_id=task_id_counter,
            freq=1,
            ship=ship,
            duration=60.0,
            min_interval=0.0,
            task_type=TaskType.IDENTIFY,
            dependency_list=[seek_task]  # 直接依赖 seek
        )
        task_id_counter += 1
        ship.tasks.append(identify_task)

        # ---- 跟踪任务（仅B和C） ----
        if ship.ship_type == ShipType.TYPE_B:
            interval = 7200  # 2小时
            num_tracks = int(plan_duration / interval)
        elif ship.ship_type == ShipType.TYPE_C:
            interval = 1800  # 30分钟
            num_tracks = int(plan_duration / interval)
        else:
            num_tracks = 0

        prev_task = identify_task  # 第一个跟踪依赖 identify
        for track_idx in range(1, num_tracks + 1):  # freq从1开始
            track_task = Task(
                task_id=task_id_counter,
                freq=track_idx,
                ship=ship,
                duration=300.0,
                min_interval=interval,
                task_type=TaskType.TRACK,
                dependency_list=[prev_task]  # 只依赖前一个
            )
            track_task.prev_track_task = prev_task
            ship.tasks.append(track_task)
            prev_task = track_task  # 更新为当前任务

    return ships

# ==================== 主程序 ====================
if __name__ == "__main__":
    csv_file = r"D:\desktop\data\全球\100艘船的航迹\ShipTraj.csv"
    all_ships = generate_ships_and_tasks(csv_path=csv_file, num_ships=100, plan_duration=86400)

    # 统计所有任务
    task_type_count = {task_type: 0 for task_type in TaskType}
    total_tasks = 0
    all_tasks = []
    for ship in all_ships:
        for task in ship.tasks:
            all_tasks.append(task)
            task_type_count[task.task_type] += 1
            total_tasks += 1


    successor_map = {task.task_id: [] for task in all_tasks} #key:任务id（前置任务）value：后置任务
    for task in all_tasks:
        for dep in task.dependency_list:#前置任务(其实就一个)
            successor_map[dep.task_id].append(task.task_id)

    print("=" * 50)
    print("任务生成完成！")
    print(f"总任务数: {total_tasks}")
    for tt in TaskType:
        print(f"{tt.value} 任务数: {task_type_count[tt]}")
    print("=" * 50)

    # 示例：显示第1艘船的所有任务依赖
    ship1 = all_ships[0]  # ship_id = 1
    print(f"\n船1 (ID={ship1.ship_id}) 的任务列表（按freq排序）：")
    # 按 freq 排序（freq 已按生成顺序递增）
    ship1.tasks.sort(key=lambda t: t.freq)
    for t in ship1.tasks:
        deps_str = [i.freq for i in t.dependency_list]
        print(f"  freq={t.freq}, type={t.task_type.value}, duration={t.duration}s, deps={deps_str}")
    #for i in range(100):
        #print(all_ships[i].ship_type)

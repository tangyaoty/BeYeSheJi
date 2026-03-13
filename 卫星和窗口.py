#-------------------------------处理数据，生成卫星和它的时间窗口-------------------------
import sys
sys.path.append(r"D:\desktop\毕设\pythonProject\Sea")
import pandas as pd
from typing import List, Tuple, Optional
import os
from Model import TimeWindow,Satellite


def parse_window_string(cell: str) -> Optional[Tuple[float, float]]:
    """
    解析单元格字符串，如 "(123.45 - 678.90)"，返回 (start, end)
    如果是 "(0.00 - 0.00)" 则返回 None
    """
    if pd.isna(cell) or not isinstance(cell, str):
        return None
    cell = cell.strip()
    if cell == "(0.00 - 0.00)":
        return None
    # 去除括号，按 " - " 分割
    content = cell[1:-1]  # 去掉首尾括号
    parts = content.split(" - ")
    if len(parts) != 2:
        return None
    try:
        start = float(parts[0])
        end = float(parts[1])
        return start, end
    except ValueError:
        return None

def load_windows_from_csv(file_path: str, satellite_id: int) -> List[TimeWindow]:
    """
    从单个CSV文件读取所有可见时间窗，返回 TimeWindow 列表
    文件格式：第一列为时间，后续列为各船的窗口数据（第一行可能是汉字列名）
    按列顺序自动分配 ship_id（从0开始）
    """
    df = pd.read_csv(file_path, header=0)  # 第一行作为列名（忽略具体内容）
    # 获取所有列名
    all_columns = df.columns.tolist()
    # 第一列是时间列，跳过；其余列为船数据列
    ship_columns = all_columns[1:]  # 列名列表（可能是汉字）

    windows = []
    for idx, row in df.iterrows():
        # 遍历每一艘船，col_index 从1开始对应ship_id=0
        for col_idx, col_name in enumerate(ship_columns, start=1):
            cell = row[col_name]
            parsed = parse_window_string(cell)
            if parsed is not None:
                start, end = parsed
                ship_id = col_idx - 1  # 根据列位置计算船编号（0-based）
                if "Seek" in file_path:
                    tw = TimeWindow(
                        satellite_id=satellite_id,
                        ship_id=ship_id,
                        start_time=start,
                        end_time=end,
                        win_type="SEEK"
                    )
                    windows.append(tw)
                elif "Ident" in file_path:
                    tw = TimeWindow(
                        satellite_id=satellite_id,
                        ship_id=ship_id,
                        start_time=start,
                        end_time=end,
                        win_type="IDENTIFY"
                    )
                    windows.append(tw)
                elif "Track" in file_path:
                    tw = TimeWindow(
                        satellite_id=satellite_id,
                        ship_id=ship_id,
                        start_time=start,
                        end_time=end,
                        win_type="TRACK"
                    )
                    windows.append(tw)
    return windows

def generate_satellites(num_sats: int = 12) -> List[Satellite]:
    """
    生成 num_sats 颗卫星，每颗卫星从对应文件中读取可见窗口数据
    """
    base_dir = r"D:\desktop\data\data"
    satellites = []

    for sat_index in range(1, num_sats + 1):
        sat_id = sat_index - 1
        seek_file = os.path.join(base_dir, f"sat{sat_index}-SeekWin.csv")
        ident_file = os.path.join(base_dir, f"sat{sat_index}-IdentWin.csv")
        track_file = os.path.join(base_dir, f"sat{sat_index}-TrackWin.csv")

        print(f"正在读取卫星 {sat_id} 的文件...")
        windows_seek = load_windows_from_csv(seek_file, satellite_id=sat_id)
        windows_identify = load_windows_from_csv(ident_file, satellite_id=sat_id)
        windows_track = load_windows_from_csv(track_file, satellite_id=sat_id)

        print(f"卫星 {sat_id}: seek={len(windows_seek)}, identify={len(windows_identify)}, track={len(windows_track)}")

        sat = Satellite(
            sat_id=sat_id,
            windows_seek=windows_seek,
            windows_identify=windows_identify,
            windows_track=windows_track
        )
        satellites.append(sat)

    return satellites

if __name__ == "__main__":
    sats = generate_satellites(12)
    print(f"\n共生成 {len(sats)} 颗卫星")
    # 示例：打印卫星0的前3个窗口
    print("\n卫星0 的前6个 seek 窗口：")
    for tw in sats[0].windows_seek[:6]:
        print(f"  卫星{tw.satellite_id}, 船{tw.ship_id}, 时间[{tw.start_time:.2f}-{tw.end_time:.2f}]")
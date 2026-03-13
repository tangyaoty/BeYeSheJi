#---------------------------------画原来的路线------------------------------------------------
import pandas as pd
import matplotlib.pyplot as plt
# 文件路径（注意使用原始字符串或双反斜杠）
file_path = r"D:Desktop\data\全球\100艘船的航迹\ShipTraj.csv"

# 读取CSV，第一行作为列名（表头）
# 第二列是纬度，第三列是经度
df = pd.read_csv(file_path)

# 提取经度（第三列，索引2）和纬度（第二列，索引1）
# 注意：如果列名不是标准英文，也可直接用列位置，但pandas默认将第一行作为列名
lon = df.iloc[:, 8]   # 第三列
lat = df.iloc[:, 7]   # 第二列

# 绘制轨迹
plt.figure(figsize=(10, 8))
plt.plot(lon, lat, marker='.', linestyle='-', markersize=2, linewidth=1)
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.title("Ship Trajectory")
plt.grid(True)
plt.show()

#------------------------------预测新的路线，画图------------------------------------------------

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

# 文件路径
input_file = r"D:\desktop\data\全球\100艘船的航迹\ShipTraj.csv"
output_file = r"D:\desktop\data\全球\100艘船的航迹\predict.xlsx"

# 读取CSV文件
df = pd.read_csv(input_file)

# 获取列名
columns = df.columns.tolist()
time_col = columns[0]          # 第一列为时间
ship_cols = columns[1:]         # 后续列为船的数据

# 确定船的数量（每两列为一艘船）
num_ships = len(ship_cols) // 2

# 提取时间列
time_vals = df[time_col].values.astype(float)
last_time = time_vals[-1]
print(f"最后已知时间: {last_time} 秒")

# 获取最后五行数据
last_five = df.tail(5).copy()
t0, t1, t2, t3, t4 = last_five[time_col].values

# 计算各段时间间隔
dt01 = t1 - t0
dt12 = t2 - t1
dt23 = t3 - t2
dt34 = t4 - t3
dt_total = t4 - t0  # 总时间差（用于方向计算）

# 存储每艘船的最终速度向量 (vx, vy) —— 方向由 t0->t4 决定，大小由各段平均速度决定
velocities = {}

for i in range(num_ships):
    lon_col = ship_cols[i*2]
    lat_col = ship_cols[i*2+1]

    # 提取最后五个点的经纬度
    lon0, lon1, lon2, lon3, lon4 = last_five[lon_col].values
    lat0, lat1, lat2, lat3, lat4 = last_five[lat_col].values

    # ---- 1. 计算方向向量（从倒数第五点到倒数第一点） ----
    dx_dir = lon4 - lon0
    dy_dir = lat4 - lat0
    if dt_total == 0:
        raise ValueError("时间差为零，无法计算方向")
    # 方向速度向量（单位：度/秒）
    vx_dir = dx_dir / dt_total
    vy_dir = dy_dir / dt_total
    dir_norm = np.hypot(vx_dir, vy_dir)  # 方向向量的模（即平均速度大小）

    # ---- 2. 计算四段速度的大小（标量速度）并取平均 ----
    # 第一段速度大小
    speed1 = np.hypot(lon1 - lon0, lat1 - lat0) / dt01 if dt01 != 0 else 0
    speed2 = np.hypot(lon2 - lon1, lat2 - lat1) / dt12 if dt12 != 0 else 0
    speed3 = np.hypot(lon3 - lon2, lat3 - lat2) / dt23 if dt23 != 0 else 0
    speed4 = np.hypot(lon4 - lon3, lat4 - lat3) / dt34 if dt34 != 0 else 0
    avg_speed = (speed1 + speed2 + speed3 + speed4) / 4

    # ---- 3. 合成最终速度向量 ----
    # 单位方向向量 = (vx_dir, vy_dir) / dir_norm
    if dir_norm > 0:
        unit_vx = vx_dir / dir_norm
        unit_vy = vy_dir / dir_norm
    else:
        # 如果最后五点没有位移（静止），则方向任意，速度为零
        unit_vx, unit_vy = 0, 0
        avg_speed = 0

    vx_final = avg_speed * unit_vx
    vy_final = avg_speed * unit_vy
    velocities[i] = (vx_final, vy_final)

# 生成预测时间点（从 last_time+300 到 172200，步长300）
pred_times = np.arange(last_time + 300, 172200 + 300, 300)
pred_times = pred_times[pred_times <= 172200]
print(f"预测时间点数量: {len(pred_times)}")

# 构建预测数据
pred_data = {time_col: pred_times}
for i in range(num_ships):
    lon_col = ship_cols[i*2]
    lat_col = ship_cols[i*2+1]

    # 最后已知位置（t4 时刻）
    last_lon = last_five[lon_col].iloc[-1]
    last_lat = last_five[lat_col].iloc[-1]
    vx, vy = velocities[i]

    # 外推（相对于 t4）
    delta_t = pred_times - t4
    pred_lon = last_lon + vx * delta_t
    pred_lat = last_lat + vy * delta_t

    pred_data[lon_col] = pred_lon
    pred_data[lat_col] = pred_lat

# 创建预测DataFrame并保存
pred_df = pd.DataFrame(pred_data)
pred_df.to_excel(output_file, index=False)
print(f"预测结果已保存至：{output_file}")

# --- 绘制船201的轨迹 ---
# 船201对应的列索引（第一艘船，i=0）
ship201_lon_col = ship_cols[4]
ship201_lat_col = ship_cols[5]

# 提取已知轨迹（所有时间点）
known_times = time_vals
known_lon = df[ship201_lon_col].values
known_lat = df[ship201_lat_col].values

# 提取预测轨迹
pred_lon = pred_df[ship201_lon_col].values
pred_lat = pred_df[ship201_lat_col].values

# 绘图
plt.figure(figsize=(10, 8))
plt.plot(known_lon, known_lat, 'b-o', markersize=3, label='已知轨迹 (蓝色)')
plt.plot(pred_lon, pred_lat, 'r--s', markersize=3, label='预测轨迹 (红色)')
plt.xlabel('经度')
plt.ylabel('纬度')
plt.title('船201轨迹（已知+预测）')
plt.legend()
plt.grid(True)
plt.axis('equal')  # 保持经纬度比例一致
plt.show()



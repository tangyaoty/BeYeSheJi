import csv
import os
import re

# 基准值
BASE = 428572800

# 正则匹配模式：形如 (123.45 - 678.90)
pattern = re.compile(r'^\(([\d.]+) - ([\d.]+)\)$')

def process_cell(cell):
    """处理单元格：如果是 (a - b) 且不是 (0.00 - 0.00)，则两个数减去BASE，并保持两位小数格式"""
    match = pattern.match(cell.strip())
    if not match:
        return cell  # 非目标格式，原样返回

    a_str, b_str = match.groups()
    a = float(a_str)
    b = float(b_str)

    # 如果是 (0.00 - 0.00)，不动
    if a == 0.0 and b == 0.0:
        return cell

    # 否则减去基准
    new_a = a - BASE
    new_b = b - BASE
    return f"({new_a:.2f} - {new_b:.2f})"

def process_file(input_file, output_file):
    """处理单个文件：读取、转换、写入"""
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(input_file, 'r', encoding='utf-8-sig') as fin, \
         open(output_file, 'w', newline='', encoding='utf-8-sig') as fout:

        reader = csv.reader(fin)
        writer = csv.writer(fout)

        for i, row in enumerate(reader):
            new_row = []
            for j, cell in enumerate(row):
                if i == 0:          # 第一行（表头）直接保留
                    new_row.append(cell)
                elif j == 0:         # 第一列（时间）直接保留
                    new_row.append(cell)
                else:
                    new_row.append(process_cell(cell))
            writer.writerow(new_row)

    print(f"处理完成：{output_file}")

def main():
    # 处理12个卫星文件
    for sat_num in range(1, 13):
        input_file = rf"D:\desktop\data\全球\可见时间窗\sat{sat_num}SeekWin.csv"
        output_file = rf"D:\desktop\data\data\sat{sat_num}-SeekWin.csv"
        try:
            process_file(input_file, output_file)
        except FileNotFoundError:
            print(f"警告：文件 {input_file} 不存在，已跳过")
        except Exception as e:
            print(f"处理 {input_file} 时出错：{e}")

if __name__ == "__main__":
    main()
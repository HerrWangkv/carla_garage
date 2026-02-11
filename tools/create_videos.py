import os
import subprocess
import glob
import cv2
import numpy as np
from tqdm import tqdm
import argparse
import re

# --- 默认配置 ---
DEFAULT_SOURCE_DIR = 'my_sunny_dataset'  # 你之前设置的数据集保存路径
VIDEO_ROOT = 'my_sunny_videos'           # 视频输出路径
FRAMERATE = 10
TARGET_WIDTH = 1280
TARGET_HEIGHT = 704

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def natural_sort_key(s):
    """
    让文件名按数字大小排序，而不是按字符排序。
    例如: 2.jpg 会排在 10.jpg 前面
    """
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

def get_depth(path):
    img = cv2.imread(path)
    if img is None: return None

    # CARLA Depth 解码
    img = img.astype(np.float32)
    depth = (img[:,:,2] + img[:,:,1] * 256.0 + img[:,:,0] * 256.0 * 256.0) / (256.0 * 256.0 * 256.0 - 1.0) * 1000.0
    return depth

def create_video_from_frames(frames, output_path, is_disparity=False):
    if not frames:
        return

    # 确保输出目录存在
    ensure_dir(os.path.dirname(output_path))

    # FFMPEG 命令
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
        "-pix_fmt", "bgr24",
        "-r", str(FRAMERATE),
        "-i", "-",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        output_path
    ]

    try:
        # 启动 ffmpeg 进程
        process = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.PIPE
        )

        for path in frames:
            if is_disparity:
                depth = get_depth(path)
                if depth is None: continue

                # 深度转视差可视化 (Inverse Depth)
                inv_depth = 1.0 / (depth + 0.1) 

                # 归一化到 0-255
                mn, mx = inv_depth.min(), inv_depth.max()
                if mx - mn > 0:
                    disp_norm = (inv_depth - mn) / (mx - mn) * 255.0
                else:
                    disp_norm = np.zeros_like(inv_depth)

                disp_img = disp_norm.astype(np.uint8)
                # 转换成伪彩色或灰度图 (这里用灰度转BGR)
                img_resized = cv2.cvtColor(disp_img, cv2.COLOR_GRAY2BGR)

            else:
                img = cv2.imread(path)
                if img is None: continue
                img_resized = img

            # Resize (如果尺寸不匹配)
            if img_resized.shape[1] != TARGET_WIDTH or img_resized.shape[0] != TARGET_HEIGHT:
                img_resized = cv2.resize(img_resized, (TARGET_WIDTH, TARGET_HEIGHT))

            try:
                process.stdin.write(img_resized.tobytes())
            except BrokenPipeError:
                break

        process.stdin.close()
        process.wait()

        if process.returncode != 0:
            print(f"❌ Error creating video: {output_path}")

    except Exception as e:
        print(f"❌ Exception creating video {output_path}: {e}")

def process_scenario(scenario_path, output_root):
    """处理单个 Scenario 文件夹"""
    scenario_name = os.path.basename(scenario_path)

    # 定义输入路径 (根据你的数据集结构，可能是 'rgb' 或 'camera/rgb')
    # 这里我们假设结构是 scenario_folder/rgb/xxx.jpg
    rgb_src = os.path.join(scenario_path, 'rgb')
    depth_src = os.path.join(scenario_path, 'depth') # 或者 'sensor.camera.depth'

    # 兼容性检查：如果在 rgb 下没找到，尝试找 sensor.camera.rgb (carla_garage 有时会这样命名)
    if not os.path.exists(rgb_src) and os.path.exists(os.path.join(scenario_path, 'sensor.camera.rgb')):
        rgb_src = os.path.join(scenario_path, 'sensor.camera.rgb')

    # 定义输出文件路径
    rgb_out_file = os.path.join(output_root, 'rgb', f"{scenario_name}.mp4")
    disp_out_file = os.path.join(output_root, 'disparity', f"{scenario_name}.mp4")

    # 1. 处理 RGB
    if os.path.exists(rgb_src):
        # 支持 jpg 和 png
        images = glob.glob(os.path.join(rgb_src, "*.jpg")) + glob.glob(os.path.join(rgb_src, "*.png"))
        # 关键：按数字排序
        images.sort(key=natural_sort_key)

        if images:
            # print(f"Processing RGB: {scenario_name} ({len(images)} frames)")
            create_video_from_frames(images, rgb_out_file, is_disparity=False)

    # 2. 处理 Depth/Disparity
    if os.path.exists(depth_src):
        images = glob.glob(os.path.join(depth_src, "*.png")) # 深度图通常是 png
        images.sort(key=natural_sort_key)

        if images:
            # print(f"Processing Depth: {scenario_name} ({len(images)} frames)")
            create_video_from_frames(images, disp_out_file, is_disparity=True)

def main():
    parser = argparse.ArgumentParser(description="Convert CARLA image folders to video")
    parser.add_argument("--source", default=DEFAULT_SOURCE_DIR, help="Path to the dataset root folder")
    parser.add_argument("--output", default=VIDEO_ROOT, help="Path to save videos")
    parser.add_argument("--scenario_path", help="Path to a single scenario folder to process")
    args = parser.parse_args()

    source_dir = args.source
    output_dir = args.output

    if not os.path.exists(source_dir):
        print(f"Error: Source directory '{source_dir}' does not exist.")
        return
    if args.scenario_path:
        # 单场景模式：只处理指定的这一个文件夹
        if os.path.exists(args.scenario_path):
            print(f"🎬 正在为单个场景生成视频: {args.scenario_path}")
            process_scenario(args.scenario_path, args.output)
        else:
            print(f"❌ 错误: 找不到路径 {args.scenario_path}")
    else:
        # 扫描所有子文件夹
        all_items = sorted(os.listdir(source_dir))
        scenarios = []

        # 筛选出包含 'rgb' 或 'sensor.camera.rgb' 子文件夹的目录
        for item in all_items:
            full_path = os.path.join(source_dir, item)
            if os.path.isdir(full_path):
                if (os.path.exists(os.path.join(full_path, 'rgb')) or 
                    os.path.exists(os.path.join(full_path, 'sensor.camera.rgb')) or
                    os.path.exists(os.path.join(full_path, 'depth'))):
                    scenarios.append(full_path)

        print(f"Found {len(scenarios)} scenarios in {source_dir}")

        # 使用 tqdm 显示进度条
        for scenario_path in tqdm(scenarios, desc="Generating Videos"):
            process_scenario(scenario_path, output_dir)

        print(f"✅ All Done! Videos saved to: {output_dir}")

if __name__ == '__main__':
    main()
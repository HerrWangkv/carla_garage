import os
import subprocess
import glob
import cv2
import numpy as np
from tqdm import tqdm

SOURCE_DIR = 'my_10hz_dataset_seq61'
VIDEO_ROOT = 'my_10hz_dataset_videos'
RGB_OUT_DIR = os.path.join(VIDEO_ROOT, 'rgb')
DISP_OUT_DIR = os.path.join(VIDEO_ROOT, 'disparity')

FRAMERATE = 10
TARGET_WIDTH = 1280
TARGET_HEIGHT = 704
MAX_FRAMES = 49

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def get_depth(path):
    # Load image
    img = cv2.imread(path)
    if img is None: return None
    
    # CARLA depth decoding: normalized = (R + G * 256 + B * 256 * 256) / (256 * 256 * 256 - 1)
    # in meters = normalized * 1000
    img = img.astype(np.float32)
    # CV2 reads in BGR
    # R is img[:,:,2], G is img[:,:,1], B is img[:,:,0]
    
    depth = (img[:,:,2] + img[:,:,1] * 256.0 + img[:,:,0] * 256.0 * 256.0) / (256.0 * 256.0 * 256.0 - 1.0) * 1000.0
    return depth

def create_video_from_frames(frames, output_path, is_disparity=False):
    if not frames:
        return

    # ffmpeg command
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
                
                # Inverse depth for disparity visualization
                inv_depth = 1.0 / (depth + 0.1) 
                
                # Normalize. 
                # Since frames can vary, using min/max per frame gives best contrast but flickers.
                # However, for pure inspection, flicker is acceptable to see features.
                # To be stable, we'd need fixed range. 
                # Let's use min/max per frame for maximum visibility.
                
                mn, mx = inv_depth.min(), inv_depth.max()
                if mx - mn > 0:
                    disp_norm = (inv_depth - mn) / (mx - mn) * 255.0
                else:
                    disp_norm = np.zeros_like(inv_depth)

                disp_img = disp_norm.astype(np.uint8)
                
                # Convert to BGR so it's a valid input for bgr24 pipe, but visually grayscale
                img_resized = cv2.cvtColor(disp_img, cv2.COLOR_GRAY2BGR)
                
            else:
                img = cv2.imread(path)
                if img is None: continue
                img_resized = img

            # Resize
            if img_resized.shape[:2] != (TARGET_HEIGHT, TARGET_WIDTH):
                img_resized = cv2.resize(img_resized, (TARGET_WIDTH, TARGET_HEIGHT))

            try:
                process.stdin.write(img_resized.tobytes())
            except BrokenPipeError:
                break
        
        process.stdin.close()
        process.wait()

        if process.returncode != 0:
            print(f"Error creating video {output_path}")
            
    except Exception as e:
        print(f"Exception creating video {output_path}: {e}")

def create_videos():
    ensure_dir(RGB_OUT_DIR)
    ensure_dir(DISP_OUT_DIR)

    try:
        if not os.path.exists(SOURCE_DIR):
            print(f"Source directory {SOURCE_DIR} not found!")
            return

        sequences = sorted([d for d in os.listdir(SOURCE_DIR) if os.path.isdir(os.path.join(SOURCE_DIR, d))])
    except Exception as e:
        print(f"Error listing source directory: {e}")
        return
    
    print(f"Found {len(sequences)} sequences.")

    for seq_name in tqdm(sequences):
        seq_path = os.path.join(SOURCE_DIR, seq_name)
        rgb_path = os.path.join(seq_path, 'rgb')
        depth_path = os.path.join(seq_path, 'depth')
        
        rgb_out = os.path.join(RGB_OUT_DIR, f"{seq_name}.mp4")
        disp_out = os.path.join(DISP_OUT_DIR, f"{seq_name}.mp4")
        
        # Collect Images
        rgb_files = sorted(glob.glob(os.path.join(rgb_path, "*.jpg")))[:MAX_FRAMES]
        depth_files = sorted(glob.glob(os.path.join(depth_path, "*.png")))[:MAX_FRAMES]
        
        # Generate RGB Video
        if os.path.exists(rgb_path) and not os.path.exists(rgb_out) and len(rgb_files) > 0:
            create_video_from_frames(rgb_files, rgb_out, is_disparity=False)
            
        # Generate Disparity Video
        if os.path.exists(depth_path) and not os.path.exists(disp_out) and len(depth_files) > 0:
            create_video_from_frames(depth_files, disp_out, is_disparity=True)

if __name__ == '__main__':
    create_videos()

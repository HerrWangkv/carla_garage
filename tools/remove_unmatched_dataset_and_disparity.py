import os
import shutil

# Paths
DATASET_DIR = "my_sunny_dataset"
RGB_DIR = os.path.join("my_sunny_videos", "rgb")
DISPARITY_DIR = os.path.join("my_sunny_videos", "disparity")

# Get all RGB video base names (without .mp4)
rgb_videos = set()
for fname in os.listdir(RGB_DIR):
    if fname.endswith(".mp4"):
        rgb_videos.add(os.path.splitext(fname)[0])

# Remove dataset folders without corresponding RGB video
for folder in os.listdir(DATASET_DIR):
    folder_path = os.path.join(DATASET_DIR, folder)
    if os.path.isdir(folder_path):
        if folder not in rgb_videos:
            print(f"Removing dataset folder: {folder_path}")
            shutil.rmtree(folder_path)

# Remove disparity videos without corresponding RGB video
for fname in os.listdir(DISPARITY_DIR):
    if fname.endswith(".mp4"):
        base = os.path.splitext(fname)[0]
        if base not in rgb_videos:
            file_path = os.path.join(DISPARITY_DIR, fname)
            print(f"Removing disparity video: {file_path}")
            os.remove(file_path)

import os
import cv2

# Root directory containing scenario folders
data_root = "my_sunny_dataset"

# Subfolders to check in each scenario
folders = ["depth", "rgb", "semantics", "measurements"]

def check_scenario_consistency(scenario_path):
    counts = {}
    for folder in folders:
        full_path = os.path.join(scenario_path, folder)
        if not os.path.isdir(full_path):
            counts[folder] = None
            continue
        # Count files (ignore hidden files)
        files = [f for f in os.listdir(full_path) if not f.startswith('.') and os.path.isfile(os.path.join(full_path, f))]
        counts[folder] = len(files)
    # Video frame checks
    scenario_name = os.path.basename(scenario_path)
    rgb_video_path = os.path.join("my_sunny_videos/rgb", f"{scenario_name}.mp4")
    disparity_video_path = os.path.join("my_sunny_videos/disparity", f"{scenario_name}.mp4")
    video_counts = {}
    for video_type, video_path in [("rgb_video", rgb_video_path), ("disparity_video", disparity_video_path)]:
        if os.path.isfile(video_path):
            cap = cv2.VideoCapture(video_path)
            video_counts[video_type] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
        else:
            video_counts[video_type] = None
    counts.update(video_counts)
    return counts
    return counts

def main():
    # Get all scenario names from dataset and from videos
    dataset_scenarios = set(os.listdir(data_root))
    rgb_video_dir = "my_sunny_videos/rgb"
    disparity_video_dir = "my_sunny_videos/disparity"
    rgb_videos = [f for f in os.listdir(rgb_video_dir) if f.endswith('.mp4')]
    disparity_videos = [f for f in os.listdir(disparity_video_dir) if f.endswith('.mp4')]
    rgb_video_scenarios = set([os.path.splitext(f)[0] for f in rgb_videos])
    disparity_video_scenarios = set([os.path.splitext(f)[0] for f in disparity_videos])

    # Check for videos with no dataset folder
    for scenario in sorted(rgb_video_scenarios | disparity_video_scenarios):
        scenario_path = os.path.join(data_root, scenario)
        has_dataset = os.path.isdir(scenario_path)
        has_rgb_video = scenario in rgb_video_scenarios
        has_disparity_video = scenario in disparity_video_scenarios
        if not has_dataset and (has_rgb_video or has_disparity_video):
            print(f"[INFO] Video exists but dataset folder does NOT for scenario: {scenario}")
            if has_rgb_video:
                print(f"  - RGB video exists")
            if has_disparity_video:
                print(f"  - Disparity video exists")

    # Continue with normal dataset folder checks
    for scenario in sorted(dataset_scenarios):
        scenario_path = os.path.join(data_root, scenario)
        if not os.path.isdir(scenario_path):
            continue
        has_rgb_video = scenario in rgb_video_scenarios
        has_disparity_video = scenario in disparity_video_scenarios
        if not has_rgb_video and not has_disparity_video:
            print(f"[INFO] Dataset folder exists but neither RGB nor disparity video exists for scenario: {scenario}")
        counts = check_scenario_consistency(scenario_path)
        # Check if all counts are identical and not None
        valid_counts = [v for v in counts.values() if v is not None]
        identical = len(set(valid_counts)) == 1 if valid_counts else False
        # Print if all counts are None or zero
        if all((v is None or v == 0)for v in counts.values()):
            print(f"[INFO] All data missing or empty for scenario: {scenario}")
            continue
        if not identical:
            print(f"Scenario: {scenario}")
            for folder, count in counts.items():
                print(f"  {folder}: {count}")
            print(f"  Identical: {identical}\n")
        # Additional check: compare rgb image count to video frame counts
        rgb_img_count = counts.get("rgb")
        rgb_video_count = counts.get("rgb_video")
        disparity_video_count = counts.get("disparity_video")
        if rgb_img_count is not None:
            if rgb_video_count is not None and rgb_img_count != rgb_video_count:
                print(f"  [WARNING] RGB image count ({rgb_img_count}) != RGB video frame count ({rgb_video_count})")
            if disparity_video_count is not None and rgb_img_count != disparity_video_count:
                print(f"  [WARNING] RGB image count ({rgb_img_count}) != Disparity video frame count ({disparity_video_count})")
        # Print if one video exists and the other does not
        if rgb_video_count is not None and disparity_video_count is None:
            print(f"  [INFO] RGB video exists but disparity video does NOT.")
        if rgb_video_count is None and disparity_video_count is not None:
            print(f"  [INFO] Disparity video exists but RGB video does NOT.")

if __name__ == "__main__":
    main()
import os
import glob
import re
import shutil

log_dir = "logs"
log_files = glob.glob(os.path.join(log_dir, "data_collection_*.log"))

print(f"Checking {len(log_files)} data collection log files in {log_dir}...")

errors_found = []
clean_logs = []

# Regex for common python errors
error_pattern = re.compile(r"Traceback \(most recent call last\)|Error:|Exception:|CRITICAL")

for log_file in log_files:
    filename = os.path.basename(log_file)
    scenario_name = filename.replace("data_collection_", "").replace(".xml.log", "")
    
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
            if error_pattern.search(content):
                lines = content.splitlines()
                error_context = "Unknown Error"
                for i, line in enumerate(lines):
                    if "Traceback" in line:
                        error_context = "\n".join(lines[i:i+5]) # Capture first few lines of traceback
                        break
                    if "Error:" in line or "Exception:" in line:
                         error_context = line
                         break
                
                errors_found.append((scenario_name, error_context))
            else:
                clean_logs.append(scenario_name)

    except Exception as e:
        print(f"Could not read {log_file}: {e}")

def cleanup_artifacts(scenario_name):
    print(f"Deleting artifacts for {scenario_name}...")
    
    # 1. Delete Logs
    logs_to_delete = [
        os.path.join(log_dir, f"data_collection_{scenario_name}.xml.log"),
        os.path.join(log_dir, f"carla_server_{scenario_name}.xml.log")
    ]
    for log_path in logs_to_delete:
        if os.path.exists(log_path):
            try:
                os.remove(log_path)
                print(f"  Deleted log: {log_path}")
            except Exception as e:
                print(f"  Failed to delete {log_path}: {e}")

    # 2. Delete Dataset Folder
    # Added underscore _* to glob to prevent prefix matching (e.g. rl_1 matching rl_10)
    dataset_base_dir = "my_10hz_dataset_town10"
    dataset_pattern = os.path.join(dataset_base_dir, f"Town10HD_Rep0_{scenario_name}_*")
    dataset_matches = glob.glob(dataset_pattern)
    
    for p in dataset_matches:
        if os.path.isdir(p):
            try:
                shutil.rmtree(p)
                print(f"  Deleted dataset folder: {p}")
            except Exception as e:
                print(f"  Failed to delete {p}: {e}")

    # 3. Delete Videos
    video_base_dir = "my_10hz_dataset_videos"
    video_subdirs = ["rgb", "disparity"]
    for subdir in video_subdirs:
        video_pattern = os.path.join(video_base_dir, subdir, f"Town10HD_Rep0_{scenario_name}_*.mp4")
        video_matches = glob.glob(video_pattern)
        for p in video_matches:
            try:
                os.remove(p)
                print(f"  Deleted video: {p}")
            except Exception as e:
                print(f"  Failed to delete {p}: {e}")

print(f"\n--- Scenarios with Errors in Logs ({len(errors_found)}) ---")
if not errors_found:
    print("None")
else:
    # Sort by scenario name for better readability
    errors_found.sort(key=lambda x: x[0])
    for scenario, context in errors_found:
        print(f"[{scenario}]")
        print(f"  {context.strip()}")
        print("-" * 40)
        
        # Deletion Logic
        cleanup_artifacts(scenario)

# 4. Cleanup completed_scenarios.txt
completed_scenarios_file = "completed_scenarios.txt"
if os.path.exists(completed_scenarios_file):
    try:
        print(f"\n--- Cleaning up {completed_scenarios_file} ---")
        with open(completed_scenarios_file, "r") as f:
            lines = f.readlines()
        
        new_lines = []
        removed_count = 0
        
        # Set of scenarios that failed (from log analysis above)
        failed_xml_names = {s + ".xml" for s, _ in errors_found}
        
        for line in lines:
            scenario_xml = line.strip()
            if not scenario_xml:
                continue
                
            # Check 1: Is it in the failed list?
            if scenario_xml in failed_xml_names:
                print(f"  Removing {scenario_xml} text entry (Found error in log)")
                removed_count += 1
                continue

            # Check 2: Does the log file exist?
            # Log file is "logs/data_collection_{scenario_xml}.log"
            log_path = os.path.join(log_dir, f"data_collection_{scenario_xml}.log")
            
            # Helper to get base name
            scenario_base = scenario_xml.replace(".xml", "")

            if not os.path.exists(log_path):
                print(f"  Removing {scenario_xml} text entry (Log file missing: {log_path})")
                # Also cleanup artifacts to prevent skipping
                cleanup_artifacts(scenario_base)
                removed_count += 1
                continue

            # Check 3: Does the video exist?
            # If the user deleted the video manually (because it looked bad), we need to clean up everything else so it re-runs.
            video_base_dir = "my_10hz_dataset_videos"
            # Pattern must match how videos are named in cleanup_artifacts
            video_check_pattern = os.path.join(video_base_dir, "rgb", f"Town10HD_Rep0_{scenario_base}_*.mp4")
            
            if not glob.glob(video_check_pattern):
                print(f"  Removing {scenario_xml} text entry (Video file missing/deleted: {video_check_pattern})")
                cleanup_artifacts(scenario_base)
                removed_count += 1
                continue
            
            new_lines.append(line)
        
        if removed_count > 0:
            with open(completed_scenarios_file, "w") as f:
                f.writelines(new_lines)
            print(f"  Updated {completed_scenarios_file}: Removed {removed_count} entries.")
        else:
            print(f"  No entries needed removal from {completed_scenarios_file}.")

    except Exception as e:
        print(f"  Failed to update {completed_scenarios_file}: {e}")

print(f"\n--- Scenarios with Clean Logs ({len(clean_logs)}) ---")
# print(sorted(clean_logs))
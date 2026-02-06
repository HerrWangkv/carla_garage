import os
import shutil
import glob
import re
import argparse
from pathlib import Path
from tqdm import tqdm

def split_dataset(source_dir, dest_dir, seq_len=61):
    source_path = Path(source_dir)
    dest_path = Path(dest_dir)
    
    if not source_path.exists():
        print(f"Source directory {source_path} does not exist.")
        return

    dest_path.mkdir(parents=True, exist_ok=True)

    # List all route directories
    route_dirs = [d for d in source_path.iterdir() if d.is_dir()]
    
    print(f"Found {len(route_dirs)} route directories in {source_dir}")

    for route_dir in tqdm(route_dirs, desc="Processing routes"):
        # Get list of frames from 'rgb' as the source of truth
        rgb_dir = route_dir / 'rgb'
        if not rgb_dir.exists():
            print(f"Skipping {route_dir}: No rgb folder")
            continue
            
        # Get sorted list of all frame files
        frames = sorted(list(rgb_dir.glob('*.jpg')))
        num_frames = len(frames)
        
        if num_frames == 0:
            print(f"Skipping {route_dir}: No frames found")
            continue
            
        # Get all subdirectories that need splitting. Filter out non-sequence folders if any.
        # Commonly these are the data folders.
        subdirs = [d.name for d in route_dir.iterdir() if d.is_dir()]
        
        # Determine number of parts
        num_parts = num_frames // seq_len
        
        if num_parts == 0:
            print(f"Skipping {route_dir}: Less than {seq_len} frames ({num_frames})")
            continue

        # Files to copy as-is (metadata)
        meta_files = list(route_dir.glob('*.json')) + list(route_dir.glob('*.json.gz'))

        for part_idx in range(num_parts):
            start_idx = part_idx * seq_len
            end_idx = start_idx + seq_len
            
            # Get the slice of frame files for this sequence
            # These are Path objects to the rgb files
            frame_slice = frames[start_idx:end_idx]
            
            # New folder name: RouteName_partX
            new_route_name = f"{route_dir.name}_part{part_idx}"
            new_route_path = dest_path / new_route_name
            new_route_path.mkdir(exist_ok=True)
            
            # Copy meta files
            for meta_file in meta_files:
                shutil.copy2(meta_file, new_route_path / meta_file.name)
                
            # Copy sequence chunks
            for subdir in subdirs:
                src_subdir = route_dir / subdir
                dst_subdir = new_route_path / subdir
                dst_subdir.mkdir(exist_ok=True)
                
                # Iterate through the frames in the current slice
                for local_i, rgb_file_path in enumerate(frame_slice):
                    # Get the ID (e.g. "0020")
                    frame_id = rgb_file_path.stem 
                    
                    # Determine target filename (remapped to 0-indexed)
                    target_stem = f"{local_i:04d}"
                    
                    # Find and copy the file for the current subdir
                    # We need to find extensions
                    candidates = []
                    # Common extensions patterns
                    if subdir == 'rgb':
                        # We know this one exists because we iterated it
                        src_file = rgb_file_path
                        dst_file = dst_subdir / f"{target_stem}{src_file.suffix}"
                        shutil.copy2(src_file, dst_file)
                        continue
                        
                    elif subdir == 'measurements':
                        candidates = [f"{frame_id}.json", f"{frame_id}.json.gz"]
                    elif subdir in ['depth', 'semantics', 'semantics_augmented', 'depth_augmented', 'bev_semantics', 'bev_semantics_augmented']:
                        candidates = [f"{frame_id}.png"]
                    elif subdir == 'lidar':
                         candidates = [f"{frame_id}.laz", f"{frame_id}.ply"]
                    elif subdir in ['boxes', 'results']: # results folder sometimes exists?
                        candidates = [f"{frame_id}.json.gz", f"{frame_id}.json"]
                    else:
                        # Try to guess or skip
                        pass
                        
                    # Try to copy
                    for fname in candidates:
                        src_file = src_subdir / fname
                        if src_file.exists():
                            dst_file = dst_subdir / f"{target_stem}{src_file.suffix}"
                            shutil.copy2(src_file, dst_file)
                            break

    print("Splitting complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split dataset into fixed length sequences.")
    parser.add_argument("--source", type=str, default="my_10hz_dataset", help="Source dataset directory")
    parser.add_argument("--dest", type=str, default="my_10hz_dataset_seq61", help="Destination dataset directory")
    parser.add_argument("--length", type=int, default=61, help="Sequence length")
    
    args = parser.parse_args()
    
    split_dataset(args.source, args.dest, args.length)

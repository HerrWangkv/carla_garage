import numpy as np
import argparse
import math
import sys
import os

try:
    from nuscenes.nuscenes import NuScenes
except ImportError:
    print("[ERROR] nuscenes-devkit is not installed. Please run: pip install nuscenes-devkit")
    sys.exit(1)

# -------------------------------
# Math Helpers (Pure Numpy)
# - Identical to NavSim version -
# -------------------------------

def q_to_mat(q):
    """
    Convert quaternion [w, x, y, z] to 3x3 rotation matrix.
    """
    w, x, y, z = q
    return np.array([
        [1 - 2*y*y - 2*z*z, 2*x*y - 2*z*w, 2*x*z + 2*y*w],
        [2*x*y + 2*z*w, 1 - 2*x*x - 2*z*z, 2*y*z - 2*x*w],
        [2*x*z - 2*y*w, 2*y*z + 2*x*w, 1 - 2*x*x - 2*y*y]
    ])

def make_transform_matrix(translation, rotation):
    """
    Construct 4x4 homogenous transform matrix from translation [x,y,z] 
    and rotation ([w,x,y,z] or 3x3 matrix).
    """
    matrix = np.eye(4)
    if isinstance(rotation, (list, tuple, np.ndarray)):
        rotation = np.array(rotation)
        if rotation.shape == (3, 3):
            matrix[:3, :3] = rotation
        elif rotation.shape == (4,):
            # assume w, x, y, z
            matrix[:3, :3] = q_to_mat(rotation)
        else:
            raise ValueError(f"Unknown rotation shape: {rotation.shape}")
    else:
        raise ValueError("Rotation must be array-like")
    
    matrix[:3, 3] = translation
    return matrix

def nusc_to_carla_vec(v):
    """
    Convert vector from NuScenes (Y-Left) to CARLA (Y-Right) convention.
    Effectively flips the Y component.
    """
    return np.array([v[0], -v[1], v[2]])

def mat_to_euler_carla(R):
    """
    Extract Roll, Pitch, Yaw (in degrees) from a CARLA-frame Rotation Matrix.
    """
    sy = math.sqrt(R[0,0] * R[0,0] + R[1,0] * R[1,0])
    singular = sy < 1e-6

    if not singular:
        x = math.atan2(R[2,1], R[2,2]) # Roll
        y = math.atan2(-R[2,0], sy)    # Pitch
        z = math.atan2(R[1,0], R[0,0]) # Yaw
    else:
        x = math.atan2(-R[1,2], R[1,1])
        y = math.atan2(-R[2,0], sy)
        z = 0
    
    return np.degrees(x), np.degrees(y), np.degrees(z)

# -------------------------------
# Main Logic
# -------------------------------

def process_nuscenes(nusc, scene_idx=0, camera_channel='CAM_FRONT'):
    print(f"[INFO] Processing Scene Index: {scene_idx}, Channel: {camera_channel}...")
    
    # 1. Get Calibration Data from SDK
    # We pick the first sample of the chosen scene to get the configuration.
    try:
        scene = nusc.scene[scene_idx]
    except IndexError:
        print(f"[ERROR] Scene index {scene_idx} out of range (Total scenes: {len(nusc.scene)})")
        return

    first_sample_token = scene['first_sample_token']
    sample = nusc.get('sample', first_sample_token)
    
    if camera_channel not in sample['data']:
        print(f"[ERROR] Channel {camera_channel} not found in sample.")
        print(f"Available channels: {list(sample['data'].keys())}")
        return

    # Get sensor data record
    sensor_data_token = sample['data'][camera_channel]
    sd_record = nusc.get('sample_data', sensor_data_token)
    
    # Get calibrated sensor record
    cs_record = nusc.get('calibrated_sensor', sd_record['calibrated_sensor_token'])

    # --- 1. Get Cam2Ego Transform ---
    # NuScenes 'calibrated_sensor' translation/rotation IS the transform from Sensor to Ego.
    # No need to multiply Lidar2Ego * Cam2Lidar manually like in the raw pickle.
    pos_nusc = np.array(cs_record['translation'])
    rot_nusc = cs_record['rotation'] # [w, x, y, z]
    R_cam_to_ego_nusc = q_to_mat(rot_nusc)

    # --- 2. Process Intrinsics ---
    intrinsics = np.array(cs_record['camera_intrinsic'])
    fx = intrinsics[0, 0]
    
    # NuScenes SDK provides explicit width/height in sample_data
    width = sd_record['width']
    height = sd_record['height']

    # Calculate FOV Horizontal
    fov_rad = 2 * np.arctan(width / (2 * fx))
    fov_deg = np.degrees(fov_rad)

    # --- 3. Convert to CARLA Config Space ---
    
    # A. Position Conversion
    # NuScenes Origin: Rear Axle
    # CARLA Origin: Vehicle Center
    # We apply the specific vehicle offsets defined in the original script.
    
    REAR_WHEEL_BASE_OFFSET = 1.4178275
    AXLE_HEIGHT_OFFSET = 0.35 
    
    pos_carla = nusc_to_carla_vec(pos_nusc)
    pos_carla[0] -= REAR_WHEEL_BASE_OFFSET
    pos_carla[2] += AXLE_HEIGHT_OFFSET

    # B. Rotation Conversion
    # Same logic as original script: 
    # 1. Convert Cam(Z-Fwd) to Actor(X-Fwd)
    # 2. Apply Nusc Rotation
    # 3. Flip Y basis vectors for CARLA Left-Handedness
    
    # Step B1: Define Transform from CARLA-Cam-Actor Frame (X-Fwd) to OpenCV Frame (Z-Fwd)
    R_carlacam_to_opencv = np.array([
        [0, 1, 0],
        [0, 0, -1],
        [1, 0, 0]
    ])

    # Step B2: Get CARLA-Cam-Actor orientation in NuScenes Frame
    R_carlacam_to_ego_nusc = R_cam_to_ego_nusc @ R_carlacam_to_opencv
    
    # Step B3: Convert the basis vectors of this rotation from NuScenes Frame to CARLA Frame
    X_vec_carla = nusc_to_carla_vec(R_carlacam_to_ego_nusc[:, 0])
    Y_vec_carla = nusc_to_carla_vec(R_carlacam_to_ego_nusc[:, 1])
    Z_vec_carla = nusc_to_carla_vec(R_carlacam_to_ego_nusc[:, 2])
    
    R_final_carla = np.column_stack([X_vec_carla, Y_vec_carla, Z_vec_carla])

    # Step B4: Extract Euler Angles
    roll, pitch, yaw = mat_to_euler_carla(R_final_carla)

    # --- 4. Print Results ---
    print("\n" + "="*80)
    print("CARLA Garage Configuration Snippet (team_code/config.py)")
    print("="*80)
    print(f"    # Generated from NuScenes {camera_channel}")
    print(f"    self.camera_pos = [{pos_carla[0]:.7f}, {pos_carla[1]:.7f}, {pos_carla[2]:.7f}]  # x, y, z")
    print(f"    self.camera_rot_0 = [{roll:.7f}, {pitch:.7f}, {yaw:.7f}]  # Roll, Pitch, Yaw")
    print("")
    print(f"    self.camera_width = {width}")
    print(f"    self.camera_height = {height}")
    print(f"    self.camera_fov = {fov_deg:.4f}")
    print("    # Don't forget to update crop settings!")
    print(f"    self.cropped_width = {width}")
    print(f"    self.cropped_height = {height}")
    print("="*80)

def main():
    parser = argparse.ArgumentParser(description="Extract CARLA Camera Config from NuScenes Dataset")
    parser.add_argument("--dataroot", default="nuscenes/nuscenes_mini_v1_0", help="Path to NuScenes root directory")
    parser.add_argument("--version", default="v1.0-mini", help="NuScenes version (default: v1.0-mini)")
    parser.add_argument("--channel", default="CAM_FRONT", help="Camera channel name (default: CAM_FRONT)")
    parser.add_argument("--scene_idx", type=int, default=0, help="Index of scene to extract calibration from (default: 0)")
    args = parser.parse_args()

    if not os.path.exists(args.dataroot):
        print(f"[ERROR] Dataroot not found: {args.dataroot}")
        return

    print(f"[INFO] Loading NuScenes {args.version}...")
    nusc = NuScenes(version=args.version, dataroot=args.dataroot, verbose=True)
    
    process_nuscenes(nusc, args.scene_idx, args.channel)

if __name__ == "__main__":
    main()
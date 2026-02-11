import pickle
import numpy as np
import argparse
import math
import sys

# -------------------------------
# Math Helpers (Pure Numpy)
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
    Assumes standard CARLA/Unreal rotation order (Z-Y-X typically, but extracted from matrix components).
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

def load_pkl(path):
    print(f"[INFO] Loading {path}...")
    with open(path, "rb") as f:
        data = pickle.load(f)
    return data

def process_calibration(data, camera_channel='CAM_F0'):
    if isinstance(data, list): 
        # Sometimes list of frames, sometimes dict. 
        # If list, take first frame.
        data = data[0]

    # --- 1. Get Cam2Ego Transform ---
    # Retrieve Lidar2Ego
    l2e_t = data.get('lidar2ego_translation')
    l2e_r = data.get('lidar2ego_rotation') # [w, x, y, z]
    l2e_mat = make_transform_matrix(l2e_t, l2e_r)

    # Retrieve Cam2Lidar
    if 'cams' not in data or camera_channel not in data['cams']:
        print(f"[ERROR] Channel {camera_channel} not found in pkl.")
        return
        
    cam_info = data['cams'][camera_channel]
    c2l_t = cam_info.get('sensor2lidar_translation')
    c2l_r = cam_info.get('sensor2lidar_rotation') # [w, x, y, z]
    c2l_mat = make_transform_matrix(c2l_t, c2l_r)

    # Compose: Cam2Ego = Lidar2Ego * Cam2Lidar
    cam2ego_mat = np.dot(l2e_mat, c2l_mat)
    
    # Extract Translation & Rotation for further processing
    pos_nusc = cam2ego_mat[:3, 3]
    R_cam_to_ego_nusc = cam2ego_mat[:3, :3]

    # --- 2. Process Intrinsics ---
    intrinsics = np.array(cam_info.get('cam_intrinsic'))
    fx = intrinsics[0, 0]
    fy = intrinsics[1, 1]
    cx = intrinsics[0, 2]
    cy = intrinsics[1, 2]

    # Assume standard full HD if not specified, or try to infer? 
    # Usually intrinsics don't store W/H. Assuming 1920x1080 as typical for these datasets.
    # But cx represents the center, usually W/2.
    # For NuScenes / NavSim, standard image size is often 1600x900
    # Let's check typical aspect ratios.
    # cx ~ 960 -> W=1920. cx ~ 800 -> W=1600.
    # cy ~ 560 -> H=1080? cy ~ 450 -> H=900?
    # However, sometimes cx/cy are slightly off-center.
    
    # We will assume:
    width = 1920 
    height = 1080
    
    # If cx is around 800, overwrite.
    if abs(cx - 800) < 100:
        width = 1600
        height = 900
    elif abs(cx - 640) < 100:
        width = 1280
        height = 720

    
    # Calculate FOV Horizontal
    fov_rad = 2 * np.arctan(width / (2 * fx))
    fov_deg = np.degrees(fov_rad)

    # --- 3. Convert to CARLA Config Space ---
    
    # A. Position Conversion
    # NuScenes/NavSim Standard: Ego Origin is at the midpoint of the rear axle. (See https://github.com/autonomousvision/navsim/issues/16)
    # CARLA Standard: Ego Origin is at the ground projected from the center of the vehicle (or rear axle depending on vehicle, but Z=0 is ground).
    #
    # PROOF: 
    # 1. The .pkl data has `lidar2ego = [0,0,0]`, implying Lidar Frame == Ego Frame (or data is pre-transformed).
    # 2. However, `cams['CAM_F0']` Z is 1.52m. If Ego was Ground, this is 1.52m high (dashboard level).
    # 3. If Ego is Axle (Standard NuScenes), then Ground is Z = -AxleHeight.
    # 4. Standard Axle Height (Wheel Radius) for autonomous test vehicles (e.g., Renault Zoe/Pacifica) is ~0.30m - 0.35m.
    # 5. Therefore, New Z (Height from Ground) = Old Z (Height from Axle) + AxleHeight.
    
    # Furthermore, we must adjust for the longitudinal origin difference.
    # NuScenes/NavSim Origin: Rear Axle
    # CARLA Origin: Vehicle Center
    # We must shift the camera position backwards by the distance between the center and the rear axle.
    # From team_code/config.py: self.rear_wheel_base = 1.4178275
    
    REAR_WHEEL_BASE_OFFSET = 1.4178275
    AXLE_HEIGHT_OFFSET = 0.35 
    
    pos_carla = nusc_to_carla_vec(pos_nusc)
    pos_carla[0] -= REAR_WHEEL_BASE_OFFSET
    pos_carla[2] += AXLE_HEIGHT_OFFSET

    # B. Rotation Conversion
    # We need to find the rotation R_carlacam_to_carlaego such that:
    # It represents the same physical orientation as R_cam_to_ego_nusc.
    
    # Step B1: Define Transform from CARLA-Cam-Actor Frame (X-Fwd) to OpenCV Frame (Z-Fwd)
    # Z_op = X_cc
    # X_op = Y_cc
    # Y_op = -Z_cc
    R_carlacam_to_opencv = np.array([
        [0, 1, 0],
        [0, 0, -1],
        [1, 0, 0]
    ])

    # Step B2: Get CARLA-Cam-Actor orientation in NuScenes Frame
    R_carlacam_to_ego_nusc = R_cam_to_ego_nusc @ R_carlacam_to_opencv
    
    # Step B3: Convert the basis vectors of this rotation from NuScenes Frame to CARLA Frame
    # (Flip Y component of each column vector)
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
    print(f"    # Generated from {camera_channel}")
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
    parser = argparse.ArgumentParser(description="Extract CARLA Camera Config from NavSim PKL")
    parser.add_argument("file", help="Path to .pkl file")
    parser.add_argument("--channel", default="CAM_F0", help="Camera channel name (default: CAM_F0)")
    args = parser.parse_args()

    data = load_pkl(args.file)
    process_calibration(data, args.channel)

if __name__ == "__main__":
    main()

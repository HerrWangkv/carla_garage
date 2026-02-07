import glob
import os
import subprocess
import sys
import time

def run_scenarios():
    # Configuration
    # Check if a specific routes file is provided via environment variable
    env_routes = os.environ.get("ROUTES")
    if env_routes and os.path.isfile(env_routes):
        print(f"Using single routes file from env: {env_routes}")
        files = [env_routes]
    else:
        root_dir = '/home/kwang/Desktop/carla_garage/data/lb1_split'
        files = glob.glob(os.path.join(root_dir, '**', '*Town10HD*.xml'), recursive=True)
        files.sort()

        start_idx = int(os.environ.get("START_INDEX", 0))
        end_idx = int(os.environ.get("END_INDEX", len(files)))
        print(f"Running subset from index {start_idx} to {end_idx}")
        files = files[start_idx:end_idx]
    
    work_dir = os.getcwd() # Should be /home/kwang/Desktop/carla_garage
    
    # Environment variables are inherited from the shell script calling this
    # We just need to override the ROUTES variable for each call
    
    evaluator_script = "leaderboard/leaderboard/leaderboard_evaluator_local.py"
    
    print(f"Found {len(files)} Town10HD scenario files.")
    
    for i, f in enumerate(files):
        print(f"[{i+1}/{len(files)}] Processing: {f}")
        
        # Construct command
        # We assume the parent shell script has already set up PYTHONPATH, PORT, TM_PORT, etc.
        # But we need to pass the arguments that leaderboard_evaluator_local.py expects
        
        # Read from env or default
        port = os.environ.get("PORT", "2000")
        base_tm_port = int(os.environ.get("TM_PORT", "8000"))
        # Increment TM port for each run to avoid bind error if previous port is in TIME_WAIT
        # We need to make sure we don't pick a port that is too high, and also not one that the previous run is still holding
        # Also, TM port needs to be distinct from World Port (2000)
        tm_port = base_tm_port + (i % 500) * 10 

        agent = "team_code/data_agent.py"
        save_path = os.environ.get("SAVE_PATH", "results")
        checkpoint = f"{save_path}/results.json"
        
        cmd = [
            "python3", evaluator_script,
            f"--port={port}",
            f"--traffic-manager-port={tm_port}",
            f"--routes={f}",
            "--repetitions=1",
            "--track=MAP",
            f"--agent={agent}",
            f"--agent-config={f}",  # Agent config usually points to routes file in this setup
            f"--checkpoint={checkpoint}",
            "--debug=0"
        ]
        
        # We need to run this command. 
        # Since we are running under xvfb in the shell script, we can just run this.
        # However, the shell script calls: xvfb-run ... python ...
        # If we run THIS script under xvfb, then these subprocesses inherit the DISPLAY.
        
        try:
            # Run and wait for it to finish, with a hard timeout of 10 minutes (600s)
            # This prevents the script from hanging indefinitely if the evaluator freezes
            result = subprocess.run(cmd, check=True, timeout=600)
        except subprocess.TimeoutExpired:
            print(f"Scenario {f} timed out after 600s! Killing it.")
        except subprocess.CalledProcessError as e:
            print(f"Error running scenario {f}: {e}")
            # We continue to next scenario even if one fails
        
        print(f"Finished {f}\n")
        
        # Optional: small sleep to let server settle if needed, though evaluator should cleanup
        # Increase sleep time to prevent race conditions between scenarios
        time.sleep(10)

if __name__ == "__main__":
    run_scenarios()

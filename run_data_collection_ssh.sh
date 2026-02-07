#!/bin/bash

# --- 1. 路径设置 ---
export CARLA_ROOT=$(pwd)/carla  # 使用绝对路径，更安全
export WORK_DIR=$(pwd)

# 确保 Python 路径包含必要的库
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/scenario_runner_autopilot
export LEADERBOARD_ROOT=${WORK_DIR}/leaderboard_autopilot
export PYTHONPATH="${CARLA_ROOT}/PythonAPI/carla/":"${SCENARIO_RUNNER_ROOT}":"${LEADERBOARD_ROOT}":${PYTHONPATH}

# --- 2. 数据收集参数 ---
export DATAGEN=1
export SAVE_PATH=${WORK_DIR}/my_10hz_dataset_town10
export TOWN=Town10HD
export REPETITION=0
export DEBUG_CHALLENGE=0

# Accept arguments: 1=RoutesFile, 2=TMPort
if [ -n "$1" ]; then
    export ROUTES="$1"
    echo "Using Routes File: $ROUTES"
else
    # Fallback or error
    echo "Error: No routes file provided."
    exit 1
fi

if [ -n "$2" ]; then
    export TM_PORT="$2"
else
    export TM_PORT=8000
fi

# 端口
export PORT=2000

# --- 3. 启动 CARLA Server ---
echo "Starting CARLA Server..."
pkill -f CarlaUE4
sleep 2

# 定义清理函数
cleanup() {
    echo "Caught signal! Cleaning up..."
    pkill -9 -f CarlaUE4
    pkill -9 -f leaderboard_evaluator
    pkill -f run_town10_split.py
}
trap "cleanup; exit" SIGINT SIGTERM

# 显式使用 Vulkan
unset DISPLAY
nohup ${CARLA_ROOT}/CarlaUE4.sh -port=${PORT} -vulkan -RenderOffScreen -quality-level=Epic > carla_server.log 2>&1 &
CARLA_PID=$!
echo "CARLA PID: $CARLA_PID"

echo "Waiting 25s for CARLA to initialize..."
sleep 25

# --- 4. 启动数据收集 (Client) ---
echo "Starting Data Collection Client for $ROUTES..."

# 使用 append mode (>>) 记录日志
# We run the python script which now respects ROUTES env var
xvfb-run -a -s "-screen 0 2560x1440x24" python3 tools/run_town10_split.py >> data_collection.log 2>&1 &
CLIENT_PID=$!

# Monitor loop
while kill -0 $CLIENT_PID 2> /dev/null; do
    if ! kill -0 $CARLA_PID 2> /dev/null; then
        echo "CARLA Server detected dead! Killing client..."
        kill -9 $CLIENT_PID
        break
    fi
    sleep 5
done

# Wait for client to explicitly finish (in case it was just finishing when loop validated)
wait $CLIENT_PID

echo "Scenario finished."

# --- 5. 清理 ---
echo "Killing CARLA Server..."
kill $CARLA_PID
pkill -9 -f CarlaUE4
sleep 5


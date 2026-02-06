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
export SAVE_PATH=${WORK_DIR}/my_10hz_dataset
export TOWN=Town13 
export REPETITION=0

# 端口
export PORT=2000
export TM_PORT=8000

# 路线文件
# export ROUTES=${WORK_DIR}/leaderboard/data/routes_validation.xml 
# 使用包含 Town12 和 Town13 的多样化路线文件
export ROUTES=${WORK_DIR}/leaderboard/data/routes_diverse.xml

# --- 3. 启动 CARLA Server ---
echo "Starting CARLA Server..."
pkill -f CarlaUE4
sleep 2

# 定义清理函数，确保脚本退出(包括Ctrl+C)时杀死所有CARLA相关进程
cleanup() {
    trap - SIGINT SIGTERM EXIT
    echo "Caught signal! Cleaning up..."
    # 强制杀死所有名为 CarlaUE4 的进程，不仅仅是脚本的 PID
    pkill -9 -f CarlaUE4
    # 同时也清理 Python 客户端
    pkill -9 -f leaderboard_evaluator
    exit
}

# 注册信号捕获：当接收到 SIGINT(Ctrl+C) 或 SIGTERM 时执行 cleanup
trap cleanup SIGINT SIGTERM EXIT

# 显式使用 Vulkan，不依赖 Display。重定向日志以便排查启动问题。
unset DISPLAY
nohup ${CARLA_ROOT}/CarlaUE4.sh -port=${PORT} -vulkan -RenderOffScreen -quality-level=Epic > carla_server.log 2>&1 &
CARLA_PID=$!
echo "CARLA PID: $CARLA_PID. Logging to carla_server.log"

echo "Waiting 20s for CARLA to obtain ports and initialize..."
sleep 20

# --- 4. 启动数据收集 (Client) ---
echo "Starting Data Collection Client..."
echo "Results will be saved to: $SAVE_PATH"

# 关键修改：
# 1. 显式指定 Xvfb 屏幕分辨率与 config.py 中的相机分辨率 (1920x1080) 匹配或更大，防止渲染裁剪或崩溃。
# 2. 将 Python 输出重定向到 data_collection.log 以便 DEBUG。
xvfb-run -a -s "-screen 0 2560x1440x24" python3 leaderboard/leaderboard/leaderboard_evaluator_local.py \
    --port=${PORT} \
    --traffic-manager-port=${TM_PORT} \
    --routes=${ROUTES} \
    --repetitions=1 \
    --track=MAP \
    --agent=team_code/data_agent.py \
    --agent-config=${ROUTES} \
    --checkpoint=${SAVE_PATH}/results.json \
    --debug=0 > data_collection.log 2>&1 &

CLIENT_PID=$!
wait $CLIENT_PID

echo "Data collection finished (or crashed). Check 'data_collection.log' for details."

# --- 5. 清理 ---
# cleanup 函数由 trap EXIT 自动调用，无需重复
# echo "Killing CARLA Server..."
# kill $CARLA_PID

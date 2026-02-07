#!/bin/bash
# record_single_autopilot.sh

# --- 1. 路径与基础设置 ---
export CARLA_ROOT=$(pwd)/carla
export WORK_DIR=$(pwd)
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/scenario_runner_autopilot
export LEADERBOARD_ROOT=${WORK_DIR}/leaderboard_autopilot
export PYTHONPATH="${CARLA_ROOT}/PythonAPI/carla/":"${SCENARIO_RUNNER_ROOT}":"${LEADERBOARD_ROOT}":${PYTHONPATH}

# 核心变量
export SAVE_PATH=${WORK_DIR}/my_sim2real_dataset
mkdir -p ${SAVE_PATH}
export VIDEO_PATH=${WORK_DIR}/my_sim2real_videos
mkdir -p ${VIDEO_PATH}
export REPETITION=0
export DATAGEN=1

# --- 2. 提取信息并执行“存在性检查” ---
if [ -n "$1" ]; then
    export ROUTES="$1"
    
    # 提取 Town 名
    if [[ "$ROUTES" == *"Town12"* ]]; then export TOWN="Town12";
    elif [[ "$ROUTES" == *"Town13"* ]]; then export TOWN="Town13";
    else export TOWN="Town10HD"; fi
    SCENARIO_TYPE=$(basename $(dirname "$ROUTES")) 
    SCENARIO_NAME=$(basename "$ROUTES" .xml)
    TARGET_FOLDER="${SAVE_PATH}/${TOWN}_Rep${REPETITION}_${SCENARIO_TYPE}_${SCENARIO_NAME}"
    
    if [ -d "$TARGET_FOLDER" ]; then
        echo "⏭️  略过：文件夹已存在，不再重复采集。"
        echo "路径: $TARGET_FOLDER"
        exit 0
    fi

    echo "📍 Town: $TOWN | Scenario: ${SCENARIO_TYPE}_${SCENARIO_NAME}"
else
    echo "用法: bash record_single_autopilot.sh <xml_path>"
    exit 1
fi

# --- 3. 启动 Server ---
# 只有当文件夹不存在时，才会执行到这里
echo "🚀 启动 CARLA Server..."
pkill -f CarlaUE4
sleep 2
nohup ${CARLA_ROOT}/CarlaUE4.sh -port=2000 -vulkan -RenderOffScreen -quality-level=Epic > carla_server.log 2>&1 &
CARLA_PID=$!
sleep 25

# --- 4. 运行录制 ---
echo "🎬 开始录制..."
xvfb-run -a -s "-screen 0 2560x1440x24" python3 ${LEADERBOARD_ROOT}/leaderboard/leaderboard_evaluator.py \
    --port=2000 \
    --traffic-manager-port=8000 \
    --routes=${ROUTES} \
    --repetitions=1 \
    --track=MAP \
    --agent=${WORK_DIR}/team_code/data_agent.py \
    --agent-config=${ROUTES} \
    --checkpoint=${SAVE_PATH}/results_single.json \
    --debug=0

# --- 5. 清理 ---
kill $CARLA_PID
pkill -9 -f CarlaUE4
sleep 2

# --- 6. 【融合】自动生成视频 ---
echo "🎥 录制结束，正在生成视频..."
# 调用修改后的 Python 脚本，传入刚刚生成的文件夹路径
python3 tools/create_videos.py --scenario_path "$TARGET_FOLDER" --output "$VIDEO_PATH"

if [ $? -eq 0 ]; then
    echo "✅ 流程全部完成！"
    echo "原始数据: $TARGET_FOLDER"
    echo "视频文件: $VIDEO_PATH/rgb/${TOWN}_Rep${REPETITION}_${SCENARIO_TYPE}_${SCENARIO_NAME}.mp4"
else
    echo "⚠️  场景录制成功，但视频生成失败。"
fi
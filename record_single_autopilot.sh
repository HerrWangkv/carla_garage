#!/bin/bash
# record_single_autopilot.sh

# --- 1. 路径与基础设置 ---
export CARLA_ROOT=$(pwd)/carla
export WORK_DIR=$(pwd)
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/scenario_runner_autopilot
export LEADERBOARD_ROOT=${WORK_DIR}/leaderboard_autopilot
export PYTHONPATH="${CARLA_ROOT}/PythonAPI/carla/":"${SCENARIO_RUNNER_ROOT}":"${LEADERBOARD_ROOT}":${PYTHONPATH}

# 核心变量
export SAVE_PATH=${WORK_DIR}/my_sunny_dataset
mkdir -p ${SAVE_PATH}
export VIDEO_PATH=${WORK_DIR}/my_sunny_videos
mkdir -p ${VIDEO_PATH}
export REPETITION=0

# --- 2. 提取信息并执行“存在性检查” ---
if [ -n "$1" ]; then
    export ROUTES="$1"


    # 通用提取 Town 名和场景名，支持所有 TownXX
    # 从文件名中提取 Town 名（如 Town01、Town02...）
    CONFIG_BASENAME=$(basename "$ROUTES" .xml)
    if [[ "$CONFIG_BASENAME" =~ (Town[0-9A-Za-z]+)_ ]]; then
        TOWN="${BASH_REMATCH[1]}"
    else
        # 若未匹配，回退到路径中查找
        if [[ "$ROUTES" =~ (Town[0-9A-Za-z]+) ]]; then
            TOWN="${BASH_REMATCH[1]}"
        else
            TOWN="UnknownTown"
        fi
    fi
    export TOWN  # 确保 TOWN 变量对子进程可见
    # 场景类型为上级目录名
    SCENARIO_TYPE=$(basename $(dirname "$ROUTES"))


    # 只取 config 文件名中的最后一个下划线后的数字作为 index（更健壮，确保为数字）
    SCENARIO_INDEX=$(echo "$CONFIG_BASENAME" | grep -oE '[0-9]+$')
    TARGET_FOLDER="${SAVE_PATH}/${TOWN}_Rep${REPETITION}_${SCENARIO_TYPE}_${SCENARIO_INDEX}"

    # Debug 输出
    echo "[DEBUG] CONFIG_BASENAME: $CONFIG_BASENAME"
    echo "[DEBUG] TOWN: $TOWN"
    echo "[DEBUG] SCENARIO_TYPE: $SCENARIO_TYPE"
    echo "[DEBUG] SCENARIO_INDEX: $SCENARIO_INDEX"
    echo "[DEBUG] TARGET_FOLDER: $TARGET_FOLDER"

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
export DATAGEN=1
timeout 600 xvfb-run -a -s "-screen 0 2560x1440x24" python3 ${LEADERBOARD_ROOT}/leaderboard/leaderboard_evaluator.py \
    --port=2000 \
    --traffic-manager-port=8000 \
    --routes=${ROUTES} \
    --repetitions=1 \
    --track=MAP \
    --agent=${WORK_DIR}/team_code/data_agent.py \
    --agent-config=${ROUTES} \
    --checkpoint=${SAVE_PATH}/results_single.json \
    --debug=0

EXIT_STATUS=$?

if [ $EXIT_STATUS -eq 124 ]; then
    echo "⚠️  TIMEOUT REACHED: The simulation took longer than 10 minutes and was killed."
elif [ $EXIT_STATUS -ne 0 ]; then
    echo "⚠️  Simulation failed with error code $EXIT_STATUS."
fi

# --- 5. 清理 ---
kill $CARLA_PID
pkill -9 -f CarlaUE4
sleep 2

# --- 6. 【融合】自动生成视频 ---
echo "🎥 录制结束，正在生成视频..."
# 调用修改后的 Python 脚本，传入刚刚生成的文件夹路径
python3 tools/create_videos.py --scenario_path "$TARGET_FOLDER" --output "$VIDEO_PATH"

VIDEO_FILENAME="${TOWN}_Rep${REPETITION}_${SCENARIO_TYPE}_${SCENARIO_INDEX}.mp4"
if [ $? -eq 0 ]; then
    echo "✅ 流程全部完成！"
    echo "原始数据: $TARGET_FOLDER"
    echo "视频文件: $VIDEO_PATH/rgb/$VIDEO_FILENAME"
else
    echo "⚠️  场景录制成功，但视频生成失败。"
fi

#!/bin/bash

# 1. 创建总日志目录
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# 定义父目录列表
PARENT_DIRS=("data/50x38_Town12" "data/50x36_Town13")

echo "🚀 开始批量运行任务，日志将存放在 ./$LOG_DIR 目录下..."

for parent in "${PARENT_DIRS[@]}"; do
    if [ ! -d "$parent" ]; then
        echo "⚠️  跳过不存在的目录: $parent"
        continue
    fi

    # 提取父目录名用于日志前缀 (如 50x38_Town12)
    parent_name=$(basename "$parent")

    for scenario_dir in "$parent"/*; do
        if [ -d "$scenario_dir" ]; then
            xml_files=("$scenario_dir"/*.xml)

            if [ -e "${xml_files[0]}" ]; then
                first_xml="${xml_files[0]}"
                
                # 2. 生成唯一的日志文件名
                scenario_name=$(basename "$scenario_dir")
                log_file="${LOG_DIR}/${parent_name}_${scenario_name}.log"

                echo "------------------------------------------"
                echo "运行场景: $parent_name / $scenario_name"
                echo "日志文件: $log_file"

                # 3. 执行脚本并重定向所有输出 (标准输出 + 错误输出) 到日志文件
                # 使用 &> 将 stdout 和 stderr 同时存入日志
                bash record_single_autopilot.sh "$first_xml" &> "$log_file"
                
                # 如果你想在屏幕上看到进度同时保存日志，可以用下面的命令代替上面那行：
                # bash record_single_autopilot.sh "$first_xml" 2>&1 | tee "$log_file"

                echo "✅ 已完成，退出码: $?"
            fi
        fi
    done
done

echo "=========================================="
echo "🎉 所有任务已处理完毕！请在 ./$LOG_DIR 查看详细日志。"
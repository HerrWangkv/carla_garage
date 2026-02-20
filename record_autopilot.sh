#!/bin/bash

# 1. 创建总日志目录
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo "🚀 开始批量运行任务，日志将存放在 ./$LOG_DIR 目录下..."

# 遍历 data/lb1_split 下所有 scenario 类型
for scenario_type_dir in data/lb1_split/*; do
    if [ -d "$scenario_type_dir" ]; then
        scenario_type=$(basename "$scenario_type_dir")

        echo "=========================================="
        echo "处理 Scenario 类型: $scenario_type"

        # 找到所有 Town*.xml
        mapfile -t all_xmls < <(find "$scenario_type_dir" -maxdepth 1 -name 'Town*.xml' | sort -V)

        # 提取唯一的 Town 前缀（如 Town01, Town02）
        towns=$(printf "%s\n" "${all_xmls[@]}" \
            | sed -E 's#.*/(Town[0-9]+).*#\1#' \
            | sort -u)

        # 对每个 Town 取前 2 个 XML
        for town in $towns; do
            mapfile -t town_xmls < <(
                printf "%s\n" "${all_xmls[@]}" \
                | grep "/$town" \
                | sort -V \
                | head -n 2
            )

            for xml_file in "${town_xmls[@]}"; do
                xml_base=$(basename "$xml_file" .xml)
                log_file="${LOG_DIR}/${scenario_type}_${xml_base}.log"

                echo "------------------------------------------"
                echo "运行场景: $scenario_type / $xml_base"
                echo "日志文件: $log_file"

                bash record_single_autopilot.sh "$xml_file" &> "$log_file"
                echo "✅ 已完成，退出码: $?"
            done
        done
    fi
done

echo "=========================================="
echo "🎉 所有任务已处理完毕！请在 ./$LOG_DIR 查看详细日志。"

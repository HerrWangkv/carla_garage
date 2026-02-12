#!/bin/bash

# 1. Setup
LOG_DIR="logs_recovery"
mkdir -p "$LOG_DIR"
DATA_DIR="my_sunny_dataset"
PARENT_DIRS=("data/50x38_Town12" "data/50x36_Town13")

echo "🔍 Scanning $DATA_DIR for scenarios with missing clips..."

# 2. Get a list of unique scenario bases
# Example: Town12_Rep0_AccidentTwoWays_26_0 -> Base: Town12_Rep0_AccidentTwoWays_26

for parent in "${PARENT_DIRS[@]}"; do
    if [ ! -d "$parent" ]; then
        echo "⚠️  跳过不存在的目录: $parent"
        continue
    fi
    parent_name=$(basename "$parent")

    for scenario_dir in "$parent"/*; do
        if [ -d "$scenario_dir" ]; then
            xml_files=("$scenario_dir"/*.xml)
            scenario_type=$(basename "$scenario_dir")
            # 提取 Town 名 (从 parent 路径中提取，逻辑与 record 脚本一致)
            if [[ "$parent" == *"Town12"* ]]; then town="Town12";
            elif [[ "$parent" == *"Town13"* ]]; then town="Town13";
            else town="Town10HD"; fi

            # 构造在 DATA_DIR 中搜索的通配符前缀
            # 匹配格式: Town12_Rep0_AccidentTwoWays_26_*
            search_pattern="${town}_Rep0_${scenario_type}_*"
            
            # 统计现有的 clip 数量
            clip_count=$(ls -1d ${DATA_DIR}/${search_pattern} 2>/dev/null | wc -l)

            if [ "$clip_count" -lt 2 ]; then
                # 获取该场景下的所有 XML
                mapfile -t xml_files < <(find "$scenario_dir" -maxdepth 1 -name '*.xml' | sort -V)
                
                if [ ${#xml_files[@]} -gt 0 ]; then
                    # 💡 获取数组中的最后一个 XML 文件
                    last_xml="${xml_files[-1]}"
                    
                    xml_name=$(basename "$last_xml" .xml)
                    log_file="${LOG_DIR}/${town}_${scenario_type}_${xml_name}_recovery.log"

                    echo "------------------------------------------"
                    echo "检测到缺失: $scenario_type (当前仅有 $clip_count 个)"
                    echo "准备运行最后一个配置: $(basename "$last_xml")"

                    # 执行录制脚本
                    # 注意：record_single_autopilot.sh 内部会自动检查对应的 _X 文件夹是否存在
                    bash record_single_autopilot.sh "$last_xml" &> "$log_file"
                    
                    echo "✅ 完成，退出码: $?"
                else
                    echo "⏭️  跳过 $scenario_type: 文件夹内没找到 XML 文件。"
                fi
            fi
        fi
    done
done

echo "=========================================="
echo "🎉 扫描与补充录制任务已结束。"
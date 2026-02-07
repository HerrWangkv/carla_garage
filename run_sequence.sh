#!/bin/bash
# run_sequence.sh

# Find all relevant XML files
XML_FILES=$(find ${PWD}/data/lb1_split -name "*Town10HD*.xml" | sort)
COUNT=0
TOTAL=$(echo "$XML_FILES" | wc -l)

# Log file to track completed scenarios
COMPLETED_LOG="completed_scenarios.txt"
touch "$COMPLETED_LOG"

echo "Found $TOTAL scenarios to process."

for xml_file in $XML_FILES
do
    BASENAME=$(basename "$xml_file")
    COUNT=$((COUNT+1))
    
    # 1. Fast Check: Is it already in the log file?
    if grep -Fxq "$BASENAME" "$COMPLETED_LOG"; then
        echo "Skipping Scenario $COUNT/$TOTAL: $BASENAME (Found in $COMPLETED_LOG)"
        continue
    fi

    # Extract info for Disk Check
    # Extract Route ID
    ROUTE_ID=$(grep 'route id=' "$xml_file" | cut -d'"' -f2)
    
    # Extract Scenario Type (folder name) e.g., ControlLoss, DynamicObjectCrossing
    SCENARIO_TYPE=$(basename $(dirname "$xml_file"))
    SCENARIO_CONFIG=$(basename "$xml_file" .xml)
    
    DATASET_DIR="my_10hz_dataset_town10"
    
    # 2. Disk Check: Is the result folder on disk?
    # Match pattern: *{ScenarioConfig}*{ScenarioType}*route{RouteID}*
    # We include SCENARIO_CONFIG to ensure we match the exact XML file's output,
    # distinguishing e.g. Town10HD_lr_0 vs Town10HD_rl_0 which both have route id 0.
    EXISTING_MATCHES=$(find "${DATASET_DIR}" -maxdepth 2 -name "results.json.gz" -path "*${SCENARIO_CONFIG}_*_${SCENARIO_TYPE}_*route${ROUTE_ID}_*" 2>/dev/null)
    
    # Double check avoiding partial matches (e.g. route1 vs route10) manually
    # Because find -path with wildcards depends on exact folder structure
    VALID_EXISTING=""
    if [ -n "$EXISTING_MATCHES" ]; then
        for match in $EXISTING_MATCHES; do
            # Check if match strictly contains route${ROUTE_ID}_
            if [[ "$match" == *"route${ROUTE_ID}_"* ]]; then
                VALID_EXISTING="$match"
                break
            fi
        done
    fi
    
    if [ -n "$VALID_EXISTING" ]; then
        echo ""
        echo "=================================================="
        echo "Skipping Scenario $COUNT/$TOTAL: $BASENAME"
        echo "Reason: Found existing results on disk."
        echo "Action: Adding to $COMPLETED_LOG and skipping."
        echo "=================================================="
        echo "$BASENAME" >> "$COMPLETED_LOG"
        continue
    fi

    echo ""
    echo "=================================================="
    echo "Processing Scenario $COUNT/$TOTAL: $BASENAME"
    echo "=================================================="
    
    # Calculate a unique TM_PORT to be extra safe against TIME_WAIT (though restart should clear it)
    # We cycle ports just in case OS holds onto them briefly
    # Cycle between 8000 and 8500
    TM_PORT=$((8000 + (COUNT % 50) * 10))
    
    bash run_data_collection_ssh.sh "$xml_file" "$TM_PORT"
    
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        echo "Scenario failed with exit code $EXIT_CODE"
    else
        # 3. Success: Log it and Generate Video
        echo "Scenario finished successfully. Adding to log."
        echo "$BASENAME" >> "$COMPLETED_LOG"
        
        # Determine the name of the folder that was just created
        # We know the pattern is: Town10HD_Rep0_{SCENARIO_TYPE}*route{ROUTE_ID}*
        # We need to find the specific folder that matches this pattern and has the latest timestamp
        CREATED_FOLDER=$(find "${DATASET_DIR}" -maxdepth 1 -type d -name "*${SCENARIO_TYPE}*route${ROUTE_ID}*" -printf "%T@ %p\n" | sort -n | tail -1 | cut -d' ' -f2)
        
        if [ -n "$CREATED_FOLDER" ]; then
            SEQ_NAME=$(basename "$CREATED_FOLDER")
            echo "Generating video for: $SEQ_NAME"
            python3 tools/create_videos.py --source_dir "${DATASET_DIR}" --seq_name "${SEQ_NAME}"
        fi
    fi
    
    # Optional: Backup logs for this run
    mkdir -p logs
    mv carla_server.log logs/carla_server_$(basename $xml_file).log
    mv data_collection.log logs/data_collection_$(basename $xml_file).log
    
    sleep 2
done

echo "All scenarios finished."

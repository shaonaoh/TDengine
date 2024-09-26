#!/bin/bash

pgrep taosd || taosd >> /dev/null 2>&1 &
pgrep taosadapter || taosadapter >> /dev/null 2>&1 &

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'


TEST_PATH="../../debug/build/bin"

LOG_FILE="docs-c-test-out.log"

> $LOG_FILE

declare -a TEST_EXES=(
    "docs_connect_example"
    "docs_create_db_demo"
    "docs_insert_data_demo"
    "docs_query_data_demo"
    "docs_with_reqid_demo"
    "docs_stmt_insert_demo"
    "docs_tmq_demo"
    "docs_sml_insert_demo"
)

totalCases=0
totalFailed=0
totalSuccess=0

for TEST_EXE in "${TEST_EXES[@]}"; do
    echo "Executing $TEST_EXE..."
    $TEST_PATH/$TEST_EXE >> $LOG_FILE 2>&1
    
    RESULT=$?
    
    if [ "$RESULT" -eq 0 ]; then
        totalSuccess=$((totalSuccess + 1))
        echo "[$GREEN OK $NC] $TEST_EXE executed successfully."
    else
        totalFailed=$((totalFailed + 1))
        echo "[$RED FAILED $NC] $TEST_EXE exited with code $RESULT."
    fi
    
    totalCases=$((totalCases + 1))
done

tail -n 40 $LOG_FILE

echo -e "\nTotal number of cases executed: $totalCases"
if [ "$totalSuccess" -gt "0" ]; then
  echo -e "\n${GREEN} ### Total $totalSuccess C case(s) succeed! ### ${NC}"
fi

if [ "$totalFailed" -ne "0" ]; then
  echo -e "\n${RED} ### Total $totalFailed C case(s) failed! ### ${NC}"
  exit 1
fi

echo "All tests completed."
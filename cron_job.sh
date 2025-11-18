#!/bin/bash

# === CONFIG ===
PROJECT_DIR="/Users/omjagtap/Documents/projects/RAG-Email-Sorting"
PYTHON_EXE="/opt/anaconda3/envs/RagEmailSorting/bin/python"

# Logs
LOG_OUT="$PROJECT_DIR/rag_report.out.log"
LOG_ERR="$PROJECT_DIR/rag_report.err.log"

# === SCRIPT ===
cd "$PROJECT_DIR" || exit 1

echo "==== Run at $(date) ====" >> "$LOG_OUT"

# Optional: clear previous run for a fresh daily pipeline
# Comment these out if you don't want to reset databases every day
rm -f "$PROJECT_DIR/my_emails.db"
rm -rf "$PROJECT_DIR/email_vector_db"

# Phase 1 – fetch emails
"$PYTHON_EXE" gmail_fetcher.py       >> "$LOG_OUT" 2>> "$LOG_ERR"

# Phase 2 – indexing / embeddings
"$PYTHON_EXE" indexing.py            >> "$LOG_OUT" 2>> "$LOG_ERR"

# Phase 3 – generate report
"$PYTHON_EXE" report_generation.py   >> "$LOG_OUT" 2>> "$LOG_ERR"

# Phase 4 – send report
"$PYTHON_EXE" send_report.py         >> "$LOG_OUT" 2>> "$LOG_ERR"

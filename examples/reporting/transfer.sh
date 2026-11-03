#!/usr/bin/env bash
set -euo pipefail
REPORT_DIR="${REPORT_DIR:-/tmp}"
REPORT_BUCKET="${REPORT_BUCKET:-s3://risk-reports/daily}"
aws s3 cp "${REPORT_DIR}/risk_summary.csv" "${REPORT_BUCKET}/risk_summary.csv"

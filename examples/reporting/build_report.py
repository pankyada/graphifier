import os
import pandas as pd
from sqlalchemy import create_engine

schema = os.getenv("RISK_SCHEMA", "reporting")
summary_table = f"{schema}.risk_summary"
engine = create_engine(os.getenv("REPORT_DB_URL"))
query = f"select score_band, customer_count, mean_risk from {summary_table}"
report = pd.read_sql(query, engine)
report.to_csv(os.path.join(os.getenv("REPORT_DIR", "/tmp"), "risk_summary.csv"), index=False)

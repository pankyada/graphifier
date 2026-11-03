# Example repositories

The two folders model separate repositories. Both use `RISK_SCORE_TABLE` as a
symbolic handoff: SAS sets it to `risk.risk_scored` and writes `&RISK_SCORE_TABLE`,
while the reporting SQL reads `${RISK_SCORE_TABLE}`. A graph consumer can match
the symbol names and SAS default without treating them as proof of physical
runtime connectivity. `RISK_SCHEMA` and `REPORT_BUCKET` demonstrate additional
environment and shell symbols.

- `sas-risk/` trains and scores a logistic model, then writes a scored table.
- `reporting/` summarizes scored data in SQL, reads that result in Python, and
  transfers a CSV report through a shell script.

The samples intentionally use simple, inspectable syntax. Static extraction
cannot prove credentials, runtime environment overrides, macro expansion,
runtime branches, or whether the systems point to the same physical data.

Relationship direction follows data flow. In particular, `DERIVES_FROM` links
an upstream input to a downstream output, while `INPUT_TO` links a dataset to a
transformation that consumes it.

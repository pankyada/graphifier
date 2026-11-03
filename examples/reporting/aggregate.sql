create table reporting.risk_summary as
select score_band, count(*) as customer_count, avg(predicted_default) as mean_risk
from ${RISK_SCORE_TABLE}
group by score_band;

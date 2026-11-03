%let RISK_LIB = analytics;
%let RISK_SCORE_TABLE = risk.risk_scored;
libname risk "&RISK_LIB";

proc sql;
  create table risk.risk_training as
  select customer_id, balance, late_count, defaulted
  from warehouse.credit_accounts
  where active = 1;
quit;

data risk.risk_training_model;
  set risk.risk_training;
  utilization = balance / 10000;
run;

proc logistic data=risk.risk_training_model;
  model defaulted = balance late_count utilization;
  score data=risk.risk_training_model out=&RISK_SCORE_TABLE;
run;

# project: demand-forecast (synthetic)
import os, json
from airflow import DAG
from airflow.operators.python import PythonOperator

with DAG('daily_load', schedule='0 3 * * *', catchup=False) as dag:
    extract >> load >> validate

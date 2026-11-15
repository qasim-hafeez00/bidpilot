# project: tableau-marketing (synthetic)
import os, json
from google.cloud import bigquery
client = bigquery.Client()
client.load_table_from_dataframe(df, 'analytics.ad_spend').result()

# project: prompt-eval (synthetic)
import os, json
import pandas as pd
df = pd.read_parquet('orders.parquet')
weekly = df.groupby(pd.Grouper(key='ts', freq='W'))['amount'].sum()

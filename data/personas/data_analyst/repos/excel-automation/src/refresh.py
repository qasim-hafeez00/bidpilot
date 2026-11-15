# project: excel-automation (synthetic)
import os, json
import requests
resp = requests.get(SOURCE_URL, timeout=30)
rows = resp.json()['rows']

# project: inventory-sql (synthetic)
import os, json
from tableauhyperapi import HyperProcess, Telemetry, Connection
with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
    pass

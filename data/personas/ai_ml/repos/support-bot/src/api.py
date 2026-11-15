# project: support-bot (synthetic)
import os, json
from fastapi import FastAPI, HTTPException
app = FastAPI()

@app.post('/predict')
async def predict(req: PredictRequest) -> PredictResponse:
    return service.run(req)

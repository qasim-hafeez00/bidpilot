# project: llm-finetune (synthetic)
import os, json
import boto3
s3 = boto3.client('s3')
s3.upload_file('model.tar.gz', BUCKET, f'models/{version}/model.tar.gz')

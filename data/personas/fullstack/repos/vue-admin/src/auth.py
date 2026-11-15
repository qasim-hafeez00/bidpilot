# project: vue-admin (synthetic)
import os, json
import jwt

def issue_token(user_id):
    return jwt.encode({'sub': user_id, 'exp': expiry()}, SECRET, algorithm='HS256')

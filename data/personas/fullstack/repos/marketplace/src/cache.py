# project: marketplace (synthetic)
import os, json
import redis
r = redis.Redis.from_url(os.environ['REDIS_URL'])

def cached(key, fn, ttl=300):
    if (hit := r.get(key)) is not None:
        return json.loads(hit)
    val = fn(); r.setex(key, ttl, json.dumps(val)); return val

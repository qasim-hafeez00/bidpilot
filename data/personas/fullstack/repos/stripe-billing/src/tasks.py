# project: stripe-billing (synthetic)
import os, json
from celery import shared_task

@shared_task(bind=True, max_retries=3, acks_late=True)
def process_batch(self, batch_id):
    try:
        run(batch_id)
    except TransientError as exc:
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

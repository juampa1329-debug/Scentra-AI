import os
import time

from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.ingest import process_due_webhook_events
from app_saas.workers.meta_tokens import process_due_meta_token_refreshes
from app_saas.workers.remarketing import process_due_remarketing_flows
from app_saas.workers.triggers import process_due_scheduled_trigger_messages
from app_saas.ai_agent.service import process_due_ai_replies


def main() -> None:
    worker_name = os.getenv("SAAS_WORKER_NAME", "worker-generic")
    interval_sec = int(os.getenv("SAAS_WORKER_IDLE_SEC", "5") or "5")
    batch_size = int(os.getenv("SAAS_WORKER_BATCH_SIZE", "25") or "25")
    print(f"[{worker_name}] starting")
    while True:
        ingest_result = process_due_webhook_events(limit=batch_size)
        trigger_result = process_due_scheduled_trigger_messages(limit=batch_size)
        remarketing_result = process_due_remarketing_flows(limit=batch_size)
        ai_result = process_due_ai_replies(limit=batch_size)
        outbound_result = process_due_outbound_messages(limit=batch_size)
        meta_tokens_result = process_due_meta_token_refreshes()
        print(
            f"[{worker_name}] tick ingest={ingest_result} triggers={trigger_result} "
            f"remarketing={remarketing_result} ai={ai_result} outbound={outbound_result} "
            f"meta_tokens={meta_tokens_result}"
        )
        time.sleep(interval_sec)


if __name__ == "__main__":
    main()

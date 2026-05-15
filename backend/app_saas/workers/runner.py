import os
import time

from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.ingest import process_due_webhook_events
from app_saas.workers.remarketing import process_due_remarketing_flows
from app_saas.workers.triggers import process_due_scheduled_trigger_messages


def main() -> None:
    worker_name = os.getenv("SAAS_WORKER_NAME", "worker-generic")
    interval_sec = int(os.getenv("SAAS_WORKER_IDLE_SEC", "5") or "5")
    batch_size = int(os.getenv("SAAS_WORKER_BATCH_SIZE", "25") or "25")
    print(f"[{worker_name}] starting")
    while True:
        ingest_result = process_due_webhook_events(limit=batch_size)
        trigger_result = process_due_scheduled_trigger_messages(limit=batch_size)
        remarketing_result = process_due_remarketing_flows(limit=batch_size)
        outbound_result = process_due_outbound_messages(limit=batch_size)
        print(
            f"[{worker_name}] tick ingest={ingest_result} triggers={trigger_result} "
            f"remarketing={remarketing_result} outbound={outbound_result}"
        )
        time.sleep(interval_sec)


if __name__ == "__main__":
    main()

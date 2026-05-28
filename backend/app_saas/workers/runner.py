import os
import time

from app_saas.agents.orchestrator import process_due_agent_orchestration
from app_saas.ai_agent.service import process_due_ai_replies
from app_saas.db import db_session
from app_saas.observability.service import record_worker_heartbeat
from app_saas.workers.billing import process_billing_lifecycle
from app_saas.workers.dispatch import process_due_outbound_messages
from app_saas.workers.ingest import process_due_webhook_events
from app_saas.workers.intelligence import process_due_intelligence
from app_saas.workers.meta_tokens import process_due_meta_token_refreshes
from app_saas.workers.remarketing import process_due_remarketing_flows
from app_saas.workers.reliability import process_due_reliability
from app_saas.workers.triggers import process_due_scheduled_trigger_messages


def main() -> None:
    worker_name = os.getenv("SAAS_WORKER_NAME", "worker-generic")
    interval_sec = int(os.getenv("SAAS_WORKER_IDLE_SEC", "5") or "5")
    batch_size = int(os.getenv("SAAS_WORKER_BATCH_SIZE", "25") or "25")
    print(f"[{worker_name}] starting")
    with db_session() as conn:
        record_worker_heartbeat(conn, worker_name=worker_name, worker_type="standalone", status="ok", started=True)
    while True:
        try:
            ingest_result = process_due_webhook_events(limit=batch_size)
            trigger_result = process_due_scheduled_trigger_messages(limit=batch_size)
            remarketing_result = process_due_remarketing_flows(limit=batch_size)
            ai_result = process_due_ai_replies(limit=batch_size)
            orchestrator_result = process_due_agent_orchestration(limit=batch_size)
            outbound_result = process_due_outbound_messages(limit=batch_size)
            billing_result = process_billing_lifecycle()
            intelligence_result = process_due_intelligence(limit=batch_size)
            reliability_result = process_due_reliability()
            meta_tokens_result = process_due_meta_token_refreshes()
            result = {
                "ingest": ingest_result,
                "triggers": trigger_result,
                "remarketing": remarketing_result,
                "ai": ai_result,
                "orchestrator": orchestrator_result,
                "outbound": outbound_result,
                "billing": billing_result,
                "intelligence": intelligence_result,
                "reliability": reliability_result,
                "meta_tokens": meta_tokens_result,
            }
            with db_session() as conn:
                record_worker_heartbeat(conn, worker_name=worker_name, worker_type="standalone", status="ok", result=result)
            print(
                f"[{worker_name}] tick ingest={ingest_result} triggers={trigger_result} "
                f"remarketing={remarketing_result} ai={ai_result} orchestrator={orchestrator_result} outbound={outbound_result} "
                f"billing={billing_result} intelligence={intelligence_result} reliability={reliability_result} meta_tokens={meta_tokens_result}"
            )
        except Exception as exc:
            with db_session() as conn:
                record_worker_heartbeat(conn, worker_name=worker_name, worker_type="standalone", status="error", error=str(exc)[:1200])
            print(f"[{worker_name}] error {str(exc)[:500]}", flush=True)
        time.sleep(interval_sec)


if __name__ == "__main__":
    main()

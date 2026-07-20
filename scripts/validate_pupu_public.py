#!/usr/bin/env python3
import asyncio
import time
from datetime import UTC, datetime

import httpx

from pupu_assistant.config import Settings
from pupu_assistant.integrations.pupu.client import PupuHttpClient
from pupu_assistant.integrations.pupu.models import SignatureMode
from pupu_assistant.integrations.pupu.signature import (
    ExplicitNoSignatureService,
    RoutingPupuSignatureService,
    UnavailableProtectedSignatureService,
)
from pupu_assistant.integrations.pupu.system import PupuSystemService
from pupu_assistant.validation.evidence import (
    LiveValidationEvidence,
    evidence_shape,
    write_evidence,
)

PUBLIC_PATH = "/client/base/data"


async def validate() -> int:
    settings = Settings()
    public_paths = frozenset({PUBLIC_PATH})
    signature_service = RoutingPupuSignatureService(
        public_service=ExplicitNoSignatureService(public_paths=public_paths),
        protected_service=UnavailableProtectedSignatureService(),
        public_paths=public_paths,
    )
    raw_client = httpx.AsyncClient(
        timeout=settings.pupu_timeout_seconds,
        verify=settings.pupu_verify_tls,
        headers={"user-agent": "pupu-assistant/0.1"},
    )
    client = PupuHttpClient(
        base_url=settings.pupu_base_url,
        signature_service=signature_service,
        app_version=settings.pupu_app_version,
        os_type=settings.pupu_os_type,
        http_client=raw_client,
        timestamp_ms=lambda: int(time.time() * 1000),
        max_read_attempts=4,
    )
    evidence_target = settings.pupu_evidence_path / "public-server-time.json"

    try:
        server_time = await PupuSystemService(client).get_server_time()
    except Exception as error:
        write_evidence(
            evidence_target,
            LiveValidationEvidence(
                endpoint=PUBLIC_PATH,
                signature_mode=SignatureMode.NONE,
                tested_at=datetime.now(UTC),
                http_status=None,
                pupu_errcode=None,
                request_result="failed",
                response_shape={},
                verified_in_mobile_app=False,
                failure_reason=type(error).__name__,
            ),
        )
        raise
    else:
        write_evidence(
            evidence_target,
            LiveValidationEvidence(
                endpoint=PUBLIC_PATH,
                signature_mode=SignatureMode.NONE,
                tested_at=datetime.now(UTC),
                http_status=200,
                pupu_errcode=0,
                request_result="passed",
                response_shape=evidence_shape(
                    {"errcode": 0, "data": {"server_time": server_time}}
                ),
                verified_in_mobile_app=False,
                failure_reason=None,
            ),
        )
        print(
            f"PASS endpoint={PUBLIC_PATH} signature_mode=none server_time={server_time}"
        )
        return server_time
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(validate())

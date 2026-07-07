import logging
from src.config import settings

logger = logging.getLogger(__name__)

class TwilioClient:
    def __init__(self):
        self.account_sid = getattr(settings, "twilio_account_sid", "mock_sid")
        self.auth_token = getattr(settings, "twilio_auth_token", "mock_token")
        self.from_phone = getattr(settings, "twilio_phone_number", "+10000000000")

    async def make_outbound_call(self, to_phone: str, profiling_run_id: str) -> dict:
        """
        Inicia una llamada saliente usando Twilio, con Answering Machine Detection (AMD) habilitado.
        Como estamos en modo simulación, solo imprimimos un log y retornamos un Call SID falso.
        """
        logger.info(f"[SIMULATED TWILIO] Llamando a {to_phone} para el ProfilingRun {profiling_run_id}")
        
        # Simula una llamada encolada exitosamente
        return {
            "status": "queued",
            "sid": f"CA_mock_{profiling_run_id}",
            "direction": "outbound-api"
        }

twilio_client = TwilioClient()

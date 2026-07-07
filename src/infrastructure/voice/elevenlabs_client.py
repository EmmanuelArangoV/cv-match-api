import logging
from src.config import settings

logger = logging.getLogger(__name__)

class ElevenLabsClient:
    def __init__(self):
        self.api_key = getattr(settings, "elevenlabs_api_key", "mock_key")
        self.agent_id = getattr(settings, "elevenlabs_agent_id", "mock_agent")

    async def get_transcription(self, call_id: str) -> str:
        """
        Obtiene la transcripción de la llamada desde ElevenLabs.
        Como estamos en modo simulación, retornaremos una transcripción simulada.
        """
        logger.info(f"[SIMULATED ELEVENLABS] Fetching transcription for {call_id}")
        return "Candidato: Hola, sí, estoy interesado en el puesto. Mi mayor fortaleza es Python."

elevenlabs_client = ElevenLabsClient()

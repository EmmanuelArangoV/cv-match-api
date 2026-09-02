"""Sincroniza el catálogo completo de roles de Match con Órbita."""

import asyncio

from src.application.auth.orbita_roles import ORBITA_ROLE_CATALOG
from src.config import settings
from src.infrastructure.auth.orbita_sso import OrbitaSsoClient, OrbitaSsoConfig


async def main() -> None:
    client = OrbitaSsoClient(
        OrbitaSsoConfig(
            base_url=settings.orbita_sso_base_url,
            client_id=settings.orbita_sso_client_id,
            client_secret=settings.orbita_sso_client_secret,
            redirect_uri=settings.orbita_sso_redirect_uri,
            require_https=settings.app_env not in {"development", "test"},
        )
    )
    await client.sync_role_catalog(ORBITA_ROLE_CATALOG)
    keys = ", ".join(role["key"] for role in ORBITA_ROLE_CATALOG)
    print(f"Catálogo SSO sincronizado: {keys}")


if __name__ == "__main__":
    asyncio.run(main())

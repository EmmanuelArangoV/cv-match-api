import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from src.infrastructure.auth.orbita_sso import (
    OrbitaSsoClient,
    OrbitaSsoConfig,
    OrbitaSsoConfigurationError,
    OrbitaSsoRejectedError,
)


def configured_client() -> OrbitaSsoClient:
    return OrbitaSsoClient(
        OrbitaSsoConfig(
            base_url="https://orbita.example",
            client_id="match-staging",
            client_secret="server-secret",
            redirect_uri="https://match.example/auth/orbita/callback",
        )
    )


def token_fixture(*, audience="match-staging") -> tuple[str, dict]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk["kid"] = "orbita-test-key"
    token = jwt.encode(
        {
            "sub": "20000000-0000-4000-8000-000000000001",
            "email": "user@riwi.io",
            "name": "User Test",
            "roles": ["recruiter"],
            "jti": "token-id",
            "aud": audience,
            "exp": int(time.time()) + 300,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "orbita-test-key"},
    )
    return token, public_jwk


@pytest.mark.asyncio
async def test_verify_orbita_token_requires_expected_audience_and_claims():
    client = configured_client()
    token, jwk = token_fixture()
    client._discovery = {
        "token_signing_alg_values_supported": ["RS256"],
    }
    client._jwks = {"keys": [jwk]}

    identity = await client.verify_token(token)

    assert identity.email == "user@riwi.io"
    assert identity.roles == ("recruiter",)


@pytest.mark.asyncio
async def test_verify_orbita_token_rejects_wrong_audience():
    client = configured_client()
    token, jwk = token_fixture(audience="another-app")
    client._discovery = {
        "token_signing_alg_values_supported": ["RS256"],
    }
    client._jwks = {"keys": [jwk]}

    with pytest.raises(OrbitaSsoRejectedError, match="no es válido"):
        await client.verify_token(token)


def test_orbita_config_requires_https_in_production():
    with pytest.raises(OrbitaSsoConfigurationError, match="HTTPS"):
        OrbitaSsoClient(
            OrbitaSsoConfig(
                base_url="http://orbita.example",
                client_id="match-staging",
                client_secret="server-secret",
                redirect_uri="http://match.example/auth/orbita/callback",
            )
        )

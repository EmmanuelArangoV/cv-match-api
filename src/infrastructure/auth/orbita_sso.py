"""Adaptador confidencial para el contrato SSO v1 de Órbita."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK


class OrbitaSsoConfigurationError(Exception):
    pass


class OrbitaSsoUnavailableError(Exception):
    pass


class OrbitaSsoRejectedError(Exception):
    pass


@dataclass(frozen=True)
class OrbitaSsoConfig:
    base_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    require_https: bool = True

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("ORBITA_SSO_BASE_URL", self.base_url),
                ("ORBITA_SSO_CLIENT_ID", self.client_id),
                ("ORBITA_SSO_CLIENT_SECRET", self.client_secret),
                ("ORBITA_SSO_REDIRECT_URI", self.redirect_uri),
            )
            if not value
        ]
        if missing:
            raise OrbitaSsoConfigurationError(
                f"Configuración SSO incompleta: {', '.join(missing)}"
            )
        base = urlsplit(self.base_url)
        redirect = urlsplit(self.redirect_uri)
        if not base.scheme or not base.netloc or base.username or base.password:
            raise OrbitaSsoConfigurationError("ORBITA_SSO_BASE_URL no es una URL válida")
        if (
            not redirect.scheme
            or not redirect.netloc
            or redirect.fragment
            or redirect.username
            or redirect.password
        ):
            raise OrbitaSsoConfigurationError("ORBITA_SSO_REDIRECT_URI no es una URL válida")
        if self.require_https and (base.scheme != "https" or redirect.scheme != "https"):
            raise OrbitaSsoConfigurationError("Las URLs SSO deben usar HTTPS")


@dataclass(frozen=True)
class OrbitaIdentity:
    subject: str
    email: str
    name: str
    roles: tuple[str, ...]
    token_id: str
    expires_at: int


@dataclass(frozen=True)
class OrbitaTokenResponse:
    access_token: str
    expires_in: int


class OrbitaSsoClient:
    CONTRACT_VERSION = "1.0"

    def __init__(self, config: OrbitaSsoConfig) -> None:
        config.validate()
        self._config = config
        self._discovery: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None

    async def authorization_url(self, state: str) -> str:
        discovery = await self.discovery()
        query = urlencode(
            {
                "client_id": self._config.client_id,
                "redirect_uri": self._config.redirect_uri,
                "state": state,
            }
        )
        return f"{discovery['authorization_endpoint']}?{query}"

    async def exchange_code(self, code: str) -> tuple[OrbitaTokenResponse, OrbitaIdentity]:
        discovery = await self.discovery()
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.post(
                    discovery["token_endpoint"],
                    json={
                        "code": code,
                        "client_id": self._config.client_id,
                        "client_secret": self._config.client_secret,
                        "redirect_uri": self._config.redirect_uri,
                    },
                )
        except httpx.HTTPError as exc:
            raise OrbitaSsoUnavailableError("Órbita no está disponible") from exc
        if response.status_code >= 500:
            raise OrbitaSsoUnavailableError("Órbita no está disponible")
        if not response.is_success:
            raise OrbitaSsoRejectedError("Órbita rechazó el código de autorización")
        try:
            payload = response.json()
            token_response = OrbitaTokenResponse(
                access_token=str(payload["access_token"]),
                expires_in=int(payload["expires_in"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise OrbitaSsoRejectedError("Órbita entregó una respuesta inválida") from exc
        identity = await self.verify_token(token_response.access_token)
        return token_response, identity

    async def verify_token(self, token: str) -> OrbitaIdentity:
        if not token:
            raise OrbitaSsoRejectedError("Órbita no entregó un token")
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise OrbitaSsoRejectedError("El token de Órbita no es válido") from exc
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise OrbitaSsoRejectedError("El token de Órbita no usa RS256/kid válidos")

        discovery = await self.discovery()
        supported = discovery.get("token_signing_alg_values_supported", [])
        if "RS256" not in supported:
            raise OrbitaSsoRejectedError("El contrato de Órbita no admite RS256")

        key_data = await self._find_jwk(header["kid"])
        if key_data is None:
            key_data = await self._find_jwk(header["kid"], force_refresh=True)
        if key_data is None:
            raise OrbitaSsoRejectedError("El kid del token de Órbita es desconocido")

        try:
            claims = jwt.decode(
                token,
                PyJWK.from_dict(key_data).key,
                algorithms=["RS256"],
                audience=self._config.client_id,
                leeway=30,
                options={"require": ["sub", "email", "name", "roles", "jti", "exp"]},
            )
        except (InvalidTokenError, ValueError) as exc:
            raise OrbitaSsoRejectedError("El token de Órbita no es válido") from exc

        string_claims = ("sub", "email", "name", "jti")
        if any(
            not isinstance(claims.get(field), str) or not claims[field]
            for field in string_claims
        ):
            raise OrbitaSsoRejectedError("El token de Órbita no contiene identidad válida")
        roles = claims.get("roles")
        expires_at = claims.get("exp")
        if (
            not isinstance(roles, list)
            or not roles
            or not all(isinstance(role, str) and role for role in roles)
            or not isinstance(expires_at, int)
        ):
            raise OrbitaSsoRejectedError("El token de Órbita no contiene roles/exp válidos")
        return OrbitaIdentity(
            subject=claims["sub"],
            email=claims["email"],
            name=claims["name"],
            roles=tuple(roles),
            token_id=claims["jti"],
            expires_at=expires_at,
        )

    async def sync_role_catalog(self, roles: list[dict[str, str]]) -> dict[str, Any]:
        discovery = await self.discovery()
        endpoint = discovery["role_catalog_sync_endpoint"].replace(
            "{client_id}", self._config.client_id
        )
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.put(
                    endpoint,
                    json={"client_secret": self._config.client_secret, "roles": roles},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise OrbitaSsoUnavailableError("Órbita entregó un catálogo inválido")
                return payload
        except httpx.HTTPError as exc:
            raise OrbitaSsoUnavailableError("No se pudo sincronizar el catálogo de roles") from exc

    async def discovery(self) -> dict[str, Any]:
        if self._discovery is not None:
            return self._discovery
        url = f"{self._config.base_url.rstrip('/')}/api/.well-known/orbita-configuration"
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Discovery inválido")
                discovery = payload
        except (httpx.HTTPError, ValueError) as exc:
            raise OrbitaSsoUnavailableError("No se pudo descubrir el contrato SSO") from exc
        if discovery.get("contract_version") != self.CONTRACT_VERSION:
            raise OrbitaSsoConfigurationError("La versión del contrato SSO no es compatible")
        self._validate_discovery(discovery)
        self._discovery = discovery
        return discovery

    async def _find_jwk(
        self, kid: str, *, force_refresh: bool = False
    ) -> dict[str, Any] | None:
        jwks = await self._load_jwks(force_refresh=force_refresh)
        keys = jwks.get("keys", [])
        if not isinstance(keys, list):
            raise OrbitaSsoRejectedError("El JWKS de Órbita no es válido")
        return next(
            (item for item in keys if isinstance(item, dict) and item.get("kid") == kid),
            None,
        )

    async def _load_jwks(self, *, force_refresh: bool = False) -> dict[str, Any]:
        if self._jwks is not None and not force_refresh:
            return self._jwks
        discovery = await self.discovery()
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.get(discovery["jwks_uri"])
                response.raise_for_status()
                jwks = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OrbitaSsoUnavailableError("No se pudo consultar el JWKS de Órbita") from exc
        if not isinstance(jwks, dict):
            raise OrbitaSsoRejectedError("El JWKS de Órbita no es válido")
        self._jwks = jwks
        return jwks

    def _validate_discovery(self, discovery: dict[str, Any]) -> None:
        configured = urlsplit(self._config.base_url)
        expected_origin = (configured.scheme, configured.netloc)
        fields = (
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "introspection_endpoint",
            "role_catalog_sync_endpoint",
        )
        for field in fields:
            raw = discovery.get(field)
            if not isinstance(raw, str):
                raise OrbitaSsoConfigurationError(f"Discovery no contiene {field}")
            endpoint = urlsplit(raw.replace("{client_id}", "client"))
            if (endpoint.scheme, endpoint.netloc) != expected_origin:
                raise OrbitaSsoConfigurationError(
                    f"El endpoint {field} está fuera del origen configurado"
                )
            if endpoint.fragment or endpoint.username or endpoint.password:
                raise OrbitaSsoConfigurationError(f"El endpoint {field} no es seguro")

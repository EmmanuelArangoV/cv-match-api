"""Caso de uso de sesión local iniciada mediante Órbita."""

import uuid
from datetime import UTC, datetime, timedelta

from src.application.auth.orbita_roles import MATCH_ROLE_BY_ORBITA_KEY, ORBITA_ROLE_PRIORITY
from src.config import settings
from src.domain.shared.exceptions import (
    ConflictException,
    ForbiddenException,
    ServiceUnavailableException,
    UnauthorizedException,
)
from src.infrastructure.auth.orbita_sso import (
    OrbitaSsoClient,
    OrbitaSsoConfigurationError,
    OrbitaSsoRejectedError,
    OrbitaSsoUnavailableError,
)
from src.infrastructure.auth.refresh_tokens import store_refresh_token
from src.infrastructure.auth.tokens import create_access_token, create_refresh_token
from src.infrastructure.db.models import User, UserRole, UserStatus
from src.infrastructure.db.repositories.user_repository import UserRepository


class OrbitaLoginUseCase:
    def __init__(self, user_repo: UserRepository, sso_client: OrbitaSsoClient) -> None:
        self._repo = user_repo
        self._sso = sso_client

    async def execute(self, code: str) -> tuple[dict[str, object], User]:
        try:
            token_response, identity = await self._sso.exchange_code(code)
        except OrbitaSsoConfigurationError as exc:
            raise ServiceUnavailableException("El SSO de Órbita no está configurado") from exc
        except OrbitaSsoUnavailableError as exc:
            raise ServiceUnavailableException("Órbita no está disponible temporalmente") from exc
        except OrbitaSsoRejectedError as exc:
            raise UnauthorizedException("No fue posible validar la sesión con Órbita") from exc

        role = self._resolve_role(identity.roles)
        try:
            orbita_user_id = uuid.UUID(identity.subject)
        except ValueError as exc:
            raise UnauthorizedException("La identidad entregada por Órbita no es válida") from exc

        normalized_email = identity.email.strip().lower()
        if not normalized_email:
            raise UnauthorizedException("Órbita no entregó un correo válido")

        linked_user = await self._repo.find_by_orbita_user_id(orbita_user_id)
        email_owner = await self._repo.find_by_email(normalized_email)
        if linked_user is not None:
            if email_owner is not None and email_owner.id != linked_user.id:
                raise ConflictException("El correo de Órbita pertenece a otra cuenta de Match")
            user = linked_user
            if user.status != UserStatus.ACTIVE.value:
                raise UnauthorizedException("Usuario suspendido")
            first_name, last_name = self._split_name(identity.name, normalized_email)
            user.email = normalized_email
            user.name = first_name
            user.last_name = last_name
            user.role = role
            user = await self._repo.save(user)
        else:
            if email_owner is not None:
                raise ConflictException(
                    "El correo ya pertenece a una cuenta local. La vinculación con Órbita debe "
                    "hacerse explícitamente."
                )
            first_name, last_name = self._split_name(identity.name, normalized_email)
            user = await self._repo.save(
                User(
                    name=first_name,
                    last_name=last_name,
                    email=normalized_email,
                    password_hash=None,
                    orbita_user_id=orbita_user_id,
                    role=role,
                    status=UserStatus.ACTIVE.value,
                )
            )

        now = datetime.now(UTC)
        provider_deadline = min(
            identity.expires_at,
            int(now.timestamp()) + token_response.expires_in,
        )
        if provider_deadline <= int(now.timestamp()):
            raise UnauthorizedException("La sesión entregada por Órbita ya venció")
        local_deadline = min(
            datetime.fromtimestamp(provider_deadline, UTC),
            now + timedelta(minutes=settings.access_token_expire_minutes),
        )
        access_token = create_access_token(
            str(user.id),
            role.value,
            expires_at=local_deadline,
        )
        refresh_token = create_refresh_token()
        await store_refresh_token(
            refresh_token,
            str(user.id),
            absolute_expires_at=provider_deadline,
        )
        return (
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "role": role.value,
                "expires_in": max(1, int((local_deadline - now).total_seconds())),
                "session_expires_in": max(1, provider_deadline - int(now.timestamp())),
            },
            user,
        )

    @staticmethod
    def _resolve_role(roles: tuple[str, ...]) -> UserRole:
        unknown = set(roles) - MATCH_ROLE_BY_ORBITA_KEY.keys()
        if unknown:
            raise ForbiddenException("Órbita entregó roles no reconocidos por Match")
        for key in ORBITA_ROLE_PRIORITY:
            if key in roles:
                return MATCH_ROLE_BY_ORBITA_KEY[key]
        raise ForbiddenException("Tu cuenta no tiene un rol habilitado para Match")

    @staticmethod
    def _split_name(display_name: str, email: str) -> tuple[str, str]:
        clean_name = " ".join(display_name.split()) or email.split("@", 1)[0]
        parts = clean_name.split(" ", 1)
        return parts[0][:100], (parts[1] if len(parts) > 1 else "")[:100]

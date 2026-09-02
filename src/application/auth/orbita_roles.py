"""Catálogo de roles de Match publicado en Órbita."""

from src.infrastructure.db.models import UserRole

ORBITA_ROLE_CATALOG: list[dict[str, str]] = [
    {
        "key": "admin",
        "display_name": "Administrador",
        "description": "Administración completa de Riwi Match.",
    },
    {
        "key": "ta_leader",
        "display_name": "Líder de Talento",
        "description": "Supervisión de recruiters y procesos de selección.",
    },
    {
        "key": "recruiter",
        "display_name": "Recruiter",
        "description": "Gestión de procesos, candidatos, match y profiling asignados.",
    },
]

MATCH_ROLE_BY_ORBITA_KEY = {
    "admin": UserRole.ADMIN,
    "ta_leader": UserRole.TA_LEADER,
    "recruiter": UserRole.RECRUITER,
}

ORBITA_ROLE_PRIORITY = ("admin", "ta_leader", "recruiter")

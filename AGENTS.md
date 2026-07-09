# AGENTS.md — Backend (cv-match-api)

Guía para agentes de IA: ver `CLAUDE.md` en este mismo directorio.

Lo imprescindible:

- **El plan de cierre del MVP (F1–F3 al 100%) está en `PLAN_MVP_100.md`, en la raíz del monorepo
  (repo padre `RiwiMatch`).** Consultarlo antes de priorizar trabajo nuevo.
- El estado real del backend está en `STATUS_RESUMEN.md` (este repo).
- Toda transición de estado pasa por las máquinas de estado de `src/domain/`; las skills de
  `.claude/skills/` documentan las reglas RB-001..RB-010 y el andamiaje de tareas Celery.

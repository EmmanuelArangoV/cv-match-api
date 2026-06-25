"""
Seed script: creates a hiring process + JD + 4 candidate CVs, then triggers match.

Candidates: Angelo Torres, Daniela Restrepo, Emmanuel Arango, Maryhug Ospina
Role: Backend Node.js Senior — area Tecnologia

Usage:
  cd C:\Users\E2112\Desktop\cv-match-api
  .venv\Scripts\python.exe scripts/seed_test_data.py
"""
import io
import json
import sys
import textwrap
import time
import requests

BASE_URL = "http://localhost:8000"
RECRUITER_EMAIL = "recruiter@riwi.io"
RECRUITER_PASSWORD = "riwi2026"

# ─── Job Description text ─────────────────────────────────────────────────────

JD_TEXT = textwrap.dedent("""
CARGO: Backend Engineer Senior — Node.js / TypeScript
EMPRESA: RIWI S.A.S  |  AREA: Tecnologia  |  CIUDAD: Medellin, Colombia

== RESUMEN DEL ROL ==
Buscamos un Backend Engineer Senior con dominio profundo de Node.js y TypeScript
para liderar el desarrollo de microservicios de alta disponibilidad en la plataforma
RIWI. El candidato sera responsable de diseno de APIs REST, integracion con servicios
de IA (OpenAI, LangChain), gestion de colas (Celery / BullMQ) y mantenimiento de
infraestructura en AWS/GCP.

== REQUISITOS OBLIGATORIOS ==
- 4+ anos de experiencia en Node.js con TypeScript en produccion
- Dominio de NestJS o Express con arquitectura limpia / DDD
- Experiencia con PostgreSQL, Redis, y colas de mensajeria (RabbitMQ / BullMQ)
- Conocimiento de Docker y orquestacion (Docker Compose, Kubernetes basico)
- Ingles B2 o superior (lecturas tecnicas y reuniones con equipo distribuido)
- Seniority: Senior (4-8 anos de experiencia total en software)

== REQUISITOS DESEABLES ==
- Experiencia con OpenAI API o modelos LLM en produccion
- Conocimiento de Python (FastAPI / Django) como lenguaje secundario
- Experiencia en startups o equipos de producto agiles
- Certificaciones en AWS (Solutions Architect o Developer)

== STACK TECNOLOGICO ==
Node.js 20+, TypeScript 5, NestJS, PostgreSQL 15, Redis 7, BullMQ,
Docker, GitHub Actions, AWS (EC2, RDS, S3, Lambda), OpenAI API

== CONDICIONES ==
Modalidad: 100% remoto
Salario: COP 8.000.000 – 12.000.000 segun experiencia
Contrato: Indefinido
""").strip()

# ─── CV templates ─────────────────────────────────────────────────────────────

CANDIDATES = [
    {
        "name": "Angelo",
        "last_name": "Torres",
        "filename": "cv_angelo_torres.pdf",
        "cv_text": textwrap.dedent("""
        ANGELO TORRES MEJIA
        Backend Engineer Senior | angelo.torres@gmail.com | +57 310 555 0101
        Medellin, Colombia | github.com/angelotorres | linkedin.com/in/angelotorres

        PERFIL PROFESIONAL
        Ingeniero de software con 6 anos de experiencia especializado en Node.js y TypeScript.
        He liderado arquitecturas de microservicios para fintechs y plataformas SaaS en Colombia y Mexico.
        Apasionado por la calidad del codigo, testing y entrega continua.

        EXPERIENCIA LABORAL

        Backend Tech Lead — Pagos Colombia S.A.S (2022 – presente)
        - Lideré la migracion de monolito Rails a microservicios Node.js/NestJS sirviendo 500k transacciones/dia
        - Disenei APIs REST y GraphQL con NestJS, PostgreSQL y Redis para procesamiento de pagos en tiempo real
        - Implementé sistema de colas con BullMQ para procesamiento asincrono de webhooks de Wompi y PSE
        - Reduccion de latencia P99 de 2.1s a 180ms mediante caching Redis y query optimization
        - Liderancé equipo de 4 ingenieros backend con code reviews semanales y pair programming

        Backend Engineer Senior — Rappi Colombia (2019 – 2022)
        - Desarrollé microservicios de logistica en Node.js/Express atendiendo 2M usuarios activos
        - Migré pipelines de datos a AWS Lambda + SQS para procesamiento de eventos en tiempo real
        - Integraciones con proveedores de pagos (Stripe, PayU, Adyen)
        - PostgreSQL tuning: particionamiento de tablas y creacion de indices compuestos

        Backend Developer — Freelance (2018 – 2019)
        - Desarrollo de APIs REST para startups locales usando Express.js y MongoDB

        EDUCACION
        Ingenieria de Sistemas — Universidad de Antioquia (2013 – 2018) | GPA 4.2/5.0

        HABILIDADES TECNICAS
        Node.js, TypeScript, NestJS, Express.js, PostgreSQL, Redis, BullMQ, Docker,
        AWS (EC2, RDS, Lambda, S3, SQS), GitHub Actions, Jest, Supertest, OpenAI API

        IDIOMAS
        Espanol: nativo | Ingles: C1 (TOEFL iBT 105)

        CERTIFICACIONES
        AWS Certified Solutions Architect — Associate (2023)
        """).strip(),
    },
    {
        "name": "Daniela",
        "last_name": "Restrepo",
        "filename": "cv_daniela_restrepo.pdf",
        "cv_text": textwrap.dedent("""
        DANIELA RESTREPO CARDONA
        Desarrolladora Backend | daniela.restrepo@outlook.com | +57 300 444 2020
        Bogota, Colombia | github.com/danirestrepo

        PERFIL
        Desarrolladora backend con 3 anos de experiencia en Python/Django y FastAPI.
        Actualmente aprendiendo Node.js. Fuerte en ciencia de datos y procesamiento de texto con IA.

        EXPERIENCIA

        Backend Developer — Startuplab Bogota (2023 – presente)
        - Desarrollo de APIs REST con FastAPI y Python para plataforma EdTech con 50k usuarios
        - Integracion con OpenAI GPT-4 para generacion automatica de contenido educativo
        - PostgreSQL y Redis para cache de resultados de consultas complejas
        - Desplegues con Docker en DigitalOcean

        Desarrolladora Junior — Empresa de Consultoria XYZ (2021 – 2023)
        - Mantenimiento de aplicaciones Django/Python legacy
        - Migraciones de base de datos y scripting con Python

        EDUCACION
        Ingenieria de Sistemas — Universidad Nacional de Colombia (2016 – 2021)

        HABILIDADES
        Python, FastAPI, Django, PostgreSQL, Redis, Docker, OpenAI API,
        JavaScript basico, algo de Node.js (2 meses autoaprendizaje)

        IDIOMAS
        Espanol: nativo | Ingles: B1 (lecto-escritura tecnica, conversacion limitada)
        """).strip(),
    },
    {
        "name": "Emmanuel",
        "last_name": "Arango",
        "filename": "cv_emmanuel_arango.pdf",
        "cv_text": textwrap.dedent("""
        EMMANUEL ARANGO VARGAS
        Full Stack Developer | emmanuel.arango@gmail.com | +57 315 777 3030
        Medellin, Colombia | github.com/emmanuelajv | linkedin.com/in/emmanuelajv

        PERFIL PROFESIONAL
        Full Stack Developer con 5 anos de experiencia, mitad backend mitad frontend.
        Experiencia solida en Node.js/TypeScript con NestJS y React/Next.js.
        He trabajado en productos SaaS B2B y plataformas de reclutamiento.

        EXPERIENCIA

        Full Stack Engineer — RIWI S.A.S (2023 – presente)
        - Desarrollo de plataforma de matching CV con Node.js/NestJS (backend) y Next.js 14 (frontend)
        - Integracion con OpenAI para parsing de CVs y scoring de candidatos
        - PostgreSQL con Supabase, Redis para sesiones, Celery (Python) para tareas asincronas
        - Cloudflare R2 para almacenamiento de PDFs, implementacion de webhooks WhatsApp Business

        Backend Developer — Fintech XYZ (2021 – 2023)
        - APIs REST con Express.js/TypeScript para procesamiento de creditos digitales
        - Integracion con bureaus de credito (TransUnion, Experian) via SOAP/REST
        - PostgreSQL, Redis, Docker, CI/CD con GitHub Actions

        Desarrollador Junior — Agencia Digital ABC (2019 – 2021)
        - Desarrollo web con Node.js, React, MongoDB

        EDUCACION
        Ingenieria de Software — Universidad EAFIT (2015 – 2019)

        HABILIDADES TECNICAS
        Node.js, TypeScript, NestJS, Express, React, Next.js, PostgreSQL,
        Redis, Docker, OpenAI API, Python (FastAPI, Celery), AWS S3, Cloudflare R2

        IDIOMAS
        Espanol: nativo | Ingles: B2 (lectura tecnica fluida, reuniones en ingles)
        """).strip(),
    },
    {
        "name": "Maryhug",
        "last_name": "Ospina",
        "filename": "cv_maryhug_ospina.pdf",
        "cv_text": textwrap.dedent("""
        MARYHUG OSPINA HENAO
        Backend Engineer | maryhug.ospina@gmail.com | +57 312 888 4040
        Cali, Colombia | github.com/maryhugospina

        PERFIL
        Ingeniera backend con 4 anos de experiencia en Node.js y Python.
        Especializada en arquitecturas de microservicios y sistemas distribuidos.
        Experiencia en empresas de tecnologia financiera y salud digital.

        EXPERIENCIA

        Backend Engineer — HealthTech Colombia (2022 – presente)
        - Microservicios Node.js/NestJS para plataforma de telemedicina con 200k usuarios activos
        - Diseno de APIs RESTful y gRPC para comunicacion entre microservicios
        - PostgreSQL con migraciones TypeORM, Redis para pub/sub y sesiones de usuario
        - BullMQ para procesamiento asincrono de notificaciones y reportes medicos
        - Docker + Kubernetes en GKE, monitoreo con Grafana/Prometheus

        Backend Developer — Nequi (Bancolombia) (2020 – 2022)
        - Desarrollo en Node.js/TypeScript para APIs de billetera digital
        - Manejo de transacciones de alta concurrencia con PostgreSQL y locking optimista
        - Integracion con sistemas Core Bancario via mensajeria Kafka

        EDUCACION
        Ingenieria Informatica — Universidad del Valle (2015 – 2020) | Grado con honors

        HABILIDADES
        Node.js, TypeScript, NestJS, PostgreSQL, Redis, BullMQ, gRPC,
        Docker, Kubernetes, GKE, Kafka, Python (scripting), GitHub Actions

        IDIOMAS
        Espanol: nativo | Ingles: B2 (reuniones tecnicas y documentacion)

        CERTIFICACIONES
        Google Cloud Professional Developer (2023)
        """).strip(),
    },
]

# ─── PDF generation (minimal valid PDF with text) ────────────────────────────

def make_pdf(text: str) -> bytes:
    """Create a minimal PDF with the given text content."""
    lines = text.split("\n")
    y = 750
    stream_lines = []
    for line in lines:
        safe = (line
            .replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
            .replace("\r", ""))
        if not safe.strip():
            y -= 10
        else:
            # Simple truncation: keep under ~90 chars per line to avoid layout issues
            while len(safe) > 90:
                stream_lines.append(f"BT /F1 9 Tf 40 {y} Td ({safe[:90]}) Tj ET")
                safe = safe[90:]
                y -= 12
            stream_lines.append(f"BT /F1 9 Tf 40 {y} Td ({safe}) Tj ET")
            y -= 12
        if y < 50:
            y = 750  # wrap to top (single page for simplicity)

    stream_content = "\n".join(stream_lines)
    stream_bytes = stream_content.encode("latin-1", errors="replace")
    stream_len = len(stream_bytes)

    pdf = (
        f"%PDF-1.4\n"
        f"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        f"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        f"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]\n"
        f"   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        f"4 0 obj\n<< /Length {stream_len} >>\nstream\n"
    ).encode("latin-1")

    end_part = (
        f"\nendstream\nendobj\n"
        f"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        f"xref\n0 6\n"
        f"0000000000 65535 f \n"
        f"trailer\n<< /Size 6 /Root 1 0 R >>\n"
        f"startxref\n0\n%%EOF\n"
    ).encode("latin-1")

    return pdf + stream_bytes + end_part


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    s = requests.Session()
    s.verify = False

    # 1. Login
    print("Logging in...")
    r = s.post(f"{BASE_URL}/api/v1/auth/login",
               json={"email": RECRUITER_EMAIL, "password": RECRUITER_PASSWORD})
    if r.status_code != 200:
        print(f"Login failed: {r.status_code} {r.text}")
        sys.exit(1)
    token = r.json()["access_token"]
    s.headers["Authorization"] = f"Bearer {token}"
    print("  Login OK")

    # 2. Create hiring process
    print("\nCreating hiring process...")
    r = s.post(f"{BASE_URL}/api/v1/processes/", json={
        "name": "Backend Node.js Senior — Tecnologia 2026",
        "job_title": "Backend Engineer Senior",
        "area": "Tecnologia",
        "seniority": "Sr",
        "budget_max_usd": 50.0,
    })
    if r.status_code not in (200, 201):
        print(f"Create process failed: {r.status_code} {r.text}")
        sys.exit(1)
    process_data = r.json()
    # Support both response shapes
    process_id = process_data.get("process_id") or process_data.get("id")
    print(f"  Process ID: {process_id}")

    # 3. Upload Job Description
    print("\nUploading Job Description...")
    r = s.post(f"{BASE_URL}/api/v1/processes/{process_id}/job-description",
               json={"jd_text": JD_TEXT})
    if r.status_code not in (200, 201):
        print(f"Upload JD failed: {r.status_code} {r.text}")
        sys.exit(1)
    print("  JD uploaded OK")

    # 4. Generate and upload CVs
    print("\nUploading CVs...")
    files_to_upload = []
    for c in CANDIDATES:
        pdf_bytes = make_pdf(c["cv_text"])
        files_to_upload.append(("files", (c["filename"], io.BytesIO(pdf_bytes), "application/pdf")))
        print(f"  Generated PDF for {c['name']} {c['last_name']} ({len(pdf_bytes)} bytes)")

    r = s.post(f"{BASE_URL}/api/v1/processes/{process_id}/candidates/upload",
               files=files_to_upload)
    if r.status_code not in (200, 201):
        print(f"Upload CVs failed: {r.status_code} {r.text}")
        sys.exit(1)
    upload_result = r.json()
    print(f"  Uploaded: {upload_result.get('uploaded', '?')} CVs queued for processing")

    # 5. Wait for CV processing (parse_cv tasks)
    print("\nWaiting for CV processing (parse_cv tasks)...")
    max_wait = 300  # 5 minutes
    interval = 10
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        r = s.get(f"{BASE_URL}/api/v1/processes/{process_id}/candidates")
        if r.status_code != 200:
            print(f"  Poll failed: {r.status_code}")
            continue
        candidates = r.json().get("candidates", [])
        statuses = [c["status"] for c in candidates]
        processing = [s2 for s2 in statuses if s2 in ("LOADED", "CV_PROCESSING")]
        errors = [s2 for s2 in statuses if s2 == "CV_ERROR"]
        done = [s2 for s2 in statuses if s2 == "MATCH_PENDING"]
        print(f"  [{elapsed}s] Processing: {len(processing)} | Done: {len(done)} | Errors: {len(errors)}")
        if len(processing) == 0 and len(candidates) > 0:
            break

    if errors:
        print(f"  WARNING: {len(errors)} CV(s) had errors")

    # 6. Trigger match
    print("\nTriggering AI match...")
    r = s.post(f"{BASE_URL}/api/v1/match/{process_id}/run")
    if r.status_code not in (200, 201, 202):
        print(f"Trigger match failed: {r.status_code} {r.text}")
        sys.exit(1)
    match_result = r.json()
    print(f"  Queued {match_result.get('queued', '?')} match tasks")

    # 7. Wait for match results
    print("\nWaiting for match results...")
    elapsed = 0
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        r = s.get(f"{BASE_URL}/api/v1/processes/{process_id}/candidates")
        if r.status_code != 200:
            continue
        candidates = r.json().get("candidates", [])
        matched    = [c for c in candidates if c["status"] == "MATCHED"]
        pending    = [c for c in candidates if c["status"] in ("MATCH_PENDING", "MATCH_PROCESSING")]
        print(f"  [{elapsed}s] Matched: {len(matched)} | Pending: {len(pending)}")
        if len(pending) == 0 and len(candidates) > 0:
            break

    # 8. Print results
    print("\n" + "="*60)
    print("MATCH RESULTS")
    print("="*60)
    r = s.get(f"{BASE_URL}/api/v1/processes/{process_id}/candidates")
    candidates = r.json().get("candidates", [])
    candidates.sort(key=lambda c: c.get("match_percentage", 0), reverse=True)
    for c in candidates:
        pct  = c.get("match_percentage", 0)
        cat  = c.get("match_category", "?")
        name = c.get("name", "?")
        print(f"  #{c.get('rank','?'):>2}  {name:<30}  {pct:>5.1f}%  [{cat}]")

    print("\nDone!")
    print(f"Process ID: {process_id}")
    print(f"Frontend:   http://localhost:3000/hiring-processes/{process_id}/ranking")


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    main()

# PJUD Scraper API

## Instalación

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # completar TWOCAPTCHA_API_KEY
```

## Ejecutar

```bash
uvicorn api:app --reload --port 8000
```

Swagger UI disponible en: http://localhost:8000/docs

## Endpoints

### GET /health
```json
{ "success": true, "status": "ok" }
```

### POST /causas/rit
**Body:**
```json
{ "rol": "121212", "anio": "2019" }
```
**Respuesta:**
```json
{
  "success": true,
  "timestamp": "2026-01-15T10:30:00",
  "tipo_busqueda": "rit",
  "total": 1,
  "causas": [
    {
      "rol": "121212-2019",
      "tipo_recurso": "(Civil) Apelación",
      "caratulado": "PÉREZ CON BANCO X",
      "fecha_ingreso": "15/03/2019",
      "estado_causa": "Tabla",
      "corte": "Corte de Apelaciones de Santiago"
    }
  ]
}
```

### POST /causas/nombre
**Body:**
```json
{
  "nombre": "Carlos",
  "ape_paterno": "Suazo",
  "ape_materno": "",
  "competencia": "1"
}
```

## Ejemplo con curl

```bash
curl -X POST http://localhost:8000/causas/nombre \
  -H "Content-Type: application/json" \
  -d '{"nombre": "Carlos", "ape_paterno": "Suazo", "competencia": "1"}'
```

## Notas
- Requiere TWOCAPTCHA_API_KEY (~$2 USD / 1000 consultas)
- Cada request demora ~20-40s (tiempo de resolución del captcha)
- No hacer más de 1 request simultáneo al mismo endpoint

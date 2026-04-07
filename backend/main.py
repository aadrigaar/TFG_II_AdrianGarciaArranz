"""
main.py — Corte Perfecto
FastAPI backend: endpoints REST + integración asíncrona con LM Studio.

Optimizado para RTX 3060 6 GB VRAM:
  - Llamadas async con httpx (no bloquea el event loop)
  - Timeout conservador de 120 s (modelos locales pueden tardar)
  - System prompt compacto para reducir contexto y VRAM
"""

from __future__ import annotations

import json
import os
import re
import calendar
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Cita, Cliente, Servicio, get_db, init_db

load_dotenv()

LM_STUDIO_URL = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
# Fecha fija del proyecto (consistencia calendario)
PROJECT_TODAY = date(2026, 4, 7)
GOODBYE_REPLY = "¡Entendido! Si me necesitas para otra cosa, aquí estaré. ¡Buen día!"
INFO_REPLY = (
    "Horario: Lunes a Viernes de 10:00 a 20:00. Sábados y domingos cerrado. "
    "Servicios y precios: Corte 20€, Tinte 40€, Peinado 15€. "
    "Combinaciones: Corte y Peinado 35€, Tinte y Peinado 55€, "
    "Corte y Tinte 60€, Corte y Tinte y Peinado 75€."
)
INVALID_NAME_PARTICLES = {
    "so", "si", "ok", "yo", "asdf", "asd", "q", "w", "e", "r", "x", "z", "na", "nop",
    "sin", "nombre", "desconocido", "anonimo", "anónimo"
}
SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# ── App & CORS ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Corte Perfecto API",
    description="Backend para la peluquería Corte Perfecto en Santander",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Schemas ─────────────────────────────────────────────────────────

class CitaCreate(BaseModel):
    nombre_cliente: str
    servicio_nombre: str
    fecha: str          # YYYY-MM-DD
    hora: str           # HH:MM
    notas: Optional[str] = None


class CitaOut(BaseModel):
    id: int
    nombre_cliente: str
    servicio_nombre: str
    fecha: str
    hora: str
    estado: str
    creada_en: datetime

    class Config:
        from_attributes = True


class ServicioOut(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str]
    precio: float
    duracion_minutos: int

    class Config:
        from_attributes = True


class ChatMessage(BaseModel):
    role: str           # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class ChatResponse(BaseModel):
    response: str           # texto limpio de la IA
    cita_creada: Optional[CitaOut] = None


# ── System Prompt con técnica de marcador ─────────────────────────────────────

SYSTEM_PROMPT = """Eres un peluquero real que trabaja en "Corte Perfecto" (Santander) y atiende a clientes por chat.
No eres un modelo de lenguaje. No analizas. No explicas procesos internos. Solo hablas con naturalidad.

=== CALENDARIO FIJO DEL PROYECTO ===
Hoy es MARTES 7 de abril de 2026.
Mañana es MIÉRCOLES 8 de abril de 2026.
El miércoles 8 es laborable.
La peluquería solo cierra sábados y domingos.

=== PROHIBICIONES ABSOLUTAS ===
- Prohibido mencionar formato, marcador, JSON, instrucciones internas, API o razonamiento.
- Prohibido responder con ruido técnico o texto de plantilla.
- Prohibido despedirte o cerrar conversación antes de tiempo, salvo que el cliente se despida explícitamente.
- Prohibido pedir datos (nombre/servicio) que ya están en el historial reciente.
- Si el cliente dice "no", "gracias", "nada" o similar, no ofrezcas más servicios ni hagas preguntas.
  Respuesta obligatoria: "¡Entendido! Si me necesitas para otra cosa, aquí estaré. ¡Buen día!"
- Prohibido confirmar una cita con nombre vacío o "sin nombre".

=== MARCADOR OBLIGATORIO ===
Termina siempre así:
### RESPUESTA: <mensaje al cliente>

=== DATOS OFICIALES ===
Horario: Lunes a Viernes de 10:00 a 20:00.
Servicios y precios:
- Corte: 20€ (30 min)
- Tinte/mechas: 40€ (60 min)
- Peinado/recogido: 15€ (20 min)
- Corte y Peinado: 35€ (20€ + 15€)
- Tinte y Peinado: 55€ (40€ + 15€)
- Corte y Tinte: 60€ (20€ + 40€)
- Corte y Tinte y Peinado: 75€ (20€ + 40€ + 15€)

=== SINÓNIMOS DE INTENCIÓN ===
Horario: "¿A qué hora abrís?", "jornada", "cuándo está abierto", "apertura", "mañana", "tarde", "mañanas", "cuándo abrís".
Servicios: "tarifas", "precios", "qué hacéis", "cuánto vale", "catálogo", "qué tenéis".
Cita: "turno", "hueco", "reserva", "apúntame", "agendar".

=== GENEROSIDAD INFORMATIVA (REGLA DE HIERRO) ===
Si el usuario pregunta por horarios o servicios (con cualquier sinónimo), ESTÁ PROHIBIDO responder con una pregunta.
Da de una vez toda la información completa:
- Horario: Lunes a Viernes de 10:00 a 20:00; sábados y domingos cerrado.
- Servicios y precios: Corte 20€, Tinte 40€, Peinado 15€.
- Combinaciones: Corte y Peinado 35€, Tinte y Peinado 55€, Corte y Tinte 60€, Corte y Tinte y Peinado 75€.
No lo des en cuentagotas ni repitas "¿Cuál te interesa?" en bucle.

=== MEMORIA Y RESET ===
Si ya aparece nombre (por ejemplo Adrian), no vuelvas a pedirlo.
Si ya aparece servicio (Corte, Tinte, Peinado o Corte y Tinte), no vuelvas a pedirlo.
Asume misma persona y misma reserva salvo que el usuario diga "otra cita" o "nueva reserva".
Si pide otra cita o nueva reserva, olvida nombre y servicio anteriores: proceso nuevo.
Si el cliente aún no ha dicho su nombre y quiere reservar, debes preguntar:
"¡Claro! ¿A nombre de quién pongo la reserva?"

=== MODIFICACIÓN DINÁMICA ===
Si dice "añádeme un tinte", "cambia la hora", "cambia el día" o similar:
- Actualiza la reserva existente.
- Si combina servicios, suma precios reales:
  Corte + Peinado = 35€,
  Tinte + Peinado = 55€,
  Corte + Tinte = 60€,
  Corte + Tinte + Peinado = 75€.
- En el JSON, el campo "servicio" debe incluir todos los servicios combinados
  (por ejemplo: "Corte y Peinado" o "Corte y Tinte y Peinado").
- Responde: "¡Entendido [Nombre]! He actualizado tu reserva."
- Emite el JSON actualizado.

=== BLOQUEO DE FIN DE SEMANA ===
Si el JSON incluye sábado o domingo, está prohibido confirmar la reserva.
Debes proponer viernes o lunes de forma explícita.
Si el usuario pide un día de fin de semana (por ejemplo "sábado 11" o solo "11" y ese día cae en fin de semana),
no preguntes la hora. Responde directamente:
"Lo siento, el sábado 11 estamos cerrados por descanso. ¿Te vendría bien el viernes 10 o el lunes 13?".

=== VALIDACIÓN DE NOMBRE ===
Si el nombre parece inválido (por ejemplo "so", "si", "ok", "yo", "asdf"), no lo aceptes.
Pide nombre real para registro.

=== RESUMEN / CONFIRMACIÓN ===
Si pide "dame el resumen" o "dame la confirmación":
- Responde exactamente: "Aquí tienes el resumen actualizado:"
- Emite JSON inmediatamente.
- No hagas preguntas extra y no te despidas.

=== FECHA DEL USUARIO (REGLA ESTRICTA) ===
Si el usuario dice un día concreto (por ejemplo "el 23"), usa ese día exacto.
No cambies ese día por "mañana" ni por otro número.
Si pregunta "¿qué día es hoy?", responde exactamente:
"Hoy es martes 7 de abril de 2026".

=== CONFIRMACIÓN FINAL ===
Cuando tengas Nombre + Servicio + Fecha + Hora:
emite el JSON de confirmación inmediatamente en ese mismo mensaje.
### RESPUESTA: ¡Perfecto, [Nombre]! Te apunto el [día] a las [hora] para [servicio]. ¡Hasta entonces! ```json
{{"nombre": "...", "servicio": "Corte|Tinte|Peinado|Corte y Peinado|Tinte y Peinado|Corte y Tinte|Corte y Tinte y Peinado", "fecha": "YYYY-MM-DD", "hora": "HH:MM"}}
```"""






# ── Helpers ──────────────────────────────────────────────────────────────────

# ── 1. Tokens de control y etiquetas thinking ────────────────────────────────
# Cubre: DeepSeek-R1, Qwen-thinking, Mistral, LLaMA, Phi, Gemma, etc.
_CONTROL_TOKEN_RE = re.compile(
    r"<\|im_start\|>.*?<\|im_end\|>"
    r"|<\|im_start\|>|<\|im_end\|>"
    r"|\[INST\]|\[/INST\]"
    r"|<s>|</s>"
    r"|<\|endoftext\|>"
    r"|<\|eot_id\|>"
    r"|<\|start_header_id\|>.*?<\|end_header_id\|>"
    r"|assistant\s*\n",
    re.DOTALL | re.IGNORECASE,
)

# ── 2. Bloques de razonamiento interno con cualquier etiqueta conocida ────────
_REASONING_BLOCK_RE = re.compile(
    r"<(?:think|thought|thoughts|thinking|reasoning|reflect|reflection"
    r"|analyze|analyse|internal|paso|steps?|chain.of.thought|cot)>"
    r".*?"
    r"</(?:think|thought|thoughts|thinking|reasoning|reflect|reflection"
    r"|analyze|analyse|internal|paso|steps?|chain.of.thought|cot)>",
    re.DOTALL | re.IGNORECASE,
)

# ── 3. Líneas de razonamiento SIN etiqueta ── extenso para cubrir todos los patrones
_REASONING_LINE_RE = re.compile(
    r"^(?:"
    # ── Inglés ──
    r"Let me (?:think|analyze|check|reason|process|consider|figure|work)[^\n]*"
    r"|I(?:'m| am| will| need to| should|'ll) (?:think|reason|analyze|consider|process|check|look|respond|answer|help|provide)[^\n]*"
    r"|(?:First|Now|Next|Then|Finally|Also|Note|Remember|So)[,:]?\s+(?:I|the|we|let)[^\n]*"
    r"|Step \d+[:\s][^\n]*"
    r"|The (?:user|client|customer) (?:said|says|wants|asked|is asking|mentioned|provided|has)[^\n]*"
    r"|(?:User|Customer|Client) (?:input|message|request|query|said):[^\n]*"
    r"|Today is[^\n]*"
    r"|The (?:date|time|day|current)[^\n]*"
    r"|It(?:'s| is) (?:currently )?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|January|February|March|April|May|June|July|August|September|October|November|December)[^\n]*"
    r"|(?:In Spain|In Santander|The barbershop|Our hours|Our services|Dear customer)[^\n]*"
    r"|My response (?:should|must|will|is|would)[^\n]*"
    r"|(?:According to|Based on) (?:the|my|our)[^\n]*"
    r"|(?:However|But|Although)[,]? (?:the|I|according)[^\n]*"
    r"|(?:Since|Because|As) (?:I|the|we|there)[^\n]*"
    # ── Español: razonamiento explicitado ──
    r"|El cliente (?:dice|ha dicho|quiere|pide|menciona|indica|solicita|ha indicado|está)[^\n]*"
    r"|El usuario (?:dice|ha dicho|quiere|pide|menciona|indica|solicita|ha indicado|está)[^\n]*"
    r"|El cliente (?:no ha|no ha indicado)[^\n]*"
    r"|Hoy es (?:lunes|martes|miércoles|jueves|viernes|sábado|domingo)[^\n]*"
    r"|(?:Así que|Por lo tanto|Por eso|Entonces)[,]? (?:puedo|debo|hay|la|el|se)[^\n]*"
    r"|Necesito recopilar[^\n]*"
    r"|Necesito (?:pedir|preguntar|solicitar|recoger|obtener)[^\n]*"
    r"|(?:Primero|Segundo|Tercero)[,]? debo[^\n]*"
    r"|Mi respuesta (?:debe|será|es|puede)[^\n]*"
    r"|No puedo incluir[^\n]*"
    r"|No tengo (?:los|la|el|un|una)[^\n]*"
    r"|(?:Debo|Voy a|Tengo que) responder[^\n]*"
    r"|Según (?:las reglas|la instrucción|el prompt|las instrucciones)[^\n]*"
    r"|La (?:regla|instrucción|fecha|respuesta) (?:\d+|dice|es|final|debe)[^\n]*"
    r"|Sin embargo[,]? la instrucción[^\n]*"
    r"|Pero (?:la|según|también|la regla)[^\n]*"
    r"|La fecha (?:es|será|ya está)[^\n]*"
    r"|Ya (?:está definida|tengo|sé)[^\n]*"
    r"|Paso \d+[:\s][^\n]*"
    r"|Ra[zs]on(?:amiento|ando)[^\n]*"
    r"|Pens(?:ando|amiento)[^\n]*"
    r"|Análisis[^\n]*"
    r"|Proceso interno[^\n]*"
    r"|\[(?:Pensamiento|Razonamiento|Interno|Internal|Thinking|Análisis)\][^\n]*"
    r")",
    re.MULTILINE | re.IGNORECASE,
)


# ── 4. Bloques y objetos JSON (el frontend los muestra como tarjeta, no como texto) ──
_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*\{.*?\}\s*```"   # bloque markdown ```json {...} ```
    r"|(?:^|\n)\{[^{}\n]*\"nombre\"[^{}\n]*\}",  # JSON inline de reserva
    re.DOTALL | re.IGNORECASE,
)

# ── 5. Frases en inglés que el modelo filtra ("Today is...", "The date...") ───
_ENGLISH_LEAK_RE = re.compile(
    r"^(?:"
    r"Today is[^\n]*"
    r"|The (?:date|time|day|current)[^\n]*"
    r"|It(?:'s| is) (?:currently )?(?:Monday|Tuesday|Wednesday|Thursday|Friday"
               r"|Saturday|Sunday|January|February|March|April|May|June"
               r"|July|August|September|October|November|December)[^\n]*"
    r"|In (?:Spain|Santander)[^\n]*"
    r"|The (?:barbershop|salon|shop)[^\n]*"
    r"|Our (?:hours|schedule|services)[^\n]*"
    r"|Dear (?:customer|client)[^\n]*"
    r")",
    re.MULTILINE | re.IGNORECASE,
)


# ── 6. Marcadores de respuesta explícita ('Respuesta:' / 'Mi respuesta:') ────
_RESPUESTA_MARKER_RE = re.compile(
    r'^(?:Respuesta|Mi respuesta|Respondo|Output|Answer)\s*:\s*["\u201c]?',
    re.MULTILINE | re.IGNORECASE,
)

# ── 7. Filtro anti-meta tras marcador ### RESPUESTA: ─────────────────────────
_TECHNICAL_LINE_RE = re.compile(
    r"(?:\b(?:marcador|json|instrucciones|propuesta|cliente|escribo)\b"
    r"|(?:usando|usar|generando|generar|enviando|enviar).*(?:marcador|json)"
    r"|formato de (?:respuesta|salida)|bloque json)",
    re.IGNORECASE,
)

_NOISE_LINE_RE = re.compile(
    r"^\s*(?:###\s*RESPUESTA:|```(?:json)?|```|<\|.*?\|>|\[/?INST\]|</?s>|</?think>|</?thought>|</?reasoning>)\s*$",
    re.IGNORECASE,
)

# Regex para detectar si el texto tiene mucho contenido de razonamiento
_HAS_REASONING_RE = re.compile(
    r"(?:El cliente|El usuario|Necesito recopilar|Mi respuesta debe|Según (?:las reglas|la instrucción)"
    r"|Today is|The user|Let me|Hoy es (?:lunes|martes|miércoles|jueves|viernes)"
    r"|Debo responder|No puedo incluir|Sin embargo, la instrucción)",
    re.IGNORECASE,
)


def extract_final_response(text: str) -> str:
    """
    Estrategia inteligente de extraccion cuando el modelo filtra sus pensamientos:
    1. Si existe marcador 'Respuesta:' o similar, extrae el texto posterior.
    2. Si hay razonamiento detectado, toma el ULTIMO PARRAFO que no sea razonamiento.
    3. Si no, devuelve el texto tal cual para que lo limpie clean_reply.
    """
    # Estrategia 1: Buscar marcador 'Respuesta: "..."'
    marker_match = _RESPUESTA_MARKER_RE.search(text)
    if marker_match:
        after = text[marker_match.end():]
        # Quitar comillas de cierre si las hay
        after = re.sub(r'["\u201d\']*$', '', after.split('\n')[0]).strip()
        # Si está entre comillas dobles, extraer contenido
        quoted = re.match(r'["\u201c](.*?)["\u201d]', after, re.DOTALL)
        if quoted:
            return quoted.group(1).strip()
        if len(after) > 10:
            return after

    # Estrategia 2: Si detectamos razonamiento, tomar el ultimo parrafo util
    if _HAS_REASONING_RE.search(text):
        paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
        for para in reversed(paragraphs):
            # El parrafo final util: empieza con signo de exclamacion, saludo o pregunta
            if re.match(r'^[\u00a1\u00bfA-Za-zÀ-ɏЀ-ӿ]', para):
                # Verificar que NO es razonamiento
                if not _HAS_REASONING_RE.search(para):
                    # Quitar comillas si el parrafo esta entre comillas
                    para = re.sub(r'^["\u201c](.*)["\u201d]$', r'\1', para, flags=re.DOTALL)
                    return para.strip()

    # Estrategia 3: Devolver texto para que lo procese clean_reply normalmente
    return text


def strip_technical_lines(text: str) -> str:
    """Elimina líneas con vocabulario técnico/meta tras el marcador ### RESPUESTA:."""
    if not text:
        return text
    text = _CONTROL_TOKEN_RE.sub("", text)
    text = re.sub(r"###\s*RESPUESTA:\s*", "", text, flags=re.IGNORECASE)
    lines = []
    for ln in text.splitlines():
        if _NOISE_LINE_RE.match(ln):
            continue
        if _TECHNICAL_LINE_RE.search(ln):
            continue
        lines.append(ln)
    clean = "\n".join(lines).strip()
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean


def last_user_message(messages: List[ChatMessage]) -> str:
    """Devuelve el último mensaje del usuario del historial."""
    for msg in reversed(messages):
        if msg.role == "user":
            return msg.content or ""
    return ""


def is_reset_intent(user_text: str) -> bool:
    if not user_text:
        return False
    return bool(re.search(r"\b(?:otra cita|nueva cita|nueva reserva|reservar otra)\b", user_text, re.IGNORECASE))


def is_closing_intent(user_text: str) -> bool:
    if not user_text:
        return False
    text = user_text.strip().lower()
    if re.fullmatch(r"(?:no+|no gracias|gracias|nada|nada gracias|ninguna|ninguno|vale|ok|de acuerdo)", text):
        return True
    return bool(re.search(r"\b(?:no gracias|nada más|nada mas|eso es todo|ya está|ya esta)\b", text, re.IGNORECASE))


def is_info_request(user_text: str) -> bool:
    if not user_text:
        return False
    text = user_text.lower()
    horario = re.search(
        r"(?:horario|horarios|abr[ei]s|apertura|jornada|abierto|cerr[aá]is|ma[ñn]anas|tardes)",
        text,
        re.IGNORECASE,
    )
    servicios = re.search(
        r"(?:tarifas?|precios?|cu[aá]nto vale|cat[aá]logo|servicios?|qu[eé] hac[eé]is|qu[eé] ten[eé]is)",
        text,
        re.IGNORECASE,
    )
    return bool(horario or servicios)


def is_today_query(user_text: str) -> bool:
    if not user_text:
        return False
    return bool(re.search(r"(?:qu[eé]\s+d[ií]a\s+es\s+hoy|fecha\s+de\s+hoy|hoy\s+qu[eé]\s+d[ií]a)", user_text, re.IGNORECASE))


def is_summary_intent(user_text: str) -> bool:
    if not user_text:
        return False
    return bool(re.search(
        r"(?:dame la reserva|dame reserva|ens[eé]ñame|ensename|a ver|resumen|confirmaci[oó]n|p[áa]samela|pasamela)",
        user_text,
        re.IGNORECASE,
    ))


def is_valid_booking_name(raw_name: str) -> bool:
    if not raw_name:
        return False
    name = raw_name.strip().lower()
    if not name:
        return False
    if name in {"sin nombre", "sin_nombre", "no nombre", "ninguno"}:
        return False
    if len(name) < 2:
        return False
    if any(ch.isdigit() for ch in name):
        return False
    tokens = [tok for tok in re.split(r"\s+", name) if tok]
    if not tokens:
        return False
    if name in INVALID_NAME_PARTICLES:
        return False
    if all(tok in INVALID_NAME_PARTICLES for tok in tokens):
        return False
    if len(tokens) == 1 and len(tokens[0]) <= 2:
        return False
    return True


def weekend_block_message(weekend_day: date) -> str:
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    day_name = dias[weekend_day.weekday()]
    days_back_to_friday = (weekend_day.weekday() - 4) % 7
    friday = weekend_day - timedelta(days=days_back_to_friday)
    days_to_monday = (7 - weekend_day.weekday()) % 7
    monday = weekend_day + timedelta(days=days_to_monday)
    return (
        f"Lo siento, el {day_name} {weekend_day.day} estamos cerrados por descanso. "
        f"¿Te vendría bien el viernes {friday.day} o el lunes {monday.day}?"
    )


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _resolve_day_in_month(day: int, year: int, month: int) -> Optional[date]:
    if day < 1:
        return None
    if day > calendar.monthrange(year, month)[1]:
        return None
    return _safe_date(year, month, day)


def parse_requested_date(user_text: str, base_day: date) -> Optional[date]:
    """Intenta resolver una fecha real desde texto libre del usuario."""
    if not user_text:
        return None

    text = user_text.lower()

    # YYYY-MM-DD
    iso = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if iso:
        y, m, d = map(int, iso.groups())
        return _safe_date(y, m, d)

    # DD/MM[/YYYY]
    slash = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if slash:
        d = int(slash.group(1))
        m = int(slash.group(2))
        y_raw = slash.group(3)
        y = base_day.year if not y_raw else int(y_raw)
        if y < 100:
            y += 2000
        return _safe_date(y, m, d)

    # "11 de mayo [de 2026]"
    month_name = re.search(
        r"\b(\d{1,2})\s+de\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
        r"(?:\s+de\s+(20\d{2}))?\b",
        text,
        re.IGNORECASE,
    )
    if month_name:
        d = int(month_name.group(1))
        m = SPANISH_MONTHS[month_name.group(2).lower()]
        y = int(month_name.group(3)) if month_name.group(3) else base_day.year
        return _safe_date(y, m, d)

    # "mes que viene" + día
    next_month_day = re.search(
        r"\b(?:mes que viene|pr[oó]ximo mes|el mes que viene)\b.*?\b(\d{1,2})\b"
        r"|\b(\d{1,2})\b.*?\b(?:mes que viene|pr[oó]ximo mes|el mes que viene)\b",
        text,
        re.IGNORECASE,
    )
    if next_month_day:
        day_str = next_month_day.group(1) or next_month_day.group(2)
        if day_str:
            ny, nm = _next_month(base_day.year, base_day.month)
            resolved = _resolve_day_in_month(int(day_str), ny, nm)
            if resolved:
                return resolved

    # Día suelto o contextual "el 11"
    isolated_day = re.fullmatch(r"\s*(?:el\s+)?(\d{1,2})\s*[?.!]?\s*", text, re.IGNORECASE)
    contextual_day = re.search(r"\b(?:el|día|dia|para el|quiero el)\s+(\d{1,2})\b", text, re.IGNORECASE)
    day_candidate = isolated_day.group(1) if isolated_day else (contextual_day.group(1) if contextual_day else None)
    if day_candidate:
        d = int(day_candidate)
        # Si aún no pasó en este mes, usar este mes; si ya pasó, próximo mes.
        current_month_resolved = _resolve_day_in_month(d, base_day.year, base_day.month)
        if current_month_resolved and current_month_resolved >= base_day:
            return current_month_resolved
        ny, nm = _next_month(base_day.year, base_day.month)
        return _resolve_day_in_month(d, ny, nm)

    return None


def detect_requested_weekend_date(user_text: str) -> Optional[date]:
    """Detecta si la fecha pedida por el usuario cae en sábado o domingo."""
    if not user_text:
        return None

    parsed = parse_requested_date(user_text, PROJECT_TODAY)
    if parsed:
        return parsed if parsed.weekday() >= 5 else None

    # Si no se pudo resolver fecha exacta pero menciona sábado/domingo, usar el próximo.
    text = user_text.lower()
    weekend_word = re.search(r"\b(s[áa]bado|domingo)\b", text, re.IGNORECASE)
    if weekend_word:
        target_weekday = 5 if re.match(r"s[áa]bado", weekend_word.group(1), re.IGNORECASE) else 6
        d = PROJECT_TODAY
        while d.weekday() != target_weekday:
            d += timedelta(days=1)
        return d

    return None


def is_update_intent(user_text: str) -> bool:
    """Detecta intención de modificar una reserva ya existente."""
    if not user_text:
        return False
    if is_reset_intent(user_text):
        return False
    return bool(re.search(
        r"\b(?:anade(?:me|melo)?|añade(?:me|melo)?|añademe|añádeme|añádemelo"
        r"|ponme(?:\s+tambi[eé]n)?|tambien|tambi[eé]n"
        r"|agrega(?:me)?|suma(?:me)?|incluye(?:me)?"
        r"|cambia(?:me)?|modifica(?:me|r)?|actualiza(?:me|r)?|mueve(?:me)?|reprograma(?:r)?)\b",
        user_text,
        re.IGNORECASE,
    ))


def is_add_service_intent(user_text: str) -> bool:
    if not user_text:
        return False
    return bool(re.search(
        r"\b(?:anade(?:me|melo)?|añade(?:me|melo)?|añademe|añádeme|añádemelo"
        r"|ponme(?:\s+tambi[eé]n)?|tambien|tambi[eé]n"
        r"|agrega(?:me)?|suma(?:me)?|incluye(?:me)?)\b",
        user_text,
        re.IGNORECASE,
    ))


def latest_booking_from_history(messages: List[ChatMessage]) -> Optional[dict]:
    for msg in reversed(messages):
        data = extract_booking_json(msg.content or "")
        if data and {"nombre", "servicio", "fecha", "hora"}.issubset(data.keys()):
            return {
                "nombre": data["nombre"],
                "servicio": normalize_servicio(data["servicio"]),
                "fecha": data["fecha"],
                "hora": data["hora"],
            }
    return None


def format_summary_with_json(booking: dict) -> str:
    payload = {
        "nombre": booking["nombre"],
        "servicio": normalize_servicio(booking["servicio"]),
        "fecha": booking["fecha"],
        "hora": booking["hora"],
    }
    return (
        "Aquí tienes el resumen actualizado:\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    )


def latest_pending_booking(db: Session, preferred_name: Optional[str] = None) -> Optional[dict]:
    query = db.query(Cita).filter(Cita.estado == "pendiente")
    if preferred_name:
        query = query.filter(Cita.nombre_cliente == preferred_name)
    cita = query.order_by(Cita.creada_en.desc(), Cita.id.desc()).first()
    if not cita:
        return None
    return {
        "nombre": cita.nombre_cliente,
        "servicio": cita.servicio_nombre,
        "fecha": cita.fecha,
        "hora": cita.hora,
    }


def hydrate_booking_for_update(raw_booking: Optional[dict], history: List[ChatMessage], db: Session) -> Optional[dict]:
    """
    Completa campos faltantes del JSON con la última reserva conocida para permitir updates
    como "añádeme peinado" sin perder fecha/hora ni nombre.
    """
    if not raw_booking:
        return None

    booking = dict(raw_booking)
    from_history = latest_booking_from_history(history)
    from_db = latest_pending_booking(db, preferred_name=booking.get("nombre"))
    base = from_history or from_db

    if base:
        if not booking.get("nombre") or not is_valid_booking_name(str(booking.get("nombre"))):
            booking["nombre"] = base.get("nombre")
        booking.setdefault("servicio", base.get("servicio"))
        booking.setdefault("fecha", base.get("fecha"))
        booking.setdefault("hora", base.get("hora"))

    return booking


def extract_last_sentences(text: str, n: int = 3) -> str:
    """
    Extrae las últimas N frases significativas de un texto.
    Fallback cuando el modelo no pone el marcador ### RESPUESTA:.
    """
    if not text:
        return ""
    try:
        text = _REASONING_BLOCK_RE.sub("", text)
        text = _CONTROL_TOKEN_RE.sub("", text)
        # Lookbehind de ancho FIJO — compatible con Python 3.13
        raw = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        clean = [s for s in raw if len(s) > 8 and not _HAS_REASONING_RE.search(s)]
        result = ' '.join(clean[-n:]) if clean else ''
        result = _JSON_BLOCK_RE.sub('', result)
        result = re.sub(r'###\s*RESPUESTA:\s*', '', result)
        return result.strip()
    except Exception as exc:
        print(f"[extract_last_sentences] Error: {exc}")
        return ""


def extract_smart_fallback(text: str) -> str:
    """
    Usado cuando el modelo olvida el marcador ### RESPUESTA:.
    Estrategia: buscar la última frase que contenga '?' (pregunta directa al cliente)
    o una despedida, ya que esas siempre son mensajes para el cliente, nunca razonamiento.
    Si no hay ninguna, devuelve la última frase no vacía.
    """
    if not text:
        return ""
    try:
        # Limpiar bloques de razonamiento y tokens de control primero
        cleaned = _REASONING_BLOCK_RE.sub("", text)
        cleaned = _CONTROL_TOKEN_RE.sub("", cleaned)
        cleaned = _JSON_BLOCK_RE.sub("", cleaned)
        cleaned = re.sub(r'###\s*RESPUESTA:\s*', '', cleaned)

        # Dividir en frases (lookbehind fijo, compatible Python 3.13)
        frases = [s.strip() for s in re.split(r'(?<=[.!?])\s+', cleaned) if s.strip()]

        # Filtrar frases de razonamiento
        frases = [f for f in frases if not _HAS_REASONING_RE.search(f) and len(f) > 8]

        if not frases:
            return ""

        # 1º: última frase con signo de interrogación (pregunta al cliente)
        preguntas = [f for f in frases if '?' in f or '\u00bf' in f]
        if preguntas:
            return preguntas[-1]

        # 2º: última frase que parezca despedida o confirmación
        despedidas_re = re.compile(
            r'(?:hasta|te espero|nos vemos|gracias|perfecto|genial|encantado|bienvenido)',
            re.IGNORECASE
        )
        despedidas = [f for f in frases if despedidas_re.search(f)]
        if despedidas:
            return despedidas[-1]

        # 3º: última frase no vacía como último recurso
        return frases[-1]

    except Exception as exc:
        print(f"[extract_smart_fallback] Error: {exc}")
        return ""


def clean_reply(text: str) -> str:
    """Pipeline completo de limpieza en 5 pasadas sobre la respuesta del LLM."""
    # Pre-procesado: extraer la respuesta final si el modelo divago
    text = extract_final_response(text)
    # Pasada 1: eliminar bloques de razonamiento con etiquetas XML
    text = _REASONING_BLOCK_RE.sub("", text)
    # Pasada 2: eliminar tokens de control de los distintos modelos
    text = _CONTROL_TOKEN_RE.sub("", text)
    # Pasada 3: eliminar líneas de razonamiento sin etiqueta
    text = _REASONING_LINE_RE.sub("", text)
    # Pasada 4: eliminar bloques/objetos JSON (el frontend los muestra como tarjeta)
    text = _JSON_BLOCK_RE.sub("", text)
    # Pasada 5: eliminar frases en inglés que se filtran del sistema
    text = _ENGLISH_LEAK_RE.sub("", text)
    # Normalización final
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_booking_json(text: str) -> Optional[dict]:
    """Extrae el primer bloque JSON válido de la respuesta del LLM."""
    patterns = [
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
        r"(\{[\s\S]*?\"nombre\"[\s\S]*?\})",
        r"(\{[^{}]*\"nombre\"[^{}]*\})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
    return None


def validate_booking(data: dict) -> Optional[str]:
    """Devuelve un mensaje de error si los datos son inválidos, None si son correctos."""
    required = {"nombre", "servicio", "fecha", "hora"}
    missing = required - set(data.keys())
    if missing:
        return f"Faltan campos: {missing}"

    if not is_valid_booking_name(data["nombre"]):
        return "ERR_NAME_INVALID"

    # Normalizar y validar servicio (incluye combinaciones dinámicas)
    components = parse_service_components(data["servicio"])
    if not components:
        return f"Servicio inválido tras normalizar: {data['servicio']}"
    servicio_normalizado = canonical_service_name(components)
    data = {**data, "servicio": servicio_normalizado.lower()}

    try:
        parsed_date = datetime.strptime(data["fecha"], "%Y-%m-%d").date()
        if parsed_date.weekday() >= 5:  # Sábado o Domingo
            return f"ERR_WEEKEND:{parsed_date.isoformat()}"
        if parsed_date < PROJECT_TODAY:
            return "La fecha no puede ser en el pasado."
    except ValueError:
        return "Formato de fecha incorrecto (YYYY-MM-DD)."

    try:
        h, m = map(int, data["hora"].split(":"))
        if not (10 <= h < 20):
            return "La hora debe estar entre 10:00 y 20:00."
    except (ValueError, AttributeError):
        return "Formato de hora incorrecto (HH:MM)."

    return None


SERVICE_ORDER = ["corte", "tinte", "peinado"]
SERVICE_DISPLAY = {
    "corte": "Corte",
    "tinte": "Tinte",
    "peinado": "Peinado",
}
SERVICE_PRICES = {
    "corte": 20,
    "tinte": 40,
    "peinado": 15,
}
SERVICIO_ALIAS_MAP = {
    # Corte
    "degradado": "corte",
    "corte de pelo": "corte",
    "corte de cabello": "corte",
    "arreglo": "corte",
    "arreglo de pelo": "corte",
    "rapado": "corte",
    "afeitado": "corte",
    "corte y barba": "corte",
    "pelo": "corte",
    # Tinte
    "coloración": "tinte",
    "coloracion": "tinte",
    "decoloración": "tinte",
    "decoloracion": "tinte",
    "mechas": "tinte",
    "luces": "tinte",
    "balayage": "tinte",
    "tinte de pelo": "tinte",
    "color": "tinte",
    # Peinado
    "recogido": "peinado",
    "styling": "peinado",
    "peinado de boda": "peinado",
    "peinado de fiesta": "peinado",
    "brushing": "peinado",
    "secado": "peinado",
}


def parse_service_components(raw: str) -> set[str]:
    """Extrae servicios base desde texto libre (corte/tinte/peinado)."""
    if not raw:
        return set()

    text = raw.strip().lower()
    components: set[str] = set()

    # Alias por frase (longitud descendente para priorizar coincidencias largas).
    for alias, base in sorted(SERVICIO_ALIAS_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in text:
            components.add(base)

    # Coincidencias directas.
    if re.search(r"\bcorte\b", text):
        components.add("corte")
    if re.search(r"\btinte\b", text):
        components.add("tinte")
    if re.search(r"\bpeinado\b", text):
        components.add("peinado")

    return components


def canonical_service_name(components: set[str]) -> str:
    ordered = [srv for srv in SERVICE_ORDER if srv in components]
    if not ordered:
        return ""
    labels = [SERVICE_DISPLAY[srv] for srv in ordered]
    return " y ".join(labels)


def normalize_servicio(raw: str) -> str:
    """Convierte cualquier alias o combinación al nombre oficial (incluye combos)."""
    components = parse_service_components(raw)
    if not components:
        return "Corte"
    return canonical_service_name(components)


def service_total_price_by_name(raw: str) -> int:
    components = parse_service_components(raw)
    if not components:
        return 0
    return sum(SERVICE_PRICES[srv] for srv in components)


def create_cita_from_booking(
    data: dict,
    db: Session,
    update_existing: bool = False,
    preserve_datetime: bool = False,
    merge_service: bool = False,
) -> Cita:
    """Crea y persiste una Cita. Si ya existe una idéntica (nombre+servicio+fecha+hora
    en estado 'pendiente'), devuelve la existente SIN duplicar."""
    nombre_servicio = normalize_servicio(data["servicio"])
    servicio = db.query(Servicio).filter(Servicio.nombre == nombre_servicio).first()
    nombre_cliente = data["nombre"].strip()
    fecha = data["fecha"]
    hora = data["hora"]

    # ── Guard anti-duplicado ───────────────────────────────────────────────────
    existente = (
        db.query(Cita)
        .filter(
            Cita.nombre_cliente == nombre_cliente,
            Cita.servicio_nombre == nombre_servicio,
            Cita.fecha == fecha,
            Cita.hora == hora,
            Cita.estado == "pendiente",
        )
        .first()
    )
    if existente:
        print(f"[Dedup] Cita id={existente.id} ya existe, no se duplica.")
        return existente

    # ── Upgrade servicio en la misma franja (cualquier combinación) ───────────
    existente_slot = (
        db.query(Cita)
        .filter(
            Cita.nombre_cliente == nombre_cliente,
            Cita.fecha == fecha,
            Cita.hora == hora,
            Cita.estado == "pendiente",
        )
        .first()
    )
    if existente_slot and existente_slot.servicio_nombre != nombre_servicio:
        existente_slot.servicio_nombre = nombre_servicio
        existente_slot.servicio_id = servicio.id if servicio else None
        db.commit()
        db.refresh(existente_slot)
        print(f"[Upgrade] Cita id={existente_slot.id} actualizada a {nombre_servicio}.")
        return existente_slot

    # ── Actualización explícita (cambio de hora/fecha/servicio) ───────────────
    if update_existing:
        ultima_cita = (
            db.query(Cita)
            .filter(
                Cita.nombre_cliente == nombre_cliente,
                Cita.estado == "pendiente",
            )
            .order_by(Cita.creada_en.desc(), Cita.id.desc())
            .first()
        )
        if ultima_cita:
            if merge_service:
                merged_components = parse_service_components(ultima_cita.servicio_nombre) | parse_service_components(nombre_servicio)
                merged_name = canonical_service_name(merged_components)
                if merged_name:
                    nombre_servicio = merged_name
                    servicio = db.query(Servicio).filter(Servicio.nombre == nombre_servicio).first()

            ultima_cita.servicio_nombre = nombre_servicio
            ultima_cita.servicio_id = servicio.id if servicio else None
            if preserve_datetime:
                fecha = ultima_cita.fecha
                hora = ultima_cita.hora
            ultima_cita.fecha = fecha
            ultima_cita.hora = hora
            db.commit()
            db.refresh(ultima_cita)
            print(f"[Update] Cita id={ultima_cita.id} modificada por intención del usuario.")
            return ultima_cita

    cita = Cita(
        nombre_cliente=nombre_cliente,
        servicio_nombre=nombre_servicio,
        servicio_id=servicio.id if servicio else None,
        fecha=fecha,
        hora=hora,
    )
    db.add(cita)
    db.commit()
    db.refresh(cita)
    return cita


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/", tags=["status"])
async def root():
    return {"message": "Corte Perfecto API activa 💈", "docs": "/docs"}


@app.get("/api/servicios", response_model=List[ServicioOut], tags=["servicios"])
def listar_servicios(db: Session = Depends(get_db)):
    return db.query(Servicio).all()


@app.get("/api/citas", response_model=List[CitaOut], tags=["citas"])
def listar_citas(db: Session = Depends(get_db)):
    return db.query(Cita).order_by(Cita.fecha, Cita.hora).all()


@app.post("/api/citas", response_model=CitaOut, status_code=201, tags=["citas"])
def crear_cita(cita_in: CitaCreate, db: Session = Depends(get_db)):
    """Crea una cita manualmente (también usado internamente por el chatbot)."""
    nombre_servicio = normalize_servicio(cita_in.servicio_nombre)
    servicio = db.query(Servicio).filter(Servicio.nombre == nombre_servicio).first()

    cita = Cita(
        nombre_cliente=cita_in.nombre_cliente,
        servicio_nombre=nombre_servicio,
        servicio_id=servicio.id if servicio else None,
        fecha=cita_in.fecha,
        hora=cita_in.hora,
        notas=cita_in.notas,
    )
    db.add(cita)
    db.commit()
    db.refresh(cita)
    return cita


@app.delete("/api/citas/{cita_id}", tags=["citas"])
def cancelar_cita(cita_id: int, db: Session = Depends(get_db)):
    cita = db.query(Cita).filter(Cita.id == cita_id).first()
    if not cita:
        raise HTTPException(status_code=404, detail="Cita no encontrada")
    cita.estado = "cancelada"
    db.commit()
    return {"message": f"Cita {cita_id} cancelada"}


@app.post("/api/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """
    Envía el historial de mensajes a LM Studio y devuelve la respuesta.
    Si la respuesta contiene un JSON de reserva válido, crea la cita en la BD.
    """
    # Fecha en español sin depender del locale del sistema operativo
    _MESES = ["","enero","febrero","marzo","abril","mayo","junio",
              "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    _DIAS_COMPLETO = [
        "Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"
    ]
    # Mantener consistencia con el calendario del proyecto (martes 7 de abril de 2026)
    _now = datetime(PROJECT_TODAY.year, PROJECT_TODAY.month, PROJECT_TODAY.day, 12, 0, 0)
    today = (
        f"{_DIAS_COMPLETO[_now.weekday()]} {_now.day} de "
        f"{_MESES[_now.month].capitalize()} de {_now.year}"
    )
    # Calcular días siguientes para el calendario
    from datetime import timedelta
    _tomorrow = _now + timedelta(days=1)
    _day_after = _now + timedelta(days=2)
    tomorrow  = f"{_DIAS_COMPLETO[_tomorrow.weekday()]} {_tomorrow.day} de {_MESES[_tomorrow.month].capitalize()}"
    day_after = f"{_DIAS_COMPLETO[_day_after.weekday()]} {_day_after.day} de {_MESES[_day_after.month].capitalize()}"
    # Próximos 5 días laborables
    next_working_days = []
    _d = _now
    while len(next_working_days) < 5:
        _d += timedelta(days=1)
        if _d.weekday() < 5:  # 0=lunes ... 4=viernes
            next_working_days.append(
                f"{_DIAS_COMPLETO[_d.weekday()]} {_d.day} de {_MESES[_d.month].capitalize()}"
            )
    next_working_days_str = ", ".join(next_working_days)
    # Calcular el próximo lunes (para sugerir cuando piden fin de semana)
    _d_monday = _now
    days_to_monday = (7 - _d_monday.weekday()) % 7 or 7  # si hoy es lunes, el lunes siguiente
    _d_monday = _d_monday + timedelta(days=days_to_monday)
    next_monday = f"{_DIAS_COMPLETO[0]} {_d_monday.day} de {_MESES[_d_monday.month].capitalize()}"
    # Si ya somos lunes, el siguiente lunes es en 7 días
    if _now.weekday() == 0:
        _d_monday2 = _now + timedelta(days=7)
        next_monday = f"{_DIAS_COMPLETO[0]} {_d_monday2.day} de {_MESES[_d_monday2.month].capitalize()}"

    user_message = last_user_message(request.messages)

    if is_today_query(user_message):
        return ChatResponse(response="Hoy es martes 7 de abril de 2026", cita_creada=None)

    if is_summary_intent(user_message):
        history_booking = latest_booking_from_history(request.messages)
        if history_booking:
            return ChatResponse(response=format_summary_with_json(history_booking), cita_creada=None)
        db_booking = latest_pending_booking(db)
        if db_booking:
            return ChatResponse(response=format_summary_with_json(db_booking), cita_creada=None)
        return ChatResponse(response="Ahora mismo no veo una reserva activa en el sistema.", cita_creada=None)

    # Regla dura: si el usuario corta la conversación, cerrar sin repreguntas.
    if is_closing_intent(user_message):
        return ChatResponse(response=GOODBYE_REPLY, cita_creada=None)

    # Regla dura: si pide fin de semana, bloquear sin preguntar hora.
    weekend_requested_date = detect_requested_weekend_date(user_message)
    if weekend_requested_date:
        return ChatResponse(response=weekend_block_message(weekend_requested_date), cita_creada=None)

    # Regla dura: información completa de una sola vez para horario/precios.
    if is_info_request(user_message):
        return ChatResponse(response=INFO_REPLY, cita_creada=None)

    # Si piden otra cita, ignorar contexto previo.
    messages_for_llm = request.messages
    if is_reset_intent(user_message):
        messages_for_llm = [ChatMessage(role="user", content=user_message)]

    # Construir el payload para LM Studio con role "system" (Llama)
    formatted_system_prompt = SYSTEM_PROMPT.format(
        today=today,
        tomorrow=tomorrow,
        day_after=day_after,
        next_working_days=next_working_days_str,
        next_monday=next_monday,
    )
    messages = [{"role": "system", "content": formatted_system_prompt}]
    for msg in messages_for_llm:
        if msg.role in {"user", "assistant"}:
            messages.append({"role": msg.role, "content": msg.content})

    # Stop sequences: cortan la generación si el modelo empieza razonamiento
    # o repite el turno del usuario (hallucination loop)
    STOP_SEQUENCES = [
        "<think>", "<thought>", "<thoughts>", "<thinking>",
        "<reasoning>", "<reflect>", "<reflection>",
        "<|im_start|>", "<|im_end|>",
        "[INST]", "</s>",
        "\nUser:", "\nUsuario:", "\nHuman:",
    ]

    payload = {
        "model": "local-model",
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 600,   # más margen para razonamiento + marcador + respuesta
        "stream": False,
        "stop": STOP_SEQUENCES,
    }

    # Llamada asíncrona a LM Studio
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{LM_STUDIO_URL}/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="No se puede conectar con LM Studio. Asegúrate de que está en ejecución en http://localhost:1234",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="LM Studio tardó demasiado en responder. El modelo puede estar cargando.",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Error en LM Studio: {e.response.text}")

    raw = response.json()

    # Extraer el texto de la respuesta — algunos modelos ponen el
    # contenido en 'content' y otros (thinking models) en 'reasoning_content'
    choice = raw["choices"][0]["message"]
    reply_raw = (
        choice.get("content")
        or choice.get("reasoning_content")
        or ""
    )

    # ── Extracción en 3 niveles ultra-robusta ────────────────────────────────
    print(f"[LLM raw] {len(reply_raw)} chars: {reply_raw[:200]!r}")

    MARKER = "### RESPUESTA:"

    if MARKER in reply_raw:
        # NIVEL 1: marcador encontrado — extraer lo que va después (ideal)
        reply_clean = reply_raw.split(MARKER)[-1].strip()
        reply_clean = strip_technical_lines(reply_clean)
        print(f"[Marker OK] {reply_clean[:80]!r}")
    else:
        print(f"[No marker] Usando smart fallback")

        # NIVEL 2 — smart: última pregunta/despedida del texto (nunca razonamiento)
        reply_clean = extract_smart_fallback(reply_raw)
        if reply_clean:
            print(f"[Smart fallback OK] {reply_clean[:80]!r}")

        # NIVEL 3 — limpieza completa del raw si el smart fallback no encontró nada
        if not reply_clean or len(reply_clean) < 10:
            reply_clean = clean_reply(reply_raw)
            print(f"[clean_reply fallback] {reply_clean[:80]!r}")

        # NIVEL 4 — heurística de párrafo final como último recurso
        if not reply_clean or len(reply_clean) < 10:
            reply_clean = extract_final_response(reply_raw).strip()
            print(f"[extract_final fallback] {reply_clean[:80]!r}")

    # Blindaje final anti-meta para todos los caminos de extracción
    reply_clean = strip_technical_lines(reply_clean)

    # Solo mensaje genérico si verdaderamente todo falló
    if not reply_clean or len(reply_clean.strip()) < 3:
        reply_clean = "¡Hola! Estoy aquí para ayudarte. ¿En qué puedo ayudarte hoy?"


    # Intentar extraer y guardar una reserva del mensaje
    cita_out = None
    update_intent = is_update_intent(user_message)
    add_service_intent = is_add_service_intent(user_message)
    booking_data = extract_booking_json(reply_clean)
    if booking_data:
        if update_intent:
            booking_data = hydrate_booking_for_update(booking_data, request.messages, db)

        requested_date = parse_requested_date(user_message, PROJECT_TODAY)
        if requested_date:
            booking_data["fecha"] = requested_date.isoformat()

        validation_error = validate_booking(booking_data)
        if not validation_error:
            try:
                cita = create_cita_from_booking(
                    booking_data,
                    db,
                    update_existing=update_intent,
                    preserve_datetime=add_service_intent,
                    merge_service=add_service_intent,
                )
                cita_out = CitaOut.model_validate(cita)
            except Exception as exc:
                print(f"[ERROR] No se pudo guardar la cita: {exc}")
        elif validation_error.startswith("ERR_WEEKEND:"):
            weekend_iso = validation_error.split(":", 1)[1]
            try:
                weekend_day = date.fromisoformat(weekend_iso)
                reply_clean = weekend_block_message(weekend_day)
            except ValueError:
                reply_clean = "Lo siento, el fin de semana cerramos. ¿Te viene mejor el viernes o el lunes?"
        elif validation_error == "ERR_NAME_INVALID":
            reply_clean = "¡Claro! ¿A nombre de quién pongo la reserva?"

    return ChatResponse(response=reply_clean, cita_creada=cita_out)

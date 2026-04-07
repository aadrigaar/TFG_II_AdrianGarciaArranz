/**
 * ChatWidget.js — Corte Perfecto
 *
 * Componente de chat que:
 *  1. Muestra un botón flotante con badge de notificación.
 *  2. Abre un panel de chat flotante animado.
 *  3. Gestiona el historial de mensajes y el estado de la conversación.
 *  4. Envía el historial al endpoint POST /api/chat del backend FastAPI.
 *  5. Detecta si la respuesta contiene una cita creada y muestra confirmación.
 *  6. Ofrece respuestas rápidas contextuales para guiar al usuario.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import './ChatWidget.css';

// ── Constantes ───────────────────────────────────────────────────────────────

const API_BASE = 'http://localhost:8000';

const WELCOME_MSG = {
  id: 0,
  role: 'assistant',
  content:
    '¡Hola! 👋 Soy el asistente virtual de **Corte Perfecto**. Puedo ayudarte a reservar una cita o resolver tus dudas.\n\n¿En qué puedo ayudarte hoy?',
  timestamp: new Date(),
};

const QUICK_REPLIES_INITIAL = [
  '📅 Quiero reservar una cita',
  '✂️ ¿Qué servicios ofrecéis?',
  '🕙 ¿Cuál es el horario?',
  '💶 ¿Cuánto cuesta un corte?',
];

const SERVICIO_PRECIOS_BASE = {
  corte: 20,
  tinte: 40,
  peinado: 15,
};

const GOODBYE_REPLY = '¡Entendido! Si me necesitas para otra cosa, aquí estaré. ¡Buen día!';

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Formatea fecha YYYY-MM-DD a formato legible */
function formatFecha(fecha) {
  try {
    const d = new Date(fecha + 'T12:00:00');
    return d.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  } catch {
    return fecha;
  }
}

/** Precio según nombre de servicio */
function getPrecio(servicio) {
  if (!servicio) return '—';
  const text = servicio.toLowerCase();
  const selected = new Set();
  if (/\bcorte\b/.test(text)) selected.add('corte');
  if (/\btinte\b|\bmechas?\b|\bcoloraci[oó]n\b|\bcolor\b/.test(text)) selected.add('tinte');
  if (/\bpeinado\b|\brecogido\b|\bbrushing\b|\bstyling\b/.test(text)) selected.add('peinado');
  const total = [...selected].reduce((sum, key) => sum + (SERVICIO_PRECIOS_BASE[key] || 0), 0);
  return total > 0 ? `${total}€` : '—';
}

/** Renderiza texto con **negrita** básica */
function renderText(text) {
  if (!text) return null;
  const parts = text.split(/\*\*(.*?)\*\*/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  );
}

/** Elimina bloques JSON y el marcador ### RESPUESTA: que pudieran escapar del backend */
function stripJsonFromText(text) {
  if (!text) return text;
  return text
    // Eliminar el marcador si el backend lo pasa sin filtrar
    .replace(/###\s*RESPUESTA:\s*/gi, '')
    // Eliminar bloques ```json ... ``` y ```...```
    .replace(/```(?:json)?[\s\S]*?```/gi, '')
    // Eliminar objetos JSON inline de reserva
    .replace(/\{[^{}]*"nombre"[^{}]*\}/gi, '')
    // Blindaje extra por si se cuela meta-discurso técnico
    .replace(/[^\n]*\b(?:usando|generando|enviando)\b[^\n]*\b(?:marcador|json)\b[^\n]*/gi, '')
    // Normalizar espacios en blanco sobrantes
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/** Extrae JSON de reserva desde el texto del asistente (fallback frontend) */
function extractBookingFromText(text) {
  if (!text) return null;
  const patterns = [
    /```json\s*(\{[\s\S]*?\})\s*```/i,
    /```\s*(\{[\s\S]*?\})\s*```/i,
    /(\{[^{}]*"nombre"[^{}]*\})/i,
  ];
  for (const pattern of patterns) {
    const match = text.match(pattern);
    if (!match) continue;
    try {
      return JSON.parse(match[1]);
    } catch {
      // Intentar siguiente patrón
    }
  }
  return null;
}

/** Convierte JSON de LLM ({nombre, servicio, fecha, hora}) al formato de tarjeta */
function normalizeBookingPayload(rawBooking, previousBooking = null) {
  if (!rawBooking) return null;

  // Caso backend: cita_creada ya viene normalizada
  if (rawBooking.nombre_cliente && rawBooking.servicio_nombre) {
    return {
      ...rawBooking,
      id: rawBooking.id ?? previousBooking?.id ?? Date.now(),
    };
  }

  // Caso LLM: JSON de confirmación
  if (rawBooking.nombre || rawBooking.servicio || rawBooking.fecha || rawBooking.hora) {
    return {
      id: previousBooking?.id ?? Date.now(),
      nombre_cliente: rawBooking.nombre || previousBooking?.nombre_cliente || '',
      servicio_nombre: rawBooking.servicio || previousBooking?.servicio_nombre || '',
      fecha: rawBooking.fecha || previousBooking?.fecha || '',
      hora: rawBooking.hora || previousBooking?.hora || '',
    };
  }

  return null;
}

/** Mezcla datos nuevos sobre la reserva previa para no perder contexto */
function mergeBooking(previousBooking, incomingBooking) {
  if (!incomingBooking) return previousBooking;
  if (!previousBooking) return incomingBooking;
  return {
    ...previousBooking,
    ...incomingBooking,
    id: incomingBooking.id ?? previousBooking.id ?? Date.now(),
    nombre_cliente: incomingBooking.nombre_cliente || previousBooking.nombre_cliente,
    servicio_nombre: incomingBooking.servicio_nombre || previousBooking.servicio_nombre,
    fecha: incomingBooking.fecha || previousBooking.fecha,
    hora: incomingBooking.hora || previousBooking.hora,
  };
}

// ── Sub-componentes ──────────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="chat-typing">
      <div className="chat-typing-avatar">💈</div>
      <div className="chat-typing-bubble">
        <div className="typing-dot" />
        <div className="typing-dot" />
        <div className="typing-dot" />
      </div>
    </div>
  );
}

function BookingCard({ cita }) {
  return (
    <div className="chat-booking-card">
      <div className="chat-booking-title">✅ Cita confirmada</div>
      <div className="chat-booking-row"><span>👤 Nombre</span><span>{cita.nombre_cliente}</span></div>
      <div className="chat-booking-row"><span>✂️ Servicio</span><span>{cita.servicio_nombre}</span></div>
      <div className="chat-booking-row"><span>📅 Fecha</span><span>{formatFecha(cita.fecha)}</span></div>
      <div className="chat-booking-row"><span>🕙 Hora</span><span>{cita.hora}</span></div>
      <div className="chat-booking-row"><span>💶 Precio</span><span>{getPrecio(cita.servicio_nombre)}</span></div>
      <div className="chat-booking-row"><span>🆔 Ref.</span><span>#{cita.id}</span></div>
    </div>
  );
}

function ChatMessage({ msg, booking }) {
  const isUser = msg.role === 'user';

  let visibleText = msg.content;

  if (!isUser) {
    // Siempre limpiar marcadores y JSON del texto del bot
    visibleText = stripJsonFromText(visibleText);

    if (msg.cita) {
      // Si hay tarjeta de cita: el texto se sustituye por frase de confirmación
      // solo si no queda nada útil tras limpiar el JSON
      visibleText = visibleText || '¡Perfecto! He registrado tu cita. Aquí tienes el resumen 👇';
    }
  }

  return (
    <div className={`chat-msg ${isUser ? 'user' : 'bot'}`}>
      <div className="chat-msg-avatar">
        {isUser ? '🧑' : '💈'}
      </div>
      <div className="chat-msg-body">
        {/* Solo renderizar burbuja si hay texto visible */}
        {visibleText && (
          <div className="chat-bubble">
            {renderText(visibleText)}
          </div>
        )}
        {/* Tarjeta de confirmación cuando hay cita */}
        {msg.cita && booking && <BookingCard cita={booking} />}
      </div>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function ChatWidget({ isOpen, setIsOpen }) {
  const [messages, setMessages] = useState([WELCOME_MSG]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showBadge, setShowBadge] = useState(true);
  const [quickReplies, setQuickReplies] = useState(QUICK_REPLIES_INITIAL);
  const [booking, setBooking] = useState(null);

  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const msgIdRef = useRef(1);
  const bookingMsgIdRef = useRef(null);

  // Auto-scroll al último mensaje
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Focus en el input al abrir
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 350);
      setShowBadge(false);
    }
  }, [isOpen]);

  const addMessage = useCallback((role, content, extra = {}) => {
    setMessages((prev) => [
      ...prev,
      { id: msgIdRef.current++, role, content, timestamp: new Date(), ...extra },
    ]);
  }, []);

  const upsertBookingMessage = useCallback((content, cita) => {
    setMessages((prev) => {
      let updated = false;
      const next = prev.map((m) => {
        if (bookingMsgIdRef.current && m.id === bookingMsgIdRef.current) {
          updated = true;
          return { ...m, content, cita };
        }
        if (m.cita) {
          return { ...m, cita: null };
        }
        return m;
      });

      if (!updated) {
        const newMsg = {
          id: msgIdRef.current++,
          role: 'assistant',
          content,
          timestamp: new Date(),
          cita,
        };
        bookingMsgIdRef.current = newMsg.id;
        return [...next, newMsg];
      }
      return next;
    });
  }, []);

  const clearBookingCard = useCallback(() => {
    setBooking(null);
    bookingMsgIdRef.current = null;
    setMessages((prev) => prev.map((m) => (m.cita ? { ...m, cita: null } : m)));
  }, []);

  const resetConversationView = useCallback(() => {
    clearBookingCard();
    setMessages([WELCOME_MSG]);
    setQuickReplies(QUICK_REPLIES_INITIAL);
    setError(null);
    setInput('');
  }, [clearBookingCard]);

  /** Envía el mensaje al backend y procesa la respuesta */
  const sendMessage = useCallback(
    async (text) => {
      const trimmed = text.trim();
      if (!trimmed || isLoading) return;

      // ── "Reservar otra cita" → limpiar historial completo ─────────────────
      const isNewBooking = /reservar otra cita|otra cita|nueva cita|nueva reserva|reservar otra/i.test(trimmed);
      if (isNewBooking) {
        // Resetear a solo el mensaje de bienvenida y arrancar desde cero
        resetConversationView();
        // Inyectar el mensaje del usuario ya en el historial limpio
        const resetMsg = { id: msgIdRef.current++, role: 'user', content: trimmed, timestamp: new Date() };
        setMessages([WELCOME_MSG, resetMsg]);
      }

      setError(null);
      setQuickReplies([]);
      if (!isNewBooking) addMessage('user', trimmed);
      setInput('');
      setIsLoading(true);

      // Construir historial — si es nueva reserva, solo el mensaje actual
      const historial = isNewBooking
        ? [{ role: 'user', content: trimmed }]
        : messages
            .filter((m) => m.id !== 0)
            .map((m) => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.content }))
            .concat([{ role: 'user', content: trimmed }]);

      try {
        const res = await fetch(`${API_BASE}/api/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: historial }),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Error HTTP ${res.status}`);
        }

        const data = await res.json();
        const { response, cita_creada } = data;

        // Guardia: nunca mostrar una burbuja vacía
        const texto = response || '(Sin respuesta del servidor. Comprueba la consola del backend.)';
        const bookingFromText = extractBookingFromText(texto);
        const normalizedServerBooking = normalizeBookingPayload(cita_creada, booking);
        const normalizedTextBooking = normalizeBookingPayload(bookingFromText, booking);
        const incomingBooking = normalizedServerBooking || normalizedTextBooking;

        if (incomingBooking) {
          const mergedBooking = mergeBooking(booking, incomingBooking);
          setBooking(mergedBooking);
          upsertBookingMessage(texto, mergedBooking);
        } else {
          addMessage('assistant', texto);
        }

        // Quick replies contextuales
        if (texto.trim() === GOODBYE_REPLY) {
          setQuickReplies([]);
        } else if (!incomingBooking) {
          setQuickReplies(['📅 Reservar otra cita', '❓ Más información']);
        } else {
          setQuickReplies(['📅 Reservar otra cita', '✅ Gracias']);
        }
      } catch (err) {
        console.error('[ChatWidget] Error:', err);
        setError(
          err.message.includes('Failed to fetch')
            ? '⚡ No se puede conectar al servidor. ¿Está el backend en ejecución?'
            : err.message
        );
        setQuickReplies(QUICK_REPLIES_INITIAL);
      } finally {
        setIsLoading(false);
        setTimeout(() => inputRef.current?.focus(), 100);
      }
    },
    [isLoading, messages, addMessage, booking, upsertBookingMessage, resetConversationView]
  );


  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const handleQuickReply = (text) => {
    const isNewBookingQuick = /reservar otra cita|otra cita|nueva cita|nueva reserva|reservar otra/i.test(text);
    if (isNewBookingQuick) {
      resetConversationView();
    }
    sendMessage(text);
  };

  return (
    <>
      {/* Botón flotante */}
      <button
        id="chat-trigger"
        className={`chat-trigger-btn ${isOpen ? 'open' : ''}`}
        onClick={() => setIsOpen((v) => !v)}
        aria-label={isOpen ? 'Cerrar chat' : 'Abrir chat de reservas'}
        title={isOpen ? 'Cerrar' : 'Asistente IA — Reservar cita'}
      >
        {isOpen ? '✕' : '💬'}
        {showBadge && !isOpen && <span className="chat-badge">1</span>}
      </button>

      {/* Panel de chat */}
      <div className={`chat-panel ${isOpen ? 'visible' : ''}`} role="dialog" aria-label="Chat de reservas">

        {/* Header */}
        <div className="chat-header">
          <div className="chat-avatar">💈</div>
          <div className="chat-header-info">
            <div className="chat-header-name">Asistente Corte Perfecto</div>
            <div className="chat-header-status">
              <div className="chat-status-dot" />
              <span>En línea · Powered by IA local</span>
            </div>
          </div>
          <button className="chat-close-btn" onClick={() => setIsOpen(false)} aria-label="Cerrar chat">
            ✕
          </button>
        </div>

        {/* Messages */}
        <div className="chat-messages" role="log" aria-live="polite">
          {messages.map((msg) => (
            <ChatMessage key={msg.id} msg={msg} booking={booking} />
          ))}
          {isLoading && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* Error */}
        {error && (
          <div className="chat-error">
            ⚠️ {error}
          </div>
        )}

        {/* Quick Replies */}
        {quickReplies.length > 0 && !isLoading && (
          <div className="chat-quick-replies" role="group" aria-label="Respuestas rápidas">
            {quickReplies.map((qr) => (
              <button
                key={qr}
                className="chat-quick-reply"
                onClick={() => handleQuickReply(qr)}
              >
                {qr}
              </button>
            ))}
          </div>
        )}

        {/* Input */}
        <div className="chat-input-area">
          <textarea
            ref={inputRef}
            className="chat-input"
            placeholder="Escribe tu mensaje..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={1}
            aria-label="Mensaje para el asistente"
          />
          <button
            className="chat-send-btn"
            onClick={() => sendMessage(input)}
            disabled={isLoading || !input.trim()}
            aria-label="Enviar mensaje"
          >
            ➤
          </button>
        </div>
      </div>
    </>
  );
}

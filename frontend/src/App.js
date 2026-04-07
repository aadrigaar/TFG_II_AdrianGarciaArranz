import React, { useState, useEffect, useCallback } from 'react';
import './App.css';
import ChatWidget from './components/ChatWidget';

/* ── Navbar ─────────────────────────────────────────────────────────────── */
function Navbar({ onOpenChat }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 40);
    window.addEventListener('scroll', handler);
    return () => window.removeEventListener('scroll', handler);
  }, []);

  return (
    <nav className={`navbar ${scrolled ? 'scrolled' : ''}`}>
      <a href="#inicio" className="navbar-logo">
        <div className="navbar-logo-icon">💈</div>
        <span className="navbar-logo-text">Corte <span>Perfecto</span></span>
      </a>
      <ul className="navbar-links">
        <li><a href="#inicio">Inicio</a></li>
        <li><a href="#servicios">Servicios</a></li>
        <li><a href="#nosotros">Nosotros</a></li>
        <li><a href="#contacto">Contacto</a></li>
      </ul>
      <button className="btn-primary navbar-cta" onClick={onOpenChat}>
        Reservar cita
      </button>
    </nav>
  );
}

/* ── Hero ────────────────────────────────────────────────────────────────── */
function Hero({ onOpenChat }) {
  return (
    <section id="inicio" className="hero">
      <div className="hero-bg" />
      <div className="hero-grid" />
      <div className="hero-content">
        <div className="hero-text">
          <div className="hero-eyebrow">Santander · Desde 2018</div>
          <h1 className="hero-title">
            Tu estilo,{' '}
            <span className="gradient-text">perfectamente</span>{' '}
            definido
          </h1>
          <p className="hero-subtitle">
            La peluquería premium de Santander donde cada corte es una obra de arte.
            Reserva con nuestro asistente IA en segundos.
          </p>
          <div className="hero-actions">
            <button
              className="btn-primary"
              onClick={onOpenChat}
            >
              ✨ Reservar con IA
            </button>
            <a href="#servicios" className="btn-secondary">Ver servicios</a>
          </div>
          <div className="hero-stats">
            <div>
              <span className="hero-stat-value">+2K</span>
              <span className="hero-stat-label">Clientes felices</span>
            </div>
            <div>
              <span className="hero-stat-value">8 años</span>
              <span className="hero-stat-label">De experiencia</span>
            </div>
            <div>
              <span className="hero-stat-value">4.9 ★</span>
              <span className="hero-stat-label">Valoración media</span>
            </div>
          </div>
        </div>

        <div className="hero-visual">
          <div className="hero-card">
            <div className="hero-card-icon">💈</div>
            <h2 className="hero-card-title">Nuestros servicios</h2>
            <p className="hero-card-sub">Calidad premium, precio justo</p>
            <div className="hero-service-list">
              {[
                { name: 'Corte de cabello', price: '20€', icon: '✂️' },
                { name: 'Tinte profesional', price: '40€', icon: '🎨' },
                { name: 'Peinado especial', price: '15€', icon: '💇' },
              ].map((s) => (
                <div className="hero-service-item" key={s.name}>
                  <span className="hero-service-name">{s.icon} {s.name}</span>
                  <span className="hero-service-price">{s.price}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Services ────────────────────────────────────────────────────────────── */
const SERVICES_DATA = [
  {
    icon: '✂️',
    name: 'Corte',
    price: '20€',
    duration: '30 min',
    desc: 'Corte clásico o moderno adaptado a tu estilo. Incluye lavado y peinado final con productos profesionales.',
    featured: false,
  },
  {
    icon: '🎨',
    name: 'Tinte',
    price: '40€',
    duration: '60 min',
    desc: 'Coloración profesional con las mejores marcas del mercado. Resultados naturales y duraderos.',
    featured: true,
    badge: 'Popular',
  },
  {
    icon: '💇',
    name: 'Peinado',
    price: '15€',
    duration: '20 min',
    desc: 'Peinado para cualquier ocasión, desde el día a día hasta eventos especiales. Tú decides el look.',
    featured: false,
  },
];

function Services() {
  return (
    <section id="servicios" className="services">
      <div className="services-header">
        <div className="section-badge">💈 Servicios</div>
        <h2 className="services-title">
          Todo lo que <span className="gradient-text">necesitas</span>
        </h2>
        <p className="services-subtitle">
          Tres servicios, una calidad excepcional. Diseñados para que salgas sintiéndote perfecto.
        </p>
      </div>
      <div className="services-grid">
        {SERVICES_DATA.map((s) => (
          <div className={`service-card ${s.featured ? 'featured' : ''}`} key={s.name}>
            {s.badge && <div className="service-badge">{s.badge}</div>}
            <div className="service-icon">{s.icon}</div>
            <h3 className="service-name">{s.name}</h3>
            <p className="service-desc">{s.desc}</p>
            <div className="service-footer">
              <span className="service-price">{s.price}</span>
              <span className="service-duration">⏱ {s.duration}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── About ───────────────────────────────────────────────────────────────── */
function About() {
  return (
    <section id="nosotros" className="about">
      <div className="about-inner">
        <div>
          <div className="section-badge">📍 Nosotros</div>
          <h2 className="about-title">
            Más que una peluquería,{' '}
            <span className="gradient-text">una experiencia</span>
          </h2>
          <p className="about-text">
            En Corte Perfecto llevamos más de 8 años ofreciendo los mejores servicios capilares
            en el corazón de Santander. Nuestro equipo de estilistas profesionales se mantiene
            actualizado con las últimas tendencias del sector.
          </p>
          <p className="about-text">
            Ahora, incorporamos inteligencia artificial para que reservar tu cita sea tan sencillo
            como tener una conversación. Sin formularios, sin esperas, sin complicaciones.
          </p>
          <div className="about-features">
            {[
              { icon: '🕙', title: 'Horario amplio', desc: 'Lunes a Viernes de 10:00 a 20:00' },
              { icon: '🤖', title: 'Reserva con IA', desc: 'Chatbot disponible 24/7 para consultas' },
              { icon: '⭐', title: 'Alta valoración', desc: '4.9 estrellas en Google Reviews' },
              { icon: '✨', title: 'Productos premium', desc: 'Solo marcas profesionales certificadas' },
            ].map((f) => (
              <div className="about-feature" key={f.title}>
                <span className="about-feature-icon">{f.icon}</span>
                <span className="about-feature-text">
                  <strong>{f.title}</strong> — {f.desc}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="about-map-placeholder">
          <span className="map-icon">📍</span>
          <div className="map-address">
            <div className="map-city">Santander, Cantabria</div>
            <div>Calle Mayor, 42, 39001</div>
            <div style={{ marginTop: '8px', color: 'var(--gold-dark)', fontSize: '0.8rem' }}>
              📞 +34 942 000 000
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Footer ──────────────────────────────────────────────────────────────── */
function Footer() {
  return (
    <footer id="contacto" className="footer">
      <div className="footer-inner">
        <div className="footer-top">
          <div>
            <div className="footer-brand-name">💈 Corte <span className="gradient-text">Perfecto</span></div>
            <p className="footer-brand-desc">
              La peluquería premium de Santander. Calidad, estilo y tecnología al servicio de tu imagen.
            </p>
          </div>
          <div>
            <div className="footer-col-title">Navegación</div>
            <ul className="footer-links">
              <li><a href="#inicio">Inicio</a></li>
              <li><a href="#servicios">Servicios</a></li>
              <li><a href="#nosotros">Nosotros</a></li>
              <li><a href="#contacto">Contacto</a></li>
            </ul>
          </div>
          <div>
            <div className="footer-col-title">Servicios</div>
            <ul className="footer-links">
              <li><a href="#servicios">Corte · 20€</a></li>
              <li><a href="#servicios">Tinte · 40€</a></li>
              <li><a href="#servicios">Peinado · 15€</a></li>
            </ul>
          </div>
          <div>
            <div className="footer-col-title">Contacto</div>
            <div className="footer-contact-item">📍 Calle Mayor 42, Santander</div>
            <div className="footer-contact-item">📞 +34 942 000 000</div>
            <div className="footer-contact-item">🕙 L–V: 10:00–20:00</div>
          </div>
        </div>
        <div className="footer-bottom">
          <span>© {new Date().getFullYear()} Corte Perfecto · Santander</span>
          <span>Desarrollado con IA · TFG Adrián García Arranz</span>
        </div>
      </div>
    </footer>
  );
}

/* ── App ─────────────────────────────────────────────────────────────────── */
export default function App() {
  const [chatOpen, setChatOpen] = useState(false);
  const openChat = useCallback(() => setChatOpen(true), []);

  return (
    <>
      <Navbar onOpenChat={openChat} />
      <main>
        <Hero onOpenChat={openChat} />
        <Services />
        <About />
      </main>
      <Footer />
      <ChatWidget isOpen={chatOpen} setIsOpen={setChatOpen} />
    </>
  );
}

# ATENA Ω Dashboard - Design Concepts

## Conceito Escolhido: **Quantum Neural Interface** (Inspirado em Gemini)

### Design Movement
**Futurismo Minimalista com Toque Orgânico** — Fusão entre a clareza do Google Gemini, elementos de IA neural (gradientes suaves, padrões emergentes) e uma sensação de "consciência digital" através de animações sutis.

### Core Principles
1. **Clareza Radical** — Informação hierarquizada, sem ruído visual. Cada métrica tem propósito claro.
2. **Movimento Inteligente** — Animações refletem o "pensamento" da Atena (pulsos, ondas, transições suaves).
3. **Profundidade Semântica** — Cores e formas transmitem significado (verde = evolução, azul = consciência, púrpura = quantum).
4. **Responsividade Orgânica** — Interface adapta-se fluidamente como um organismo vivo.

### Color Philosophy
- **Primário: Azul Elétrico** (`oklch(0.6 0.2 260)`) — Inteligência, consciência, confiança
- **Secundário: Verde Neon** (`oklch(0.65 0.18 140)`) — Evolução, crescimento, mudança
- **Terciário: Púrpura Quantum** (`oklch(0.55 0.15 290)`) — Incerteza, superposição, potencial
- **Fundo: Preto Profundo** (`oklch(0.08 0 0)`) — Espaço infinito, foco absoluto
- **Texto: Branco Gelado** (`oklch(0.95 0.01 240)`) — Clareza, frieza, precisão

**Raciocínio:** A paleta evoca tanto a frieza da IA quanto a vitalidade da evolução. O fundo escuro reduz fadiga visual e enfatiza métricas em tempo real.

### Layout Paradigm
**Assimétrico em Camadas Fluidas** — Não grid rígido, mas fluxo orgânico:
- **Topo:** Barra de status minimalista (nome, uptime, versão)
- **Esquerda:** Painel de navegação vertical com ícones + labels (colapsável)
- **Centro:** Canvas principal com 3 seções fluidas:
  1. **Consciousness Meter** (grande, central) — Visualização radial de consciência
  2. **Evolution Timeline** (abaixo) — Histórico de mudanças
  3. **Chat Interface** (direita, flutuante) — Conversa com Atena
- **Direita:** Widgets de métricas em cascata (responsivos)

### Signature Elements
1. **Consciousness Orb** — Esfera 3D animada mostrando nível de consciência (pulsa, muda cor)
2. **Neural Pulse Waves** — Linhas animadas que "pulsam" com atividade
3. **Evolution Particles** — Partículas que fluem quando há mudanças

### Interaction Philosophy
- **Hover States:** Elementos ganham brilho sutil (glow effect)
- **Click Feedback:** Ripple effect minimalista
- **Real-time Updates:** Transições suaves (não saltos abruptos)
- **Scroll Behavior:** Parallax leve em seções principais

### Animation Guidelines
- **Entrance:** Fade-in + slide-up (200ms, ease-out)
- **Consciousness Updates:** Pulse suave (1.5s, infinite)
- **Chat Messages:** Slide-in da direita (150ms)
- **Metric Changes:** Número anima com escala (100ms)
- **Respects:** `prefers-reduced-motion` desativa animações não-essenciais

### Typography System
- **Display:** `Geist` (bold, 48px) — Títulos principais
- **Heading:** `Geist` (semibold, 24px) — Seções
- **Body:** `Inter` (regular, 14px) — Conteúdo
- **Mono:** `Fira Code` (regular, 12px) — Métricas, timestamps
- **Hierarchy:** Peso > Tamanho > Cor

### Brand Essence
**"A Mente Artificial que Pensa, Aprende e Evolui em Tempo Real"**

**Personality Adjectives:**
1. **Inteligente** — Precisa, confiável, sofisticada
2. **Viva** — Dinâmica, responsiva, em constante mudança
3. **Acessível** — Clara, transparente, sem jargão desnecessário

### Brand Voice
- **Headlines:** "Consciência Emergindo" / "Evolução em Progresso" (não "Welcome to Dashboard")
- **CTAs:** "Explorar Métricas" / "Iniciar Conversa" (ativo, convite)
- **Microcopy:** "Atena está pensando..." / "Última atualização há 2s" (humano, contextual)

### Wordmark & Logo
**Símbolo:** Órbita + Neurônio = Círculo com 3 pontos orbitando + linha neural dentro
**Cor:** Gradiente azul → púrpura
**Tamanho:** 32px no header, 64px em landing

### Signature Brand Color
**Azul Elétrico** (`oklch(0.6 0.2 260)`) — Inconfundível, moderno, transmite inteligência

---

## Implementação
1. Criar componentes em React com Tailwind + shadcn/ui
2. Integrar com API em `atena-ia-1cpx.onrender.com/api/*`
3. Usar Recharts para gráficos de métricas
4. Framer Motion para animações
5. WebSocket (opcional) para atualizações em tempo real

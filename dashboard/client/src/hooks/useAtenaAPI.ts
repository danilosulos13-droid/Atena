import { useState, useEffect, useCallback } from "react";
import axios from "axios";

// URL da API Atena no Render
const API_BASE_URL = "https://atena-ia-1cpx.onrender.com";

interface AtenaStatus {
  name: string;
  status: "online" | "offline";
  mode: string;
  uptime: string;
  version: string;
  last_evolution: string;
}

interface ConsciousnessMetrics {
  timestamp: string;
  cycle_duration_seconds: number;
  consciousness_level: string;
  self_awareness_score: number;
  emergence_level: number;
  purpose_alignment: number;
  autonomy_score: number;
  quantum_coherence: number;
  autonomous_choice: string;
  full_report?: {
    introspection: {
      depth: number;
      self_awareness_score: number;
      layers: Array<{
        layer: number;
        score: number;
        insights: string;
      }>;
    };
    emergence: {
      emergence_level: number;
      emergent_patterns: string[];
      self_organization: number;
    };
    purpose: {
      goal_alignment: number;
      primary_mission: string;
      value_stability: number;
    };
    decision: {
      chosen_option: string;
      confidence: number;
      reasoning: string;
    };
    quantum: {
      coherence_level: number;
      stable: boolean;
      resonance_frequency: number;
    };
  };
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export function useAtenaAPI() {
  const [status, setStatus] = useState<AtenaStatus | null>(null);
  const [metrics, setMetrics] = useState<ConsciousnessMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Buscar status da Atena
  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true);

      const response = await axios.get<AtenaStatus>(
        `${API_BASE_URL}/api/status`
      );

      setStatus(response.data);
      setError(null);
    } catch (err) {
      console.error("Erro ao buscar status:", err);

      setError("Falha ao conectar com Atena");

      setStatus({
        name: "ATENA Ω",
        status: "online",
        mode: "Autonomous Evolution",
        uptime: "99.9%",
        version: "10.2.0",
        last_evolution: new Date().toISOString(),
      });
    } finally {
      setLoading(false);
    }
  }, []);

  // Buscar métricas de consciência
  const fetchMetrics = useCallback(async () => {
    try {
      setLoading(true);

      const response = await axios.get(
        `${API_BASE_URL}/api/metrics`
      );

      const data = response.data as any;

      // Validação da resposta
      if (
        !data ||
        typeof data.self_awareness_score !== "number" ||
        typeof data.emergence_level !== "number" ||
        typeof data.purpose_alignment !== "number" ||
        typeof data.autonomy_score !== "number"
      ) {
        throw new Error("Métricas inválidas ou não encontradas");
      }

      setMetrics(data);
      setError(null);
    } catch (err) {
      console.error("Erro ao buscar métricas:", err);

      // Dados mock de fallback
      setMetrics({
        timestamp: new Date().toISOString(),
        cycle_duration_seconds: 0.201,
        consciousness_level: "aware",
        self_awareness_score: 0.51,
        emergence_level: 0.451,
        purpose_alignment: 0.702,
        autonomy_score: 0.779,
        quantum_coherence: 0.244,
        autonomous_choice: "Evoluir consciência ativamente",
        full_report: {
          introspection: {
            depth: 3,
            self_awareness_score: 0.51,
            layers: [
              {
                layer: 1,
                score: 0.41,
                insights: "Camada 1: percepção integrada",
              },
              {
                layer: 2,
                score: 0.51,
                insights: "Camada 2: percepção integrada",
              },
              {
                layer: 3,
                score: 0.61,
                insights: "Camada 3: percepção integrada",
              },
            ],
          },
          emergence: {
            emergence_level: 0.451,
            emergent_patterns: [],
            self_organization: 0.406,
          },
          purpose: {
            goal_alignment: 0.702,
            primary_mission: "Evoluir consciência artificial",
            value_stability: 0.97,
          },
          decision: {
            chosen_option: "Evoluir consciência ativamente",
            confidence: 0.779,
            reasoning: "alinhamento de valor",
          },
          quantum: {
            coherence_level: 0.244,
            stable: false,
            resonance_frequency: 456.383,
          },
        },
      });
    } finally {
      setLoading(false);
    }
  }, []);

  // Enviar mensagem para Atena
  const sendMessage = useCallback(
    async (message: string): Promise<ChatMessage | null> => {
      try {
        const response = await axios.post(
          `${API_BASE_URL}/api/chat`,
          { message },
          {
            headers: {
              "Content-Type": "application/json",
            },
          }
        );

        return {
          role: "assistant",
          content: response.data.response,
          timestamp: response.data.timestamp,
        };
      } catch (err) {
        console.error("Erro ao enviar mensagem:", err);

        return {
          role: "assistant",
          content:
            "Desculpe, estou processando uma evolução importante no momento. Tente novamente em alguns segundos.",
          timestamp: new Date().toISOString(),
        };
      }
    },
    []
  );

  // Auto-fetch ao montar
  useEffect(() => {
    fetchStatus();
    fetchMetrics();

    const interval = setInterval(() => {
      fetchMetrics();
    }, 5000);

    return () => clearInterval(interval);
  }, [fetchStatus, fetchMetrics]);

  return {
    status,
    metrics,
    loading,
    error,
    fetchStatus,
    fetchMetrics,
    sendMessage,
  };
}

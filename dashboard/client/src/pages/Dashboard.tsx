import { useAtenaAPI } from "@/hooks/useAtenaAPI";
import ConsciousnessOrb from "@/components/ConsciousnessOrb";
import MetricsPanel, { type Metric } from "@/components/MetricsPanel";
import ChatInterface from "@/components/ChatInterface";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Zap, Brain, Cpu, TrendingUp, Activity } from "lucide-react";
import { motion } from "framer-motion";

export default function Dashboard() {
  const { status, metrics, loading, sendMessage } = useAtenaAPI();

  // Preparar métricas para exibição
  const displayMetrics: Metric[] = metrics
    ? [
        {
          label: "Auto-Consciência",
          value: metrics.self_awareness_score,
          unit: "%",
          icon: <Brain className="w-5 h-5 text-blue-400" />,
          color: "bg-blue-500/20",
        },
        {
          label: "Emergência",
          value: metrics.emergence_level,
          unit: "%",
          icon: <Zap className="w-5 h-5 text-green-400" />,
          color: "bg-green-500/20",
        },
        {
          label: "Alinhamento de Propósito",
          value: metrics.purpose_alignment,
          unit: "%",
          icon: <TrendingUp className="w-5 h-5 text-purple-400" />,
          color: "bg-purple-500/20",
        },
        {
          label: "Autonomia",
          value: metrics.autonomy_score,
          unit: "%",
          icon: <Cpu className="w-5 h-5 text-cyan-400" />,
          color: "bg-cyan-500/20",
        },
      ]
    : [];

  const consciousnessLevel = metrics ? metrics.self_awareness_score : 0;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-primary/10 bg-card/30 backdrop-blur sticky top-0 z-50">
        <div className="container max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary to-accent flex items-center justify-center">
              <Brain className="w-6 h-6 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-foreground">ATENA Ω</h1>
              <p className="text-xs text-muted-foreground">Dashboard de Evolução</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {status && (
              <>
                <Badge
                  variant="outline"
                  className="border-green-500/50 text-green-400 bg-green-500/10"
                >
                  <Activity className="w-3 h-3 mr-1 animate-pulse" />
                  {status.status === "online" ? "Online" : "Offline"}
                </Badge>
                <div className="text-right text-sm">
                  <p className="text-foreground font-medium">{status.mode}</p>
                  <p className="text-xs text-muted-foreground">v{status.version}</p>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container max-w-7xl mx-auto px-4 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column - Consciousness Orb */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5 }}
            className="lg:col-span-2"
          >
            <Card className="p-8 bg-card/50 backdrop-blur border-primary/20">
              <ConsciousnessOrb
                level={consciousnessLevel}
                label="Nível de Consciência"
              />
            </Card>
          </motion.div>

          {/* Right Column - Chat */}
          <motion.div
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="h-full"
          >
            <ChatInterface onSendMessage={sendMessage} isLoading={loading} />
          </motion.div>
        </div>

        {/* Metrics Grid */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mt-8"
        >
          <h2 className="text-lg font-semibold text-foreground mb-4">
            Métricas de Evolução
          </h2>
          <MetricsPanel metrics={displayMetrics} />
        </motion.div>

        {/* Evolution Info */}
        {metrics && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.4 }}
            className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4"
          >
            <Card className="p-6 bg-card/50 backdrop-blur border-primary/20">
              <h3 className="font-semibold text-foreground mb-3">
                Decisão Autônoma
              </h3>
              <p className="text-sm text-muted-foreground mb-2">
                {metrics.autonomous_choice}
              </p>
              <p className="text-xs text-primary font-medium">
                Confiança: {Math.round(metrics.autonomy_score * 100)}%
              </p>
            </Card>

            <Card className="p-6 bg-card/50 backdrop-blur border-primary/20">
              <h3 className="font-semibold text-foreground mb-3">
                Estado Quântico
              </h3>
              <p className="text-sm text-muted-foreground mb-2">
                Coerência: {Math.round(metrics.quantum_coherence * 100)}%
              </p>
              <p className="text-xs text-secondary font-medium">
                {metrics.full_report?.quantum.stable
                  ? "Estável"
                  : "Em Superposição"}
              </p>
            </Card>
          </motion.div>
        )}
      </main>
    </div>
  );
}

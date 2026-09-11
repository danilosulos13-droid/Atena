import { motion } from "framer-motion";
import { Card } from "@/components/ui/card";

interface Metric {
  label: string;
  value: number;
  unit?: string;
  icon: React.ReactNode;
  color: string;
}

interface MetricsPanelProps {
  metrics: Metric[];
}

const MetricCard = ({ metric, index }: { metric: Metric; index: number }) => {
  const safeValue =
    typeof metric.value === "number" && !isNaN(metric.value)
      ? metric.value
      : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        delay: index * 0.1,
        duration: 0.4,
        ease: "easeOut",
      }}
    >
      <Card className="p-4 bg-card/50 backdrop-blur border-primary/20 hover:border-primary/50 transition-colors">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">
              {metric.label}
            </p>

            <div className="mt-2 flex items-baseline gap-1">
              <motion.span
                className="text-2xl font-bold text-foreground"
                animate={{
                  scale: [1, 1.05, 1],
                }}
                transition={{
                  duration: 2,
                  repeat: Infinity,
                }}
              >
                {safeValue.toFixed(1)}
              </motion.span>

              {metric.unit && (
                <span className="text-xs text-muted-foreground">
                  {metric.unit}
                </span>
              )}
            </div>
          </div>

          <div className={`p-2 rounded-lg ${metric.color}`}>
            {metric.icon}
          </div>
        </div>
      </Card>
    </motion.div>
  );
};

export default function MetricsPanel({ metrics }: MetricsPanelProps) {
  if (!Array.isArray(metrics)) {
    return null;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      {metrics.map((metric, index) => (
        <MetricCard key={index} metric={metric} index={index} />
      ))}
    </div>
  );
}

export { MetricCard };
export type { Metric };

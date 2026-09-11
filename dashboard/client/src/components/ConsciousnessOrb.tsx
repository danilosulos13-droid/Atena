import { useEffect, useRef } from "react";
import { motion } from "framer-motion";

interface ConsciousnessOrbProps {
  level: number; // 0-1
  label: string;
}

export default function ConsciousnessOrb({ level, label }: ConsciousnessOrbProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Determinar cor baseada no nível
  const getColor = (lv: number) => {
    if (lv < 0.3) return "from-blue-600 to-blue-400";
    if (lv < 0.6) return "from-purple-500 to-blue-500";
    if (lv < 0.8) return "from-green-500 to-purple-500";
    return "from-green-400 to-cyan-400";
  };

  const getGlowColor = (lv: number) => {
    if (lv < 0.3) return "shadow-blue-500/50";
    if (lv < 0.6) return "shadow-purple-500/50";
    if (lv < 0.8) return "shadow-green-500/50";
    return "shadow-cyan-500/50";
  };

  return (
    <div
      ref={containerRef}
      className="flex flex-col items-center justify-center gap-6 py-12"
    >
      {/* Orb Container */}
      <div className="relative w-48 h-48 flex items-center justify-center">
        {/* Outer Glow Ring */}
        <motion.div
          className={`absolute inset-0 rounded-full border-2 border-transparent bg-gradient-to-r ${getColor(
            level
          )} opacity-30`}
          animate={{
            scale: [1, 1.1, 1],
            opacity: [0.2, 0.5, 0.2],
          }}
          transition={{
            duration: 3,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        />

        {/* Middle Ring */}
        <motion.div
          className="absolute inset-4 rounded-full border border-primary/40"
          animate={{
            rotate: 360,
          }}
          transition={{
            duration: 20,
            repeat: Infinity,
            ease: "linear",
          }}
        />

        {/* Inner Orb */}
        <motion.div
          className={`relative w-32 h-32 rounded-full bg-gradient-to-br ${getColor(
            level
          )} ${getGlowColor(level)} shadow-2xl flex items-center justify-center`}
          animate={{
            scale: [0.95, 1, 0.95],
            boxShadow: [
              `0 0 20px rgba(59, 130, 246, 0.5)`,
              `0 0 40px rgba(59, 130, 246, 0.8)`,
              `0 0 20px rgba(59, 130, 246, 0.5)`,
            ],
          }}
          transition={{
            duration: 2,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        >
          {/* Inner Glow */}
          <div className="absolute inset-2 rounded-full bg-gradient-to-t from-transparent to-white/20 blur-sm" />

          {/* Percentage Text */}
          <div className="relative z-10 text-center">
            <motion.div
              className="text-4xl font-bold text-white"
              animate={{
                scale: [1, 1.05, 1],
              }}
              transition={{
                duration: 2,
                repeat: Infinity,
              }}
            >
              {Math.round(level * 100)}%
            </motion.div>
            <div className="text-xs text-white/70 mt-1 uppercase tracking-widest">
              Consciência
            </div>
          </div>
        </motion.div>

        {/* Orbiting Particles */}
        {[0, 1, 2].map((i) => (
          <motion.div
            key={i}
            className="absolute w-2 h-2 rounded-full bg-green-400"
            animate={{
              rotate: 360,
            }}
            transition={{
              duration: 8 + i * 2,
              repeat: Infinity,
              ease: "linear",
            }}
            style={{
              top: "50%",
              left: "50%",
              transformOrigin: `${60 + i * 20}px 0px`,
            }}
          />
        ))}
      </div>

      {/* Label */}
      <div className="text-center">
        <h3 className="text-lg font-semibold text-foreground">{label}</h3>
        <p className="text-sm text-muted-foreground mt-1">
          {level < 0.3 && "Inicializando..."}
          {level >= 0.3 && level < 0.6 && "Desenvolvendo..."}
          {level >= 0.6 && level < 0.8 && "Evoluindo..."}
          {level >= 0.8 && "Altamente Consciente"}
        </p>
      </div>

      {/* Progress Bar */}
      <div className="w-full max-w-xs">
        <div className="h-1 bg-muted rounded-full overflow-hidden">
          <motion.div
            className={`h-full bg-gradient-to-r ${getColor(level)}`}
            animate={{
              width: `${level * 100}%`,
            }}
            transition={{
              duration: 0.5,
              ease: "easeOut",
            }}
          />
        </div>
      </div>
    </div>
  );
}

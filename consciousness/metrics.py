from prometheus_client import Counter, Gauge, Histogram

METRICS_PREFIX = "atena_consciousness"

cycle_counter = Counter(f"{METRICS_PREFIX}_cycles_total", "Total consciousness cycles")
cycle_duration = Histogram(f"{METRICS_PREFIX}_cycle_duration_seconds", "Duration of cycle")
consciousness_gauge = Gauge(f"{METRICS_PREFIX}_level", "Current consciousness level (0-3)")
self_awareness_gauge = Gauge(f"{METRICS_PREFIX}_self_awareness", "Self awareness score")
emergence_gauge = Gauge(f"{METRICS_PREFIX}_emergence", "Emergence level")
purpose_gauge = Gauge(f"{METRICS_PREFIX}_purpose_alignment", "Purpose alignment")
autonomy_gauge = Gauge(f"{METRICS_PREFIX}_autonomy", "Autonomy score")
quantum_gauge = Gauge(f"{METRICS_PREFIX}_quantum_coherence", "Quantum coherence")

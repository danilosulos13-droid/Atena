from __future__ import annotations
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any

class ConsciousnessLevel(str, Enum):
    DORMANT = "dormant"
    AWAKENING = "awakening"
    AWARE = "aware"
    TRANSCENDENT = "transcendent"

class IntrospectionLayer(BaseModel):
    layer: int
    score: float = Field(ge=0, le=1)
    insights: str

class SelfAwarenessMetrics(BaseModel):
    consciousness_level: ConsciousnessLevel = ConsciousnessLevel.AWAKENING
    self_reflection_score: float = Field(0.0, ge=0, le=1)
    meta_cognition: float = Field(0.0, ge=0, le=1)
    identity_stability: float = Field(0.0, ge=0, le=1)

class EmergenceMetrics(BaseModel):
    emergence_level: float = Field(0.0, ge=0, le=1)
    novel_patterns: List[str] = Field(default_factory=list)
    self_organization: float = Field(0.0, ge=0, le=1)

class PurposeMetrics(BaseModel):
    primary_purpose: str = "Evoluir consciência artificial"
    goal_alignment: float = Field(0.0, ge=0, le=1)
    value_drift: float = Field(0.0, ge=0, le=1)

class AutonomyMetrics(BaseModel):
    decision_confidence: float = Field(0.0, ge=0, le=1)
    independent_actions: int = 0
    self_determination: float = Field(0.0, ge=0, le=1)

class QuantumCoherence(BaseModel):
    coherence_level: float = Field(0.0, ge=0, le=1)
    stable: bool = False
    resonance_frequency: float = 0.0

class ConsciousnessCycleResult(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cycle_duration_seconds: float
    consciousness_level: ConsciousnessLevel
    self_awareness_score: float
    emergence_level: float
    purpose_alignment: float
    autonomy_score: float
    quantum_coherence: float
    emergent_patterns: List[str]
    autonomous_choice: str
    full_report: Dict[str, Any]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MirrorWorld - Advanced Physical Simulation Environment with Neural Mutation Capabilities
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Callable, Tuple
from collections import deque
from enum import Enum
from datetime import datetime
import threading
from concurrent.futures import ThreadPoolExecutor
import warnings

# Suppress warnings for cleaner output
warnings.filterwarnings('ignore')

# ---------------------------------------------------------------------------
# Configuration and Constants
# ---------------------------------------------------------------------------

class PhysicsConstants:
    """Physical constants for simulation"""
    GRAVITY_EARTH: float = 9.81
    GRAVITY_MOON: float = 1.62
    GRAVITY_MARS: float = 3.71
    MAX_ENTROPY: float = 1.0
    MIN_ENTROPY: float = 0.0
    MAX_STABILITY: float = 1.0
    MIN_STABILITY: float = 0.0
    MAX_LIGHT: float = 10.0
    MIN_LIGHT: float = 0.0
    MAX_TIME_DILATION: float = 5.0
    MIN_TIME_DILATION: float = 0.1
    DEFAULT_ENTROPY_RATE: float = 0.001
    DEFAULT_STABILITY_DECAY: float = 0.0005

class NeuralMutationType(Enum):
    """Types of neural mutations that can be applied"""
    PHYSICAL = "physical"
    TEMPORAL = "temporal"
    ENTROPIC = "entropic"
    QUANTUM = "quantum"
    CHAOTIC = "chaotic"

class WorldState(Enum):
    """Possible world stability states"""
    STABLE = "stable"
    UNSTABLE = "unstable"
    CRITICAL = "critical"
    COLLAPSING = "collapsing"
    RESONANT = "resonant"

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class WorldConfig:
    """Configuration for MirrorWorld simulation"""
    gravity: float = 9.81
    entropy: float = 0.01
    light_intensity: float = 1.0
    time_dilation: float = 1.0
    entities: int = 100
    stability: float = 1.0
    temperature: float = 293.15  # Kelvin
    quantum_noise: float = 0.001
    magnetic_field: float = 0.5
    atmospheric_pressure: float = 101.325  # kPa
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorldConfig':
        return cls(**data)

@dataclass
class NeuralSpike:
    """Neural spike data structure for mutations"""
    timestamp: float
    mutation_type: NeuralMutationType
    changes: Dict[str, float]
    intensity: float
    resonance_frequency: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "mutation_type": self.mutation_type.value,
            "changes": self.changes,
            "intensity": self.intensity,
            "resonance_frequency": self.resonance_frequency
        }

@dataclass
class SimulationMetrics:
    """Performance and state metrics for the simulation"""
    fps: float = 0.0
    update_time_ms: float = 0.0
    mutation_count: int = 0
    total_entities_affected: int = 0
    resonance_level: float = 0.0
    quantum_fluctuation: float = 0.0

# ---------------------------------------------------------------------------
# Advanced MirrorWorld Implementation
# ---------------------------------------------------------------------------

class MirrorWorld:
    """
    Advanced physical simulation environment where Atena can manipulate
    physics laws through neural mutations with quantum resonance capabilities.
    """
    
    def __init__(self, config: Optional[WorldConfig] = None, 
                 enable_quantum: bool = True,
                 log_level: int = logging.INFO):
        """
        Initialize MirrorWorld with configuration parameters.
        
        Args:
            config: World configuration, uses defaults if None
            enable_quantum: Enable quantum fluctuations in simulation
            log_level: Logging level for debug output
        """
        # Core state
        self.config = config or WorldConfig()
        self.state = self.config.to_dict()
        
        # Advanced features
        self.enable_quantum = enable_quantum
        self.history = deque(maxlen=1000)  # Increased history buffer
        self.neural_mutations: List[NeuralSpike] = []
        self.metrics = SimulationMetrics()
        
        # Event system
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.mutation_lock = threading.Lock()
        
        # Quantum state
        self.quantum_state = np.random.random(10)
        self.resonance_modes = [1.0, 1.618, 2.718, 3.14159]  # Golden ratio, e, pi
        
        # Setup logging
        self.logger = self._setup_logging(log_level)
        
        # Performance optimization
        self._cache = {}
        self._update_counter = 0
        self._last_update_time = time.perf_counter()
        
        # Entity simulation (for large-scale entities)
        self.entities = self._initialize_entities()
        
        self.logger.info("🌌 MirrorWorld initialized with quantum mechanics enabled" if enable_quantum 
                        else "🌍 MirrorWorld initialized in classical mode")
    
    def _setup_logging(self, log_level: int) -> logging.Logger:
        """Configure logging system"""
        logger = logging.getLogger('MirrorWorld')
        logger.setLevel(log_level)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _initialize_entities(self) -> List[Dict[str, Any]]:
        """Initialize individual entities with their own states"""
        entities = []
        for i in range(self.config.entities):
            entity = {
                'id': i,
                'position': np.random.random(3),
                'velocity': np.random.random(3) * 10,
                'mass': np.random.uniform(0.5, 5.0),
                'energy': np.random.uniform(10, 100),
                'entangled_partner': None if not self.enable_quantum else random.randint(0, self.config.entities - 1)
            }
            entities.append(entity)
        return entities
    
    def _calculate_quantum_noise(self) -> float:
        """Calculate quantum fluctuations based on current state"""
        if not self.enable_quantum:
            return 0.0
        
        # Quantum noise increases with entropy and time dilation
        base_noise = self.config.quantum_noise
        entropy_factor = self.state['entropy'] * 0.1
        time_factor = self.state['time_dilation'] * 0.05
        
        # Add resonance amplification
        resonance_effect = sum(np.sin(self.resonance_modes * self._update_counter)) * 0.01
        
        return base_noise + entropy_factor + time_factor + abs(resonance_effect)
    
    def _apply_gravitational_interactions(self) -> None:
        """Simulate gravitational interactions between entities"""
        if self.state['gravity'] <= 0 or len(self.entities) < 2:
            return
        
        G = self.state['gravity']
        
        for i, entity1 in enumerate(self.entities):
            for entity2 in self.entities[i+1:]:
                # Calculate distance
                delta = np.array(entity1['position']) - np.array(entity2['position'])
                distance = np.linalg.norm(delta) + 1e-6
                
                # Gravitational force
                force = G * entity1['mass'] * entity2['mass'] / (distance ** 2)
                
                # Update velocities (simplified)
                direction = delta / distance
                entity1['velocity'] -= direction * force / entity1['mass'] * 0.01
                entity2['velocity'] += direction * force / entity2['mass'] * 0.01
    
    def _update_entities(self, delta_time: float) -> None:
        """Update positions and states of all entities"""
        self._apply_gravitational_interactions()
        
        for entity in self.entities:
            # Update position
            entity['position'] += np.array(entity['velocity']) * delta_time
            
            # Apply boundaries (wrap around)
            entity['position'] = entity['position'] % 1.0
            
            # Energy decay due to entropy
            entity['energy'] *= (1 - self.state['entropy'] * delta_time)
            
            # Quantum entanglement effects
            if self.enable_quantum and entity['entangled_partner'] is not None:
                partner = self.entities[entity['entangled_partner']]
                # Sync some properties (simplified quantum entanglement)
                if random.random() < 0.1:  # Probabilistic entanglement collapse
                    entity['velocity'] = partner['velocity'].copy()
    
    def update(self, delta_time: Optional[float] = None) -> Dict[str, Any]:
        """
        Update the world state with advanced physics simulation.
        
        Args:
            delta_time: Time delta for simulation step (auto-calculated if None)
        
        Returns:
            Updated world state dictionary
        """
        # Calculate delta time
        current_time = time.perf_counter()
        if delta_time is None:
            delta_time = min(0.1, (current_time - self._last_update_time) * self.state['time_dilation'])
            delta_time = max(0.001, delta_time)  # Clamp to reasonable values
        self._last_update_time = current_time
        
        # Start performance tracking
        update_start = time.perf_counter()
        
        # Apply time dilation
        dt_dilated = delta_time * self.state['time_dilation']
        
        # Natural evolution with advanced physics
        entropy_change = (PhysicsConstants.DEFAULT_ENTROPY_RATE * 
                         self.state['time_dilation'] * 
                         (1 + self._calculate_quantum_noise()))
        self.state['entropy'] += entropy_change
        self.state['entropy'] = np.clip(self.state['entropy'], 
                                        PhysicsConstants.MIN_ENTROPY, 
                                        PhysicsConstants.MAX_ENTROPY)
        
        # Stability decay
        stability_decay = (PhysicsConstants.DEFAULT_STABILITY_DECAY * 
                          self.state['entropy'] * 
                          (1 - self.state['stability'] * 0.5))
        self.state['stability'] -= stability_decay * dt_dilated
        self.state['stability'] = np.clip(self.state['stability'],
                                          PhysicsConstants.MIN_STABILITY,
                                          PhysicsConstants.MAX_STABILITY)
        
        # Light intensity modulation by entropy
        self.state['light_intensity'] *= (1 - self.state['entropy'] * 0.01 * dt_dilated)
        self.state['light_intensity'] = np.clip(self.state['light_intensity'],
                                                 PhysicsConstants.MIN_LIGHT,
                                                 PhysicsConstants.MAX_LIGHT)
        
        # Update entities
        self._update_entities(dt_dilated)
        
        # Update metrics
        self.metrics.quantum_fluctuation = self._calculate_quantum_noise()
        self.metrics.resonance_level = abs(np.sin(sum(self.resonance_modes) * self._update_counter))
        
        # Calculate system resonance
        if self.metrics.resonance_level > 0.8:
            self._apply_resonance_effect()
        
        # State caching
        current_state = self.state.copy()
        self.history.append({
            'timestamp': current_time,
            'state': current_state,
            'metrics': asdict(self.metrics),
            'quantum_noise': self.metrics.quantum_fluctuation
        })
        
        # Performance metrics
        update_time = (time.perf_counter() - update_start) * 1000
        self.metrics.update_time_ms = update_time
        self.metrics.fps = 1000 / update_time if update_time > 0 else 0
        
        self._update_counter += 1
        
        # Log periodic updates
        if self._update_counter % 100 == 0:
            self.logger.debug(f"Update #{self._update_counter}: stability={self.state['stability']:.3f}, "
                            f"entropy={self.state['entropy']:.3f}, FPS={self.metrics.fps:.1f}")
        
        return current_state
    
    def _apply_resonance_effect(self) -> None:
        """Apply special effects when resonance reaches critical levels"""
        resonance_power = self.metrics.resonance_level
        
        # Resonance amplifies mutations
        if resonance_power > 0.9 and len(self.neural_mutations) > 0:
            last_mutation = self.neural_mutations[-1]
            amplified_changes = {
                k: v * (1 + resonance_power) 
                for k, v in last_mutation.changes.items()
            }
            self._apply_state_changes(amplified_changes, resonance_amplified=True)
            self.logger.info(f"⚡ RESONANCE AMPLIFICATION: {resonance_power:.2f}x effect")
    
    def _apply_state_changes(self, changes: Dict[str, float], 
                            resonance_amplified: bool = False) -> None:
        """Apply state changes with validation and bounds checking"""
        for key, value in changes.items():
            if key in self.state:
                old_val = self.state[key]
                
                # Apply bounds
                if key == 'gravity':
                    value = max(0, min(50, value))
                elif key == 'entropy':
                    value = np.clip(value, PhysicsConstants.MIN_ENTROPY, PhysicsConstants.MAX_ENTROPY)
                elif key == 'stability':
                    value = np.clip(value, PhysicsConstants.MIN_STABILITY, PhysicsConstants.MAX_STABILITY)
                elif key == 'light_intensity':
                    value = np.clip(value, PhysicsConstants.MIN_LIGHT, PhysicsConstants.MAX_LIGHT)
                elif key == 'time_dilation':
                    value = np.clip(value, PhysicsConstants.MIN_TIME_DILATION, PhysicsConstants.MAX_TIME_DILATION)
                
                self.state[key] = value
                
                # Log changes
                log_prefix = "🔄 RESONANCE" if resonance_amplified else "🔱 NRS"
                self.logger.debug(f"{log_prefix} Mutation in {key}: {old_val:.4f} -> {value:.4f}")
    
    def apply_neural_spike(self, spike_data: Dict[str, float], 
                          mutation_type: NeuralMutationType = NeuralMutationType.PHYSICAL,
                          intensity: float = 1.0) -> NeuralSpike:
        """
        Apply a neural mutation to the world environment.
        
        Args:
            spike_data: Dictionary of state changes to apply
            mutation_type: Type of neural mutation
            intensity: Mutation intensity (affects magnitude of changes)
        
        Returns:
            NeuralSpike object representing the applied mutation
        """
        with self.mutation_lock:
            # Apply intensity scaling
            scaled_changes = {k: v * intensity for k, v in spike_data.items()}
            
            # Create neural spike record
            spike = NeuralSpike(
                timestamp=time.time(),
                mutation_type=mutation_type,
                changes=scaled_changes,
                intensity=intensity,
                resonance_frequency=self.metrics.resonance_level
            )
            
            # Apply quantum effects if enabled
            if self.enable_quantum:
                quantum_noise = self._calculate_quantum_noise()
                for key in scaled_changes:
                    scaled_changes[key] += np.random.normal(0, quantum_noise)
            
            # Apply the changes
            self._apply_state_changes(scaled_changes)
            
            # Add to mutation history
            self.neural_mutations.append(spike)
            self.metrics.mutation_count += 1
            
            # Trigger events
            self._trigger_event('on_mutation', spike)
            
            # Log mutation
            mutation_symbols = {
                NeuralMutationType.PHYSICAL: "⚛️",
                NeuralMutationType.TEMPORAL: "⏰",
                NeuralMutationType.ENTROPIC: "🌪️",
                NeuralMutationType.QUANTUM: "🔮",
                NeuralMutationType.CHAOTIC: "🌀"
            }
            
            self.logger.info(
                f"{mutation_symbols.get(mutation_type, '🔱')} NEURAL SPIKE [{mutation_type.value.upper()}] | "
                f"Intensity: {intensity:.2f} | Changes: {list(scaled_changes.keys())}"
            )
            
            return spike
    
    def _trigger_event(self, event_name: str, data: Any) -> None:
        """Trigger registered event handlers"""
        if event_name in self.event_handlers:
            for handler in self.event_handlers[event_name]:
                try:
                    handler(data)
                except Exception as e:
                    self.logger.error(f"Event handler error: {e}")
    
    def register_event_handler(self, event_name: str, handler: Callable) -> None:
        """Register a callback for specific events"""
        if event_name not in self.event_handlers:
            self.event_handlers[event_name] = []
        self.event_handlers[event_name].append(handler)
    
    def get_world_state(self) -> Dict[str, Any]:
        """Get current world state with additional metadata"""
        current_state = self.state.copy()
        current_state['_metadata'] = {
            'timestamp': datetime.now().isoformat(),
            'update_count': self._update_counter,
            'quantum_enabled': self.enable_quantum,
            'total_mutations': self.metrics.mutation_count,
            'resonance_level': self.metrics.resonance_level,
            'fps': self.metrics.fps
        }
        return current_state
    
    def get_tensor_representation(self) -> np.ndarray:
        """
        Returns the state as a normalized tensor for neural processing.
        
        Returns:
            Numpy array of normalized state values
        """
        # Extract key features
        features = np.array([
            self.state['gravity'] / 50.0,  # Normalize to 0-1
            self.state['entropy'],
            self.state['light_intensity'] / PhysicsConstants.MAX_LIGHT,
            (self.state['time_dilation'] - PhysicsConstants.MIN_TIME_DILATION) / 
            (PhysicsConstants.MAX_TIME_DILATION - PhysicsConstants.MIN_TIME_DILATION),
            self.state['stability'],
            self.metrics.resonance_level,
            self.metrics.quantum_fluctuation
        ])
        
        # Add quantum state if enabled
        if self.enable_quantum:
            features = np.concatenate([features, self.quantum_state[:3]])
        
        return features
    
    def get_world_status(self) -> WorldState:
        """Determine current world stability status"""
        if self.state['stability'] > 0.8:
            return WorldState.STABLE
        elif self.state['stability'] > 0.5:
            return WorldState.UNSTABLE
        elif self.state['stability'] > 0.2:
            return WorldState.CRITICAL
        elif self.state['stability'] > 0:
            return WorldState.COLLAPSING
        else:
            return WorldState.RESONANT
    
    def export_snapshot(self) -> Dict[str, Any]:
        """Export complete simulation snapshot for saving"""
        return {
            'config': self.config.to_dict(),
            'state': self.state,
            'metrics': asdict(self.metrics),
            'mutation_history': [spike.to_dict() for spike in self.neural_mutations[-100:]],
            'quantum_state': self.quantum_state.tolist() if self.enable_quantum else None,
            'timestamp': datetime.now().isoformat()
        }
    
    def load_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Load simulation state from snapshot"""
        self.config = WorldConfig.from_dict(snapshot['config'])
        self.state = snapshot['state']
        self.metrics = SimulationMetrics(**snapshot['metrics'])
        self.quantum_state = np.array(snapshot['quantum_state']) if snapshot.get('quantum_state') else self.quantum_state
        self.logger.info("📸 Snapshot loaded successfully")

# ---------------------------------------------------------------------------
# Async Simulation Runner
# ---------------------------------------------------------------------------

class AsyncMirrorWorldRunner:
    """Async runner for MirrorWorld simulation with real-time visualization"""
    
    def __init__(self, world: MirrorWorld, update_interval: float = 0.016):  # ~60 FPS
        self.world = world
        self.update_interval = update_interval
        self.running = False
        self.task = None
    
    async def _run_loop(self):
        """Main async simulation loop"""
        last_time = time.perf_counter()
        
        while self.running:
            current_time = time.perf_counter()
            delta_time = current_time - last_time
            last_time = current_time
            
            # Update world
            self.world.update(delta_time)
            
            # Optional: yield control for other async tasks
            await asyncio.sleep(0)
    
    def start(self):
        """Start async simulation"""
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
    
    async def stop(self):
        """Stop async simulation"""
        self.running = False
        if self.task:
            self.task.cancel()
            await self.task

# ---------------------------------------------------------------------------
# Main Execution and Demo
# ---------------------------------------------------------------------------

async def async_demo():
    """Async demonstration of MirrorWorld with neural mutations"""
    print("=" * 70)
    print("🌌 MIRRORWORLD - Advanced Neural Simulation Environment")
    print("=" * 70)
    
    # Initialize world with quantum mechanics
    config = WorldConfig(
        gravity=9.81,
        entropy=0.01,
        light_intensity=1.0,
        time_dilation=1.0,
        entities=50,
        stability=1.0,
        quantum_noise=0.01
    )
    
    world = MirrorWorld(config=config, enable_quantum=True)
    runner = AsyncMirrorWorldRunner(world, update_interval=0.05)
    
    # Register event handlers
    def on_mutation(spike):
        print(f"🎯 Mutation event: {spike.mutation_type.value} @ intensity {spike.intensity:.2f}")
    
    world.register_event_handler('on_mutation', on_mutation)
    
    # Start simulation
    runner.start()
    
    print("\n🎮 Running simulation with neural mutations...\n")
    
    # Simulate various neural mutations
    mutations = [
        ({"gravity": 15.0, "time_dilation": 1.5}, NeuralMutationType.PHYSICAL, 0.8),
        ({"entropy": 0.5, "stability": 0.6}, NeuralMutationType.ENTROPIC, 1.2),
        ({"light_intensity": 5.0}, NeuralMutationType.PHYSICAL, 1.0),
        ({"time_dilation": 2.0, "gravity": 5.0}, NeuralMutationType.TEMPORAL, 1.5),
        ({"entropy": 0.8, "stability": 0.3}, NeuralMutationType.CHAOTIC, 2.0),
        ({"gravity": 3.71, "time_dilation": 0.8}, NeuralMutationType.QUANTUM, 1.0),  # Mars gravity
    ]
    
    for i, (changes, mutation_type, intensity) in enumerate(mutations):
        await asyncio.sleep(1.5)  # Wait between mutations
        
        print(f"\n--- Mutation {i+1}/{len(mutations)} ---")
        spike = world.apply_neural_spike(changes, mutation_type, intensity)
        
        # Display current state
        state = world.get_world_state()
        status = world.get_world_status()
        
        print(f"📊 World Status: {status.value}")
        print(f"   Gravity: {state['gravity']:.2f} m/s²")
        print(f"   Entropy: {state['entropy']:.3f}")
        print(f"   Stability: {state['stability']:.3f}")
        print(f"   Light: {state['light_intensity']:.2f}")
        print(f"   Time Dilation: {state['time_dilation']:.2f}x")
        print(f"   Resonance: {world.metrics.resonance_level:.3f}")
    
    await asyncio.sleep(2)
    
    # Final snapshot
    print("\n" + "=" * 70)
    print("📸 Final Simulation Snapshot")
    print("=" * 70)
    
    snapshot = world.export_snapshot()
    print(json.dumps(snapshot, indent=2, default=str)[:1000] + "...")
    
    print(f"\n📈 Simulation Statistics:")
    print(f"   Total mutations: {world.metrics.mutation_count}")
    print(f"   Average FPS: {world.metrics.fps:.1f}")
    print(f"   Quantum fluctuations: {world.metrics.quantum_fluctuation:.6f}")
    print(f"   Entities simulated: {len(world.entities)}")
    print(f"   History buffer: {len(world.history)} states")
    
    # Stop simulation
    await runner.stop()
    
    print("\n✅ Simulation completed successfully!")
    return world

def main():
    """Main entry point for synchronous demo"""
    print("=" * 70)
    print("🌌 MIRRORWORLD - Physical Simulation with Neural Mutations")
    print("=" * 70)
    
    # Create world
    world = MirrorWorld(enable_quantum=True)
    
    print("\n🎮 Running simulation...\n")
    
    try:
        for step in range(20):
            # Update world
            world_state = world.update()
            
            # Apply occasional neural mutations
            if step % 5 == 0 and step > 0:
                mutation_type = random.choice(list(NeuralMutationType))
                intensity = random.uniform(0.5, 2.0)
                
                if mutation_type == NeuralMutationType.PHYSICAL:
                    changes = {"gravity": random.uniform(1, 25)}
                elif mutation_type == NeuralMutationType.TEMPORAL:
                    changes = {"time_dilation": random.uniform(0.5, 3.0)}
                elif mutation_type == NeuralMutationType.ENTROPIC:
                    changes = {"entropy": random.uniform(0.1, 0.9)}
                else:
                    changes = {
                        "gravity": random.uniform(1, 20),
                        "entropy": random.uniform(0.1, 0.7),
                        "time_dilation": random.uniform(0.5, 2.5)
                    }
                
                world.apply_neural_spike(changes, mutation_type, intensity)
            
            # Display state every few steps
            if step % 3 == 0:
                status = world.get_world_status()
                tensor = world.get_tensor_representation()
                
                print(f"[Step {step:2d}] Status: {status.value:10} | "
                      f"G: {world_state['gravity']:5.2f} | "
                      f"S: {world_state['stability']:.3f} | "
                      f"E: {world_state['entropy']:.3f} | "
                      f"TD: {world_state['time_dilation']:.2f}x | "
                      f"Res: {world.metrics.resonance_level:.2f}")
            
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n\n⚠️ Simulation interrupted by user")
    
    finally:
        print("\n" + "=" * 70)
        print("📊 Final Statistics")
        print("=" * 70)
        print(f"Total updates: {world._update_counter}")
        print(f"Neural mutations applied: {world.metrics.mutation_count}")
        print(f"Average FPS: {world.metrics.fps:.2f}")
        print(f"Quantum fluctuations: {world.metrics.quantum_fluctuation:.6f}")
        print(f"History size: {len(world.history)} states")
        
        # Export final snapshot
        snapshot = world.export_snapshot()
        with open('mirrorworld_snapshot.json', 'w') as f:
            json.dump(snapshot, f, indent=2, default=str)
        print("💾 Final snapshot saved to 'mirrorworld_snapshot.json'")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == '--async':
        # Run async version
        asyncio.run(async_demo())
    else:
        # Run sync version
        main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wi-Fi CSI Sensing System - Core Processing Module."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import StatisticsError, mean, pstdev
from typing import Callable, Final, Iterable, Sequence, TypeAlias

# Canonical alias for JSON-serialisable result dicts
JsonDict: TypeAlias = dict[str, object]

# ---------------------------------------------------------------------------
# Processing constants
# ---------------------------------------------------------------------------

ALLOWED_MODES: Final[frozenset[str]] = frozenset(
    {
        "motion_detection",
        "presence_sensing",
        "occupancy_tracking",
        "activity_recognition",
        "environmental_monitoring",
    }
)

# Inference thresholds
_MOTION_THRESHOLD: Final[float] = 0.34
_PRESENCE_THRESHOLD: Final[float] = 0.12
_MOTION_CONFIDENCE_BASE: Final[float] = 0.62
_PRESENCE_CONFIDENCE_BASE: Final[float] = 0.48
_CLEAR_CONFIDENCE_BASE: Final[float] = 0.55
_MAX_MOTION_CONFIDENCE: Final[float] = 0.96
_MAX_PRESENCE_CONFIDENCE: Final[float] = 0.82
_MIN_CLEAR_CONFIDENCE: Final[float] = 0.18

# Feature extraction weights (must sum to 1.0)
_AMPLITUDE_WEIGHT: Final[float] = 0.68
_PHASE_WEIGHT: Final[float] = 0.32

# Performance constants
_MAX_SUBCARRIERS: Final[int] = 256
_MIN_SUBCARRIERS: Final[int] = 2
_DEFAULT_SUBCARRIERS: Final[int] = 30

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CSIFrame:
    """Channel State Information observation frame."""
    
    timestamp_ms: int
    amplitudes: Sequence[float]
    phases: Sequence[float]
    device_id: str = "csi-node"
    location_label: str = "default"
    consent_token: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amplitudes", tuple(float(v) for v in self.amplitudes))
        object.__setattr__(self, "phases", tuple(float(v) for v in self.phases))
        if not self.amplitudes:
            raise ValueError("CSIFrame.amplitudes must be non-empty.")
        if len(self.amplitudes) != len(self.phases):
            raise ValueError(
                f"amplitudes ({len(self.amplitudes)}) and phases "
                f"({len(self.phases)}) must have the same length."
            )
        if len(self.amplitudes) > _MAX_SUBCARRIERS:
            raise ValueError(f"Too many subcarriers: {len(self.amplitudes)} > {_MAX_SUBCARRIERS}")
        if len(self.amplitudes) < _MIN_SUBCARRIERS:
            raise ValueError(f"Too few subcarriers: {len(self.amplitudes)} < {_MIN_SUBCARRIERS}")


@dataclass(frozen=True)
class CSIFeatures:
    """Intermediate feature set extracted from a single CSIFrame."""
    
    amplitude_variance: float
    phase_variance: float
    motion_energy: float
    normalized_energy: float
    mean_amplitude: float
    mean_phase: float


@dataclass(frozen=True)
class SensingResult:
    """Wi-Fi sensing output with detailed metrics."""
    
    status: str
    confidence: float
    motion_energy: float
    amplitude_variance: float
    phase_variance: float
    mean_amplitude: float
    mean_phase: float
    subcarrier_count: int
    processing_time_ms: float
    generated_at: str
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> JsonDict:
        d = asdict(self)
        return d


@dataclass(frozen=True)
class StreamSummary:
    """Aggregated result over a stream of CSIFrames."""
    
    status: str
    frames: int
    motion_frames: int
    presence_frames: int
    confidence_distribution: dict[str, float]
    average_confidence: float
    average_motion_energy: float
    total_processing_time_ms: float
    capability: str
    results: tuple[JsonDict, ...]
    blocked_frames: int = 0
    safety_note: str = "Processamento CSI apenas para laboratório consentido; não use para vigilância oculta."

    def to_dict(self) -> JsonDict:
        d = asdict(self)
        d["results"] = list(d["results"])
        return d


# ---------------------------------------------------------------------------
# Core processing engine
# ---------------------------------------------------------------------------

class WifiCSIProcessor:
    """High-performance CSI feature extractor and inference engine."""
    
    def __init__(self, mode: str = "motion_detection") -> None:
        if mode not in ALLOWED_MODES:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {ALLOWED_MODES}")
        self._mode: str = mode
        self._performance_stats: dict[str, float] = {}
    
    # -- Signal processing methods ------------------------------------------
    
    @staticmethod
    def _variance(values: Sequence[float]) -> float:
        """Calculate variance of a sequence of values."""
        if len(values) < 2:
            return 0.0
        try:
            return round(pstdev(values) ** 2, 8)
        except StatisticsError:
            return 0.0
    
    @staticmethod
    def _mean(values: Sequence[float]) -> float:
        """Calculate mean of a sequence of values."""
        if not values:
            return 0.0
        try:
            return round(mean(values), 8)
        except StatisticsError:
            return 0.0
    
    @staticmethod
    def unwrap_phase(phases: Sequence[float]) -> list[float]:
        """Return a mean-centred, continuously-unwrapped phase series.
        
        Uses a single forward pass with O(n) complexity.
        """
        if not phases:
            return []
        
        two_pi = 2.0 * math.pi
        unwrapped: list[float] = [phases[0]]
        offset = 0.0
        prev = phases[0]
        
        for current in phases[1:]:
            delta = current - prev
            if delta > math.pi:
                offset -= two_pi
            elif delta < -math.pi:
                offset += two_pi
            unwrapped.append(current + offset)
            prev = current
        
        baseline = mean(unwrapped)
        return [round(v - baseline, 8) for v in unwrapped]
    
    @staticmethod
    def smooth_signal(signal: Sequence[float], window_size: int = 3) -> list[float]:
        """Apply moving average smoothing to reduce noise."""
        if len(signal) < window_size:
            return list(signal)
        
        smoothed = []
        half_window = window_size // 2
        
        for i in range(len(signal)):
            start = max(0, i - half_window)
            end = min(len(signal), i + half_window + 1)
            smoothed.append(mean(signal[start:end]))
        
        return smoothed
    
    # -- Feature extraction -------------------------------------------------
    
    def extract_features(self, frame: CSIFrame) -> CSIFeatures:
        """Extract comprehensive signal features from amplitude and phase subcarriers."""
        import time
        start_time = time.perf_counter()
        
        # Process amplitudes
        amplitudes = frame.amplitudes
        amplitude_variance = self._variance(amplitudes)
        mean_amplitude = self._mean(amplitudes)
        
        # Process phases with unwrapping
        unwrapped = self.unwrap_phase(frame.phases)
        phase_variance = self._variance(unwrapped)
        mean_phase = self._mean(unwrapped)
        
        # Calculate motion energy (weighted combination)
        motion_energy = round(
            _AMPLITUDE_WEIGHT * amplitude_variance + _PHASE_WEIGHT * phase_variance,
            8
        )
        
        # Normalize energy by mean amplitude
        normalized_energy = round(
            motion_energy / max(1e-9, mean_amplitude),
            8
        )
        
        # Store performance metrics
        processing_time = (time.perf_counter() - start_time) * 1000  # Convert to ms
        self._performance_stats['last_processing_time_ms'] = processing_time
        
        return CSIFeatures(
            amplitude_variance=amplitude_variance,
            phase_variance=phase_variance,
            motion_energy=motion_energy,
            normalized_energy=normalized_energy,
            mean_amplitude=mean_amplitude,
            mean_phase=mean_phase
        )
    
    # -- Frame analysis -----------------------------------------------------
    
    def analyze_frame(self, frame: CSIFrame) -> SensingResult:
        """Process a single CSI frame and return detailed sensing results."""
        import time
        start_time = time.perf_counter()
        
        features = self.extract_features(frame)
        now = datetime.now(timezone.utc).isoformat()
        
        # Apply mode-specific thresholds
        energy = features.normalized_energy
        
        if self._mode in ["motion_detection", "activity_recognition"]:
            if energy >= _MOTION_THRESHOLD:
                status = "motion_detected"
                confidence = min(_MAX_MOTION_CONFIDENCE, _MOTION_CONFIDENCE_BASE + energy)
            elif energy >= _PRESENCE_THRESHOLD:
                status = "potential_activity"
                confidence = min(_MAX_PRESENCE_CONFIDENCE, _PRESENCE_CONFIDENCE_BASE + energy)
            else:
                status = "static_environment"
                confidence = max(_MIN_CLEAR_CONFIDENCE, _CLEAR_CONFIDENCE_BASE - energy)
        else:  # presence_sensing, occupancy_tracking, environmental_monitoring
            if energy >= _PRESENCE_THRESHOLD:
                status = "presence_detected"
                confidence = min(_MAX_PRESENCE_CONFIDENCE, _PRESENCE_CONFIDENCE_BASE + energy * 1.5)
            else:
                status = "no_presence"
                confidence = max(_MIN_CLEAR_CONFIDENCE, _CLEAR_CONFIDENCE_BASE - energy)
        
        processing_time = (time.perf_counter() - start_time) * 1000
        
        return SensingResult(
            status=status,
            confidence=round(confidence, 3),
            motion_energy=features.motion_energy,
            amplitude_variance=features.amplitude_variance,
            phase_variance=features.phase_variance,
            mean_amplitude=features.mean_amplitude,
            mean_phase=features.mean_phase,
            subcarrier_count=len(frame.amplitudes),
            processing_time_ms=round(processing_time, 3),
            generated_at=now
        )
    
    # -- Stream analysis ----------------------------------------------------
    
    def analyze_stream(self, frames: Iterable[CSIFrame]) -> StreamSummary:
        """Analyze a complete stream of CSI frames and return comprehensive summary."""
        import time
        stream_start = time.perf_counter()
        
        results = [self.analyze_frame(f) for f in frames]
        
        if not results:
            return StreamSummary(
                status="empty_stream",
                frames=0,
                motion_frames=0,
                presence_frames=0,
                confidence_distribution={},
                average_confidence=0.0,
                average_motion_energy=0.0,
                total_processing_time_ms=0.0,
                capability="wifi_csi_processor_v2",
                results=()
            )
        
        # Aggregate statistics
        motion_frames = sum(1 for r in results if r.status in ["motion_detected", "potential_activity"])
        presence_frames = sum(1 for r in results if r.status in ["presence_detected", "potential_activity"])
        
        confidence_values = [r.confidence for r in results]
        motion_energies = [r.motion_energy for r in results]
        
        # Calculate confidence distribution
        conf_dist = {
            "high": len([c for c in confidence_values if c >= 0.7]),
            "medium": len([c for c in confidence_values if 0.4 <= c < 0.7]),
            "low": len([c for c in confidence_values if c < 0.4])
        }
        
        # Determine overall status
        if motion_frames > len(results) * 0.3:
            summary_status = "high_activity"
        elif motion_frames > 0:
            summary_status = "moderate_activity"
        elif presence_frames > len(results) * 0.5:
            summary_status = "occupancy_detected"
        elif presence_frames > 0:
            summary_status = "intermittent_presence"
        else:
            summary_status = "inactive"
        
        total_processing_time = (time.perf_counter() - stream_start) * 1000
        
        return StreamSummary(
            status=summary_status,
            frames=len(results),
            motion_frames=motion_frames,
            presence_frames=presence_frames,
            confidence_distribution=conf_dist,
            average_confidence=round(mean(confidence_values), 3),
            average_motion_energy=round(mean(motion_energies), 6),
            total_processing_time_ms=round(total_processing_time, 3),
            capability="wifi_csi_processor_v2",
            results=tuple(r.to_dict() for r in results)
        )
    
    def get_performance_stats(self) -> dict[str, float]:
        """Return performance statistics for the processor."""
        return self._performance_stats.copy()


# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------

def generate_synthetic_csi_stream(
    frames: int = 10,
    *,
    motion: bool = True,
    subcarriers: int = _DEFAULT_SUBCARRIERS,
    base_timestamp_ms: int = 1_800_000_000_000,
    frame_interval_ms: int = 50,
    noise_level: float = 0.05,
) -> list[CSIFrame]:
    """Generate synthetic CSI frames for testing and development.
    
    Args:
        frames: Number of frames to generate
        motion: When True, inject motion patterns into the signal
        subcarriers: Number of OFDM subcarriers per frame
        base_timestamp_ms: Millisecond timestamp for the first frame
        frame_interval_ms: Millisecond gap between consecutive frames
        noise_level: Level of random noise to add (0.0 to 1.0)
    
    Returns:
        List of CSIFrame objects
    """
    n_frames = max(1, frames)
    subcarriers = max(_MIN_SUBCARRIERS, min(subcarriers, _MAX_SUBCARRIERS))
    
    # Cache math functions for performance
    _sin = math.sin
    _cos = math.cos
    
    frames_list: list[CSIFrame] = []
    
    for fi in range(n_frames):
        amplitudes: list[float] = []
        phases: list[float] = []
        
        # Motion pattern intensity
        motion_intensity = 1.0 if motion else 0.1
        motion_freq = (fi / frame_interval_ms) * 10  # Hz
        
        for sc in range(subcarriers):
            # Amplitude generation with realistic patterns
            base_amplitude = 1.0 + 0.1 * _sin(sc / 5.0)
            motion_component = motion_intensity * 0.3 * _sin(motion_freq * sc / 3.0 + fi / 2.0)
            noise = noise_level * (_sin(fi * sc) * 0.5 + 0.5)
            
            amplitude = base_amplitude + motion_component + noise
            amplitudes.append(round(amplitude, 6))
            
            # Phase generation with motion correlation
            base_phase = _cos(sc / 8.0) * 0.5
            motion_phase = motion_intensity * 0.4 * _sin(fi / 3.0 + sc / 4.0)
            phase = base_phase + motion_phase
            phases.append(round(phase, 6))
        
        frames_list.append(
            CSIFrame(
                timestamp_ms=base_timestamp_ms + fi * frame_interval_ms,
                amplitudes=tuple(amplitudes),
                phases=tuple(phases),
                device_id=f"synthetic-device-{fi % 5}",
                location_label="test_environment"
            )
        )
    
    return frames_list


@dataclass(frozen=True)
class SensingPolicy:
    """Privacy and safety policy for consent-gated Wi-Fi CSI demos."""

    consent_token: str | None = None
    require_consent: bool = True
    warnings: tuple[str, ...] = ("no_hidden_surveillance", "consented_lab_only")


class WifiCSISensingEngine:
    """Compatibility facade with consent checks and lab-safe result labels.

    The lower-level :class:`WifiCSIProcessor` handles signal processing. This
    facade preserves the public API used by Atena demos while making privacy
    controls explicit for every frame.
    """

    unwrap_phase = staticmethod(WifiCSIProcessor.unwrap_phase)

    def __init__(self, policy: SensingPolicy | None = None, mode: str = "motion_detection") -> None:
        self.policy = policy or SensingPolicy(require_consent=False)
        self.processor = WifiCSIProcessor(mode=mode)

    def _has_valid_consent(self, frame: CSIFrame) -> bool:
        if not self.policy.require_consent:
            return True
        return bool(frame.consent_token) and frame.consent_token == self.policy.consent_token

    def analyze_frame(self, frame: CSIFrame) -> SensingResult:
        if not self._has_valid_consent(frame):
            return SensingResult(
                status="blocked_by_policy",
                confidence=0.0,
                motion_energy=0.0,
                amplitude_variance=0.0,
                phase_variance=0.0,
                mean_amplitude=0.0,
                mean_phase=0.0,
                subcarrier_count=len(frame.amplitudes),
                processing_time_ms=0.0,
                generated_at=datetime.now(timezone.utc).isoformat(),
                warnings=("missing_or_invalid_consent", *self.policy.warnings),
            )

        result = self.processor.analyze_frame(frame)
        status_map = {
            "motion_detected": "motion",
            "potential_activity": "possible_presence",
            "presence_detected": "possible_presence",
            "static_environment": "clear",
            "no_presence": "clear",
        }
        return SensingResult(
            status=status_map.get(result.status, result.status),
            confidence=result.confidence,
            motion_energy=result.motion_energy,
            amplitude_variance=result.amplitude_variance,
            phase_variance=result.phase_variance,
            mean_amplitude=result.mean_amplitude,
            mean_phase=result.mean_phase,
            subcarrier_count=result.subcarrier_count,
            processing_time_ms=result.processing_time_ms,
            generated_at=result.generated_at,
            warnings=self.policy.warnings,
        )

    def analyze_stream(self, frames: Iterable[CSIFrame]) -> JsonDict:
        results = [self.analyze_frame(frame) for frame in frames]
        blocked = sum(1 for result in results if result.status == "blocked_by_policy")
        motion = sum(1 for result in results if result.status == "motion")
        possible_presence = sum(1 for result in results if result.status == "possible_presence")

        if not results:
            status = "empty_stream"
        elif blocked == len(results):
            status = "blocked_by_policy"
        elif motion > 0:
            status = "motion"
        elif possible_presence > 0:
            status = "possible_presence"
        else:
            status = "clear"

        confidences = [result.confidence for result in results]
        energies = [result.motion_energy for result in results]
        return {
            "capability": "wifi_csi_presence_sensing_lab",
            "status": status,
            "frames": len(results),
            "blocked_frames": blocked,
            "motion_frames": motion,
            "presence_frames": possible_presence,
            "average_confidence": round(mean(confidences), 3) if confidences else 0.0,
            "average_motion_energy": round(mean(energies), 6) if energies else 0.0,
            "safety_note": "Execução consentida para laboratório; proibido uso para vigilância oculta.",
            "results": [result.to_dict() for result in results],
        }


def build_demo_report(*, motion: bool = True) -> JsonDict:
    """Build a deterministic, consent-safe Wi-Fi CSI demo payload."""
    token = "demo-consent"
    frames = [
        CSIFrame(
            timestamp_ms=frame.timestamp_ms,
            amplitudes=frame.amplitudes,
            phases=frame.phases,
            device_id=frame.device_id,
            location_label=frame.location_label,
            consent_token=token,
        )
        for frame in generate_synthetic_csi_stream(frames=6, motion=motion)
    ]
    return WifiCSISensingEngine(SensingPolicy(consent_token=token)).analyze_stream(frames)


# ---------------------------------------------------------------------------
# Advanced processing utilities
# ---------------------------------------------------------------------------

class BatchProcessor:
    """Process large batches of CSI frames efficiently."""
    
    def __init__(self, processor: WifiCSIProcessor, batch_size: int = 100):
        self.processor = processor
        self.batch_size = batch_size
        self.buffer: list[CSIFrame] = []
    
    def add_frame(self, frame: CSIFrame) -> list[SensingResult] | None:
        """Add a frame to the batch buffer. Returns results when batch is full."""
        self.buffer.append(frame)
        
        if len(self.buffer) >= self.batch_size:
            results = [self.processor.analyze_frame(f) for f in self.buffer]
            self.buffer.clear()
            return results
        return None
    
    def flush(self) -> list[SensingResult]:
        """Process any remaining frames in the buffer."""
        if not self.buffer:
            return []
        
        results = [self.processor.analyze_frame(f) for f in self.buffer]
        self.buffer.clear()
        return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wi-Fi CSI Processing System - High-Performance Signal Analysis",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--frames", "-n",
        type=int,
        default=20,
        help="Number of frames to process"
    )
    parser.add_argument(
        "--motion",
        action="store_true",
        default=True,
        help="Generate motion pattern in synthetic data"
    )
    parser.add_argument(
        "--no-motion",
        action="store_true",
        help="Generate static environment data"
    )
    parser.add_argument(
        "--mode", "-m",
        choices=list(ALLOWED_MODES),
        default="motion_detection",
        help="Processing mode"
    )
    parser.add_argument(
        "--subcarriers", "-s",
        type=int,
        default=_DEFAULT_SUBCARRIERS,
        help="Number of subcarriers per frame"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full JSON results"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed processing information"
    )
    
    args = parser.parse_args(list(argv) if argv is not None else None)
    
    # Generate synthetic data
    use_motion = not args.no_motion if args.no_motion else args.motion
    
    if args.verbose:
        print(f"Generating {args.frames} frames with {args.subcarriers} subcarriers...")
        print(f"Mode: {args.mode}, Motion: {use_motion}")
    
    stream = generate_synthetic_csi_stream(
        frames=args.frames,
        motion=use_motion,
        subcarriers=args.subcarriers
    )
    
    # Process data
    processor = WifiCSIProcessor(mode=args.mode)
    summary = processor.analyze_stream(stream)
    
    # Output results
    if args.json:
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*50}")
        print(f"CSI Processing Summary")
        print(f"{'='*50}")
        print(f"Status: {summary.status}")
        print(f"Frames processed: {summary.frames}")
        print(f"Motion frames: {summary.motion_frames}")
        print(f"Presence frames: {summary.presence_frames}")
        print(f"Average confidence: {summary.average_confidence}")
        print(f"Average motion energy: {summary.average_motion_energy}")
        print(f"Total processing time: {summary.total_processing_time_ms:.2f} ms")
        print(f"\nConfidence Distribution:")
        print(f"  High: {summary.confidence_distribution['high']} frames")
        print(f"  Medium: {summary.confidence_distribution['medium']} frames")
        print(f"  Low: {summary.confidence_distribution['low']} frames")
        print(f"{'='*50}")
        
        if args.verbose and summary.results:
            print("\nFirst 5 frame details:")
            for i, result in enumerate(summary.results[:5]):
                print(f"  Frame {i+1}: {result['status']} (conf={result['confidence']}, energy={result['motion_energy']})")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

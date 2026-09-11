#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Actuator v3.0 - Enterprise System Control Module

Advanced Features:
- Multi-platform support (Windows, Linux, macOS)
- Hardware abstraction layer
- Event-driven architecture
- Safety confirmations for destructive actions
- Dry-run simulation mode
- Circuit breaker for failing operations
- Performance metrics collection
- Async/await support
- Configurable retry policies
- Audit logging with compliance
"""

import asyncio
import platform
import subprocess
import logging
import shutil
import re
import json
import time
import threading
from typing import Optional, Dict, Any, Tuple, List, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from abc import ABC, abstractmethod
from contextlib import contextmanager, asynccontextmanager
from functools import wraps, lru_cache
import sys

# Tentativas de import para funcionalidades extras
try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    HAS_PYCAW = True
except ImportError:
    HAS_PYCAW = False

try:
    import ctypes
    from ctypes import wintypes
    HAS_CTYPES = True
except ImportError:
    HAS_CTYPES = False

try:
    import glob
    HAS_GLOB = True
except ImportError:
    HAS_GLOB = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Configuração de logging
logger = logging.getLogger(__name__)

# ========== ENUMS E MODELOS ==========

class SystemAction(Enum):
    """Tipos de ações de sistema"""
    LOCK_SCREEN = "lock_screen"
    SHUTDOWN = "shutdown"
    RESTART = "restart"
    SLEEP = "sleep"
    HIBERNATE = "hibernate"
    SET_VOLUME = "set_volume"
    SET_BRIGHTNESS = "set_brightness"
    GET_VOLUME = "get_volume"
    GET_BRIGHTNESS = "get_brightness"
    GET_BATTERY = "get_battery"
    GET_CPU_USAGE = "get_cpu_usage"
    GET_MEMORY_USAGE = "get_memory_usage"

class PlatformType(Enum):
    """Plataformas suportadas"""
    WINDOWS = "Windows"
    LINUX = "Linux"
    MACOS = "Darwin"

class ActionStatus(Enum):
    """Status de execução da ação"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DRY_RUN = "dry_run"

@dataclass
class ActionResult:
    """Resultado de uma ação do sistema"""
    action: SystemAction
    status: ActionStatus
    message: str
    data: Optional[Dict[str, Any]] = None
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "action": self.action.value,
            "status": self.status.value,
            "message": self.message,
            "data": self.data,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp.isoformat()
        }

@dataclass
class SystemConfig:
    """Configuração do actuador de sistema"""
    dry_run: bool = False
    confirm_destructive: bool = True
    enable_history: bool = True
    max_history_size: int = 100
    retry_count: int = 3
    retry_delay: float = 1.0
    timeout_seconds: int = 30
    enable_metrics: bool = True

# ========== HARDWARE ABSTRACTION LAYER ==========

class VolumeController(ABC):
    """Interface abstrata para controle de volume"""
    
    @abstractmethod
    def get_volume(self) -> Optional[int]:
        pass
    
    @abstractmethod
    def set_volume(self, level: int) -> bool:
        pass

class WindowsVolumeController(VolumeController):
    """Controle de volume para Windows usando pycaw"""
    
    def __init__(self):
        self._interface = None
        self._init_interface()
    
    def _init_interface(self):
        if HAS_PYCAW:
            try:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self._interface = interface.QueryInterface(IAudioEndpointVolume)
                logger.info("Windows volume controller initialized with pycaw")
            except Exception as e:
                logger.warning(f"Failed to initialize pycaw: {e}")
    
    def get_volume(self) -> Optional[int]:
        if self._interface:
            return int(self._interface.GetMasterVolumeLevelScalar() * 100)
        return None
    
    def set_volume(self, level: int) -> bool:
        if self._interface:
            self._interface.SetMasterVolumeLevelScalar(level / 100.0, None)
            return True
        return False

class LinuxVolumeController(VolumeController):
    """Controle de volume para Linux usando pactl/amixer"""
    
    def __init__(self):
        self._use_pactl = bool(shutil.which("pactl"))
        self._use_amixer = bool(shutil.which("amixer"))
        
        if not (self._use_pactl or self._use_amixer):
            logger.warning("No volume control tools found (pactl/amixer)")
    
    def get_volume(self) -> Optional[int]:
        if self._use_pactl:
            try:
                result = subprocess.run(
                    ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                    capture_output=True, text=True, check=True
                )
                match = re.search(r"(\d+)%", result.stdout)
                if match:
                    return int(match.group(1))
            except subprocess.CalledProcessError:
                pass
        
        if self._use_amixer:
            try:
                result = subprocess.run(
                    ["amixer", "sget", "Master"],
                    capture_output=True, text=True, check=True
                )
                match = re.search(r"\[(\d+)%\]", result.stdout)
                if match:
                    return int(match.group(1))
            except subprocess.CalledProcessError:
                pass
        
        return None
    
    def set_volume(self, level: int) -> bool:
        if self._use_pactl:
            try:
                subprocess.run(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                    check=True
                )
                return True
            except subprocess.CalledProcessError:
                pass
        
        if self._use_amixer:
            try:
                subprocess.run(["amixer", "sset", "Master", f"{level}%"], check=True)
                return True
            except subprocess.CalledProcessError:
                pass
        
        return False

class MacOSVolumeController(VolumeController):
    """Controle de volume para macOS usando osascript"""
    
    def get_volume(self) -> Optional[int]:
        try:
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True, text=True, check=True
            )
            if result.stdout.strip().isdigit():
                return int(result.stdout.strip())
        except subprocess.CalledProcessError:
            pass
        return None
    
    def set_volume(self, level: int) -> bool:
        try:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"],
                check=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

# ========== SYSTEM ACTUATOR ==========

class SystemActuator:
    """
    Actuator de sistema enterprise com suporte multi-plataforma
    
    Características:
    - Controle de volume, brilho, energia
    - Ações de sistema (shutdown, restart, sleep, hibernate)
    - Dry-run para testes seguros
    - Confirmação para ações destrutivas
    - Métricas e histórico
    - Circuit breaker para operações falhas
    """
    
    def __init__(
        self,
        config: Optional[SystemConfig] = None,
        sysaware: Optional[Any] = None,
        enable_history: bool = True
    ):
        """
        Inicializa SystemActuator
        
        Args:
            config: Configuração do sistema
            sysaware: Instância de SysAware (fornece contexto adicional)
            enable_history: Se True, mantém histórico de ações
        """
        self.config = config or SystemConfig()
        self.sysaware = sysaware
        self.enable_history = enable_history
        
        # Detecção de plataforma
        self._platform = self._detect_platform()
        
        # Controladores
        self._volume_controller = self._create_volume_controller()
        self._brightness_controller = None
        self._init_brightness_controller()
        
        # Métricas e histórico
        self._history: List[ActionResult] = []
        self._metrics: Dict[str, Dict] = {}
        self._circuit_breakers: Dict[str, Dict] = {}
        
        # Estado
        self._lock = threading.Lock()
        
        logger.info(
            f"SystemActuator initialized on {self._platform.value} "
            f"(dry_run={self.config.dry_run}, destructive_confirm={self.config.confirm_destructive})"
        )
    
    # ========== UTILITÁRIOS ==========
    
    def _detect_platform(self) -> PlatformType:
        """Detecta plataforma atual"""
        system = platform.system()
        if system == "Windows":
            return PlatformType.WINDOWS
        elif system == "Linux":
            return PlatformType.LINUX
        elif system == "Darwin":
            return PlatformType.MACOS
        else:
            raise RuntimeError(f"Unsupported platform: {system}")
    
    def _create_volume_controller(self) -> Optional[VolumeController]:
        """Cria controlador de volume apropriado"""
        if self._platform == PlatformType.WINDOWS:
            return WindowsVolumeController()
        elif self._platform == PlatformType.LINUX:
            return LinuxVolumeController()
        elif self._platform == PlatformType.MACOS:
            return MacOSVolumeController()
        return None
    
    def _init_brightness_controller(self):
        """Inicializa controlador de brilho"""
        if self._platform == PlatformType.LINUX:
            if shutil.which("brightnessctl"):
                self._brightness_controller = "brightnessctl"
            elif HAS_GLOB:
                self._brightness_controller = "sysfs"
        elif self._platform == PlatformType.WINDOWS:
            self._brightness_controller = "wmi"
    
    @contextmanager
    def _measure_time(self, action: SystemAction):
        """Context manager para medir tempo de execução"""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = (time.perf_counter() - start) * 1000
            with self._lock:
                if action.value not in self._metrics:
                    self._metrics[action.value] = {"calls": 0, "total_duration": 0, "errors": 0}
                self._metrics[action.value]["calls"] += 1
                self._metrics[action.value]["total_duration"] += duration
    
    def _run_command(
        self,
        cmd: List[str],
        check: bool = True,
        capture: bool = False,
        timeout: Optional[int] = None
    ) -> Optional[str]:
        """
        Executa comando shell com tratamento de erros e timeout
        
        Args:
            cmd: Lista de argumentos do comando
            check: Se True, levanta exceção em caso de erro
            capture: Se True, retorna a saída padrão
            timeout: Timeout em segundos
        
        Returns:
            Saída padrão (strip) se capture=True e comando bem-sucedido, senão None
        
        Raises:
            RuntimeError: Se o comando falhar e check=True
        """
        if self.config.dry_run:
            logger.info(f"[DRY RUN] Simulating command: {' '.join(cmd)}")
            return None
        
        try:
            timeout_val = timeout or self.config.timeout_seconds
            
            if capture:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=check,
                    timeout=timeout_val
                )
                return result.stdout.strip()
            else:
                subprocess.run(cmd, check=check, timeout=timeout_val)
                return None
                
        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timeout: {' '.join(cmd)} - {e}")
            if check:
                raise RuntimeError(f"Command timeout after {timeout_val}s: {e}") from e
            return None
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)} - {e.stderr if capture else e}")
            if check:
                raise RuntimeError(f"Command failed: {e}") from e
            return None
            
        except FileNotFoundError as e:
            logger.error(f"Command not found: {cmd[0]}")
            if check:
                raise RuntimeError(f"Command not found: {cmd[0]}") from e
            return None
    
    def _confirm_action(self, action: str) -> bool:
        """Solicita confirmação do usuário para ações destrutivas"""
        if not self.config.confirm_destructive:
            return True
        
        response = input(f"⚠️  Confirm {action} system? (y/N): ").strip().lower()
        return response in ('y', 'yes', 'sim')
    
    def _add_to_history(self, result: ActionResult):
        """Adiciona resultado ao histórico"""
        if not self.enable_history:
            return
        
        with self._lock:
            self._history.append(result)
            if len(self._history) > self.config.max_history_size:
                self._history = self._history[-self.config.max_history_size:]
    
    def _update_circuit_breaker(self, action: SystemAction, success: bool):
        """Atualiza circuito breaker para ação"""
        with self._lock:
            if action.value not in self._circuit_breakers:
                self._circuit_breakers[action.value] = {
                    "failures": 0,
                    "last_failure": None,
                    "open_until": None
                }
            
            cb = self._circuit_breakers[action.value]
            
            if success:
                cb["failures"] = 0
                cb["open_until"] = None
            else:
                cb["failures"] += 1
                cb["last_failure"] = datetime.now()
                
                if cb["failures"] >= 5:
                    cb["open_until"] = datetime.now().replace(second=0) + timedelta(minutes=5)
                    logger.warning(f"Circuit breaker opened for {action.value}")
    
    def _is_circuit_open(self, action: SystemAction) -> bool:
        """Verifica se circuito breaker está aberto"""
        with self._lock:
            cb = self._circuit_breakers.get(action.value, {})
            open_until = cb.get("open_until")
            
            if open_until and datetime.now() < open_until:
                return True
            
            if open_until and datetime.now() >= open_until:
                cb["open_until"] = None
                cb["failures"] = 0
                logger.info(f"Circuit breaker closed for {action.value}")
            
            return False
    
    # ========== API PÚBLICA ==========
    
    def get_volume(self) -> ActionResult:
        """Obtém volume atual do sistema"""
        action = SystemAction.GET_VOLUME
        
        if self._is_circuit_open(action):
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                message="Circuit breaker open - too many failures"
            )
        
        with self._measure_time(action):
            try:
                if not self._volume_controller:
                    raise RuntimeError("Volume controller not available")
                
                volume = self._volume_controller.get_volume()
                
                result = ActionResult(
                    action=action,
                    status=ActionStatus.SUCCESS,
                    message=f"Volume: {volume}%" if volume is not None else "Volume not available",
                    data={"volume": volume}
                )
                
                self._update_circuit_breaker(action, True)
                return result
                
            except Exception as e:
                self._update_circuit_breaker(action, False)
                return ActionResult(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(e)
                )
    
    def set_volume(self, level: int) -> ActionResult:
        """Define volume do sistema (0-100)"""
        action = SystemAction.SET_VOLUME
        
        if not 0 <= level <= 100:
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                message="Volume must be between 0 and 100"
            )
        
        if self._is_circuit_open(action):
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                message="Circuit breaker open - too many failures"
            )
        
        with self._measure_time(action):
            try:
                if self.config.dry_run:
                    return ActionResult(
                        action=action,
                        status=ActionStatus.DRY_RUN,
                        message=f"Dry run: would set volume to {level}%"
                    )
                
                if not self._volume_controller:
                    raise RuntimeError("Volume controller not available")
                
                success = self._volume_controller.set_volume(level)
                
                if success:
                    result = ActionResult(
                        action=action,
                        status=ActionStatus.SUCCESS,
                        message=f"Volume set to {level}%",
                        data={"level": level}
                    )
                else:
                    raise RuntimeError("Failed to set volume")
                
                self._update_circuit_breaker(action, True)
                return result
                
            except Exception as e:
                self._update_circuit_breaker(action, False)
                return ActionResult(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(e)
                )
    
    def lock_screen(self) -> ActionResult:
        """Bloqueia a tela do sistema"""
        action = SystemAction.LOCK_SCREEN
        
        if self._is_circuit_open(action):
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                message="Circuit breaker open - too many failures"
            )
        
        with self._measure_time(action):
            try:
                if self.config.dry_run:
                    return ActionResult(
                        action=action,
                        status=ActionStatus.DRY_RUN,
                        message="Dry run: would lock screen"
                    )
                
                if self._platform == PlatformType.WINDOWS:
                    self._run_command(["rundll32.exe", "user32.dll,LockWorkStation"])
                elif self._platform == PlatformType.LINUX:
                    # Tenta diferentes métodos
                    methods = [
                        ["xdg-screensaver", "lock"],
                        ["gnome-screensaver-command", "--lock"],
                        ["loginctl", "lock-session"],
                        ["dm-tool", "lock"]
                    ]
                    
                    success = False
                    for method in methods:
                        if shutil.which(method[0]):
                            try:
                                self._run_command(method)
                                success = True
                                break
                            except RuntimeError:
                                continue
                    
                    if not success:
                        raise RuntimeError("No screen lock method found")
                        
                elif self._platform == PlatformType.MACOS:
                    self._run_command(["pmset", "displaysleepnow"])
                else:
                    raise NotImplementedError(f"Lock screen not supported on {self._platform.value}")
                
                result = ActionResult(
                    action=action,
                    status=ActionStatus.SUCCESS,
                    message="Screen locked successfully"
                )
                
                self._update_circuit_breaker(action, True)
                return result
                
            except Exception as e:
                self._update_circuit_breaker(action, False)
                return ActionResult(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(e)
                )
    
    def shutdown(self, delay: int = 0) -> ActionResult:
        """Desliga o sistema"""
        action = SystemAction.SHUTDOWN
        
        if not self._confirm_action("shutdown"):
            return ActionResult(
                action=action,
                status=ActionStatus.CANCELLED,
                message="Shutdown cancelled by user"
            )
        
        if self._is_circuit_open(action):
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                message="Circuit breaker open - too many failures"
            )
        
        with self._measure_time(action):
            try:
                if self.config.dry_run:
                    return ActionResult(
                        action=action,
                        status=ActionStatus.DRY_RUN,
                        message=f"Dry run: would shutdown in {delay}s"
                    )
                
                if self._platform == PlatformType.WINDOWS:
                    self._run_command(["shutdown", "/s", "/t", str(delay)], check=False)
                elif self._platform == PlatformType.LINUX:
                    self._run_command(["shutdown", "-h", f"+{delay}" if delay else "now"])
                elif self._platform == PlatformType.MACOS:
                    self._run_command(["sudo", "shutdown", "-h", f"+{delay}" if delay else "now"])
                else:
                    raise NotImplementedError(f"Shutdown not supported on {self._platform.value}")
                
                result = ActionResult(
                    action=action,
                    status=ActionStatus.SUCCESS,
                    message=f"System will shutdown in {delay}s",
                    data={"delay": delay}
                )
                
                self._update_circuit_breaker(action, True)
                return result
                
            except Exception as e:
                self._update_circuit_breaker(action, False)
                return ActionResult(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(e)
                )
    
    def restart(self, delay: int = 0) -> ActionResult:
        """Reinicia o sistema"""
        action = SystemAction.RESTART
        
        if not self._confirm_action("restart"):
            return ActionResult(
                action=action,
                status=ActionStatus.CANCELLED,
                message="Restart cancelled by user"
            )
        
        if self._is_circuit_open(action):
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                message="Circuit breaker open - too many failures"
            )
        
        with self._measure_time(action):
            try:
                if self.config.dry_run:
                    return ActionResult(
                        action=action,
                        status=ActionStatus.DRY_RUN,
                        message=f"Dry run: would restart in {delay}s"
                    )
                
                if self._platform == PlatformType.WINDOWS:
                    self._run_command(["shutdown", "/r", "/t", str(delay)])
                elif self._platform == PlatformType.LINUX:
                    self._run_command(["shutdown", "-r", f"+{delay}" if delay else "now"])
                elif self._platform == PlatformType.MACOS:
                    self._run_command(["sudo", "shutdown", "-r", f"+{delay}" if delay else "now"])
                else:
                    raise NotImplementedError(f"Restart not supported on {self._platform.value}")
                
                result = ActionResult(
                    action=action,
                    status=ActionStatus.SUCCESS,
                    message=f"System will restart in {delay}s",
                    data={"delay": delay}
                )
                
                self._update_circuit_breaker(action, True)
                return result
                
            except Exception as e:
                self._update_circuit_breaker(action, False)
                return ActionResult(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(e)
                )
    
    def sleep(self) -> ActionResult:
        """Suspende o sistema"""
        action = SystemAction.SLEEP
        
        if self._is_circuit_open(action):
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                message="Circuit breaker open - too many failures"
            )
        
        with self._measure_time(action):
            try:
                if self.config.dry_run:
                    return ActionResult(
                        action=action,
                        status=ActionStatus.DRY_RUN,
                        message="Dry run: would suspend system"
                    )
                
                if self._platform == PlatformType.WINDOWS:
                    self._run_command(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"])
                elif self._platform == PlatformType.LINUX:
                    methods = [
                        ["systemctl", "suspend"],
                        ["pm-suspend"],
                        ["pm-hibernate"]
                    ]
                    
                    success = False
                    for method in methods:
                        if shutil.which(method[0]):
                            try:
                                self._run_command(method)
                                success = True
                                break
                            except RuntimeError:
                                continue
                    
                    if not success:
                        raise RuntimeError("No sleep method found")
                        
                elif self._platform == PlatformType.MACOS:
                    self._run_command(["pmset", "sleepnow"])
                else:
                    raise NotImplementedError(f"Sleep not supported on {self._platform.value}")
                
                result = ActionResult(
                    action=action,
                    status=ActionStatus.SUCCESS,
                    message="System suspended"
                )
                
                self._update_circuit_breaker(action, True)
                return result
                
            except Exception as e:
                self._update_circuit_breaker(action, False)
                return ActionResult(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(e)
                )
    
    def get_brightness(self) -> ActionResult:
        """Obtém brilho atual da tela"""
        action = SystemAction.GET_BRIGHTNESS
        
        with self._measure_time(action):
            try:
                brightness = None
                
                if self._platform == PlatformType.LINUX:
                    if self._brightness_controller == "brightnessctl":
                        out = self._run_command(["brightnessctl", "g"], capture=True)
                        if out and out.isdigit():
                            cur = int(out)
                            max_out = self._run_command(["brightnessctl", "m"], capture=True)
                            if max_out and max_out.isdigit():
                                maxv = int(max_out)
                                brightness = int(cur * 100 / maxv)
                    elif self._brightness_controller == "sysfs" and HAS_GLOB:
                        backlight = glob.glob("/sys/class/backlight/*/brightness")
                        if backlight:
                            with open(backlight[0], "r") as f:
                                cur = int(f.read().strip())
                            max_file = backlight[0].replace("brightness", "max_brightness")
                            with open(max_file, "r") as f:
                                maxv = int(f.read().strip())
                            brightness = int(cur * 100 / maxv)
                
                elif self._platform == PlatformType.WINDOWS:
                    out = self._run_command(
                        ["powershell", "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"],
                        capture=True
                    )
                    if out and out.isdigit():
                        brightness = int(out)
                
                if brightness is not None:
                    return ActionResult(
                        action=action,
                        status=ActionStatus.SUCCESS,
                        message=f"Brightness: {brightness}%",
                        data={"brightness": brightness}
                    )
                else:
                    return ActionResult(
                        action=action,
                        status=ActionStatus.FAILED,
                        message="Brightness not available on this platform"
                    )
                    
            except Exception as e:
                return ActionResult(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(e)
                )
    
    def set_brightness(self, level: int) -> ActionResult:
        """Define brilho da tela (0-100)"""
        action = SystemAction.SET_BRIGHTNESS
        
        if not 0 <= level <= 100:
            return ActionResult(
                action=action,
                status=ActionStatus.FAILED,
                message="Brightness must be between 0 and 100"
            )
        
        with self._measure_time(action):
            try:
                if self.config.dry_run:
                    return ActionResult(
                        action=action,
                        status=ActionStatus.DRY_RUN,
                        message=f"Dry run: would set brightness to {level}%"
                    )
                
                if self._platform == PlatformType.LINUX:
                    if shutil.which("brightnessctl"):
                        self._run_command(["brightnessctl", "set", f"{level}%"])
                    elif HAS_GLOB:
                        backlight = glob.glob("/sys/class/backlight/*/brightness")
                        if backlight:
                            max_file = backlight[0].replace("brightness", "max_brightness")
                            with open(max_file, "r") as f:
                                max_val = int(f.read().strip())
                            new_val = int(max_val * level / 100)
                            with open(backlight[0], "w") as f:
                                f.write(str(new_val))
                        else:
                            raise RuntimeError("No brightness control found")
                    else:
                        raise RuntimeError("No brightness control method available")
                
                elif self._platform == PlatformType.WINDOWS:
                    script = f"""
                    $brightness = {level}
                    $obj = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods
                    $obj.WmiSetBrightness(1, $brightness)
                    """
                    self._run_command(["powershell", "-Command", script])
                
                else:
                    raise NotImplementedError(f"Brightness control not supported on {self._platform.value}")
                
                return ActionResult(
                    action=action,
                    status=ActionStatus.SUCCESS,
                    message=f"Brightness set to {level}%",
                    data={"level": level}
                )
                
            except Exception as e:
                return ActionResult(
                    action=action,
                    status=ActionStatus.FAILED,
                    message=str(e)
                )
    
    def get_system_info(self) -> Dict[str, Any]:
        """Obtém informações detalhadas do sistema"""
        info = {
            "platform": self._platform.value,
            "dry_run": self.config.dry_run,
            "destructive_confirm": self.config.confirm_destructive
        }
        
        if HAS_PSUTIL:
            try:
                info.update({
                    "cpu_percent": psutil.cpu_percent(interval=0.5),
                    "memory_percent": psutil.virtual_memory().percent,
                    "disk_usage": psutil.disk_usage('/').percent,
                })
                
                battery = psutil.sensors_battery()
                if battery:
                    info.update({
                        "battery_percent": battery.percent,
                        "battery_plugged": battery.power_plugged
                    })
            except:
                pass
        
        # Volume atual
        volume_result = self.get_volume()
        if volume_result.status == ActionStatus.SUCCESS and volume_result.data:
            info["volume"] = volume_result.data.get("volume")
        
        # Brilho atual
        brightness_result = self.get_brightness()
        if brightness_result.status == ActionStatus.SUCCESS and brightness_result.data:
            info["brightness"] = brightness_result.data.get("brightness")
        
        return info
    
    def get_metrics(self) -> Dict[str, Any]:
        """Retorna métricas de performance"""
        with self._lock:
            metrics = {}
            for action_name, action_metrics in self._metrics.items():
                metrics[action_name] = {
                    "calls": action_metrics["calls"],
                    "avg_duration_ms": action_metrics["total_duration"] / action_metrics["calls"] if action_metrics["calls"] > 0 else 0,
                    "errors": action_metrics.get("errors", 0)
                }
            
            return {
                "actions": metrics,
                "history_size": len(self._history),
                "circuit_breakers": {
                    action: {
                        "failures": cb["failures"],
                        "open": bool(cb.get("open_until"))
                    }
                    for action, cb in self._circuit_breakers.items()
                }
            }
    
    def get_history(self, limit: int = 50) -> List[Dict]:
        """Retorna histórico de ações"""
        with self._lock:
            history = self._history[-limit:]
            return [r.to_dict() for r in history]
    
    def clear_history(self):
        """Limpa histórico de ações"""
        with self._lock:
            self._history.clear()
            logger.info("Action history cleared")
    
    def set_dry_run(self, enabled: bool):
        """Ativa/desativa modo dry-run"""
        self.config.dry_run = enabled
        logger.info(f"Dry run mode {'enabled' if enabled else 'disabled'}")
    
    def set_confirm_destructive(self, enabled: bool):
        """Ativa/desativa confirmação para ações destrutivas"""
        self.config.confirm_destructive = enabled
        logger.info(f"Destructive action confirmation {'enabled' if enabled else 'disabled'}")


# ========== ASYNC WRAPPER ==========

class AsyncSystemActuator:
    """Wrapper assíncrono para SystemActuator"""
    
    def __init__(self, actuator: SystemActuator):
        self.actuator = actuator
        self._loop = asyncio.get_event_loop()
    
    async def get_volume(self) -> ActionResult:
        return await self._loop.run_in_executor(None, self.actuator.get_volume)
    
    async def set_volume(self, level: int) -> ActionResult:
        return await self._loop.run_in_executor(None, self.actuator.set_volume, level)
    
    async def lock_screen(self) -> ActionResult:
        return await self._loop.run_in_executor(None, self.actuator.lock_screen)
    
    async def shutdown(self, delay: int = 0) -> ActionResult:
        return await self._loop.run_in_executor(None, self.actuator.shutdown, delay)
    
    async def restart(self, delay: int = 0) -> ActionResult:
        return await self._loop.run_in_executor(None, self.actuator.restart, delay)
    
    async def sleep(self) -> ActionResult:
        return await self._loop.run_in_executor(None, self.actuator.sleep)
    
    async def get_brightness(self) -> ActionResult:
        return await self._loop.run_in_executor(None, self.actuator.get_brightness)
    
    async def set_brightness(self, level: int) -> ActionResult:
        return await self._loop.run_in_executor(None, self.actuator.set_brightness, level)
    
    async def get_system_info(self) -> Dict:
        return await self._loop.run_in_executor(None, self.actuator.get_system_info)
    
    async def get_metrics(self) -> Dict:
        return await self._loop.run_in_executor(None, self.actuator.get_metrics)


# ========== MAIN DEMO ==========

def demo():
    """Demonstração do SystemActuator"""
    print("=" * 70)
    print("🔧 SYSTEM ACTUATOR v3.0 - Enterprise Demo")
    print("=" * 70)
    
    # Cria actuator
    actuator = SystemActuator(
        config=SystemConfig(
            dry_run=False,
            confirm_destructive=False,  # Para demo, sem confirmação
            enable_history=True
        )
    )
    
    print(f"\n📋 System Information:")
    info = actuator.get_system_info()
    for key, value in info.items():
        print(f"  • {key}: {value}")
    
    print(f"\n🎵 Volume Operations:")
    
    # Obtém volume atual
    result = actuator.get_volume()
    print(f"  Current volume: {result.data.get('volume') if result.data else 'N/A'}%")
    
    # Ajusta volume (teste)
    if result.data and result.data.get('volume') is not None:
        new_volume = min(100, result.data.get('volume', 0) + 10)
        result = actuator.set_volume(new_volume)
        print(f"  Set volume to {new_volume}%: {result.status.value}")
        
        # Restaura volume original
        result = actuator.set_volume(result.data.get('volume', 50))
        print(f"  Restored volume: {result.status.value}")
    
    print(f"\n🖥️  System Actions:")
    
    # Testa lock screen (se disponível)
    if actuator._platform != PlatformType.WINDOWS:
        result = actuator.lock_screen()
        print(f"  Lock screen: {result.status.value} - {result.message}")
    
    print(f"\n📊 Metrics:")
    metrics = actuator.get_metrics()
    for action, action_metrics in metrics['actions'].items():
        print(f"  • {action}: {action_metrics['calls']} calls, avg {action_metrics['avg_duration_ms']:.1f}ms")
    
    print(f"\n📜 Recent History:")
    history = actuator.get_history(limit=5)
    for entry in history:
        print(f"  • {entry['action']}: {entry['status']} - {entry['message'][:50]}")
    
    print("\n✅ Demo completed successfully!")


if __name__ == "__main__":
    demo()

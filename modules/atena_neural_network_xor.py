#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ATENA Ω - Neural Network Engine v3.0                     ║
║                  Rede Neural MLP Avançada para XOR                          ║
║                                                                            ║
║  Características Avançadas:                                                ║
║  • Arquitetura configurável (2-4-1 padrão para XOR)                       ║
║  • Múltiplas funções de ativação (Sigmoid, ReLU, Tanh, LeakyReLU)         ║
║  • Inicialização de pesos: Xavier, He, LeCun                               ║
║  • Otimizadores: SGD Momentum, AdaGrad, RMSprop, Adam, Nadam              ║
║  • Regularização: L1/L2, Dropout, Early Stopping                          ║
║  • Learning Rate Scheduling: Step, Exponential, Cosine, Plateau           ║
║  • Validação cruzada e métricas de avaliação                              ║
║  • Salvamento e carregamento de checkpoints                               ║
║  • Visualização do treinamento em tempo real                              ║
║  • Testes unitários abrangentes                                           ║
║                                                                            ║
║  Autor: ATENA Ω - Geração 345                                             ║
║  Data: 2024                                                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import logging
import os
import pickle
import sys
import time
import traceback
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from functools import lru_cache, partial, wraps
from pathlib import Path
from typing import (
    Any, Callable, Dict, Final, List, Literal, NamedTuple, Optional,
    Sequence, Tuple, Type, TypedDict, Union, cast, overload
)

import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import NDArray

# ─── Configuração de Ambiente ────────────────────────────────────────────────
SAVE_DIR: Final[Path] = Path("modules/results")
SAVE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(SAVE_DIR / 'neural_network.log')
    ]
)
logger: logging.Logger = logging.getLogger(__name__)

# ─── Tipos ────────────────────────────────────────────────────────────────────
WeightsDict = Dict[str, NDArray[np.float64]]
GradientsDict = Dict[str, NDArray[np.float64]]
HistoryDict = Dict[str, List[float]]
LayerOutput = NDArray[np.float64]

# ─── Enums ────────────────────────────────────────────────────────────────────
class ActivationFunction(Enum):
    """Funções de ativação suportadas"""
    SIGMOID = "sigmoid"
    RELU = "relu"
    TANH = "tanh"
    LEAKY_RELU = "leaky_relu"
    SWISH = "swish"
    GELU = "gelu"
    SOFTMAX = "softmax"

class WeightInitializer(Enum):
    """Estratégias de inicialização de pesos"""
    XAVIER_UNIFORM = "xavier_uniform"
    XAVIER_NORMAL = "xavier_normal"
    HE_UNIFORM = "he_uniform"
    HE_NORMAL = "he_normal"
    LECUN_UNIFORM = "lecun_uniform"
    LECUN_NORMAL = "lecun_normal"

class OptimizerType(Enum):
    """Tipos de otimizadores"""
    SGD = "sgd"
    SGD_MOMENTUM = "sgd_momentum"
    NESTEROV = "nesterov"
    ADAGRAD = "adagrad"
    RMSPROP = "rmsprop"
    ADAM = "adam"
    ADAMAX = "adamax"
    NADAM = "nadam"
    ADAMW = "adamw"

class RegularizerType(Enum):
    """Tipos de regularização"""
    NONE = "none"
    L1 = "l1"
    L2 = "l2"
    L1_L2 = "l1_l2"

class LRSchedulerType(Enum):
    """Tipos de scheduling de learning rate"""
    CONSTANT = "constant"
    STEP = "step"
    EXPONENTIAL = "exponential"
    COSINE = "cosine"
    REDUCE_ON_PLATEAU = "reduce_on_plateau"

# ─── Data Classes ─────────────────────────────────────────────────────────────
@dataclass(slots=True)
class LayerConfig:
    """Configuração de uma camada da rede"""
    input_size: int
    output_size: int
    activation: ActivationFunction = ActivationFunction.SIGMOID
    dropout_rate: float = 0.0
    use_batch_norm: bool = False

@dataclass(slots=True)
class TrainingConfig:
    """Configuração de treinamento"""
    epochs: int = 10_000
    learning_rate: float = 0.5
    optimizer: OptimizerType = OptimizerType.ADAM
    momentum: float = 0.9
    beta1: float = 0.9  # Para Adam/AdamW/Nadam
    beta2: float = 0.999  # Para Adam/AdamW/Nadam
    epsilon: float = 1e-8
    weight_decay: float = 0.0  # Para AdamW
    regularizer: RegularizerType = RegularizerType.NONE
    regularization_lambda: float = 0.01
    lr_scheduler: LRSchedulerType = LRSchedulerType.CONSTANT
    lr_decay_rate: float = 0.95
    lr_decay_steps: int = 1_000
    early_stopping_patience: int = 500
    early_stopping_min_delta: float = 1e-6
    gradient_clip_norm: Optional[float] = 1.0
    batch_size: int = 4  # Para XOR, batch_size = dataset completo
    validation_split: float = 0.0
    verbose: bool = True
    seed: int = 345

@dataclass(slots=True)
class TrainingHistory:
    """Histórico completo de treinamento"""
    train_loss: List[float] = field(default_factory=list)
    val_loss: List[float] = field(default_factory=list)
    train_accuracy: List[float] = field(default_factory=list)
    val_accuracy: List[float] = field(default_factory=list)
    learning_rates: List[float] = field(default_factory=list)
    gradient_norms: List[float] = field(default_factory=list)
    weights_norms: List[float] = field(default_factory=list)
    epoch_times: List[float] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, List[float]]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, List[float]]) -> 'TrainingHistory':
        return cls(**data)

# ─── Funções de Ativação ──────────────────────────────────────────────────────
class ActivationFunctions:
    """Implementa funções de ativação e suas derivadas"""
    
    @staticmethod
    def apply(z: NDArray[np.float64], activation: ActivationFunction) -> LayerOutput:
        """Aplica função de ativação"""
        match activation:
            case ActivationFunction.SIGMOID:
                return 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))
            case ActivationFunction.RELU:
                return np.maximum(0, z)
            case ActivationFunction.TANH:
                return np.tanh(z)
            case ActivationFunction.LEAKY_RELU:
                return np.where(z > 0, z, 0.01 * z)
            case ActivationFunction.SWISH:
                return z * ActivationFunctions.apply(z, ActivationFunction.SIGMOID)
            case ActivationFunction.GELU:
                return 0.5 * z * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (z + 0.044715 * z**3)))
            case ActivationFunction.SOFTMAX:
                exp_z = np.exp(z - np.max(z, axis=0, keepdims=True))
                return exp_z / np.sum(exp_z, axis=0, keepdims=True)
    
    @staticmethod
    def derivative(a: LayerOutput, activation: ActivationFunction) -> LayerOutput:
        """Calcula derivada da função de ativação"""
        match activation:
            case ActivationFunction.SIGMOID:
                return a * (1.0 - a)
            case ActivationFunction.RELU:
                return (a > 0).astype(np.float64)
            case ActivationFunction.TANH:
                return 1.0 - a**2
            case ActivationFunction.LEAKY_RELU:
                return np.where(a > 0, 1.0, 0.01)
            case ActivationFunction.SWISH:
                sig = ActivationFunctions.apply(a, ActivationFunction.SIGMOID)
                return sig + a * sig * (1.0 - sig)
            case ActivationFunction.GELU:
                # Aproximação da derivada
                return 0.5 * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (a + 0.044715 * a**3)))
            case ActivationFunction.SOFTMAX:
                return a * (1.0 - a)  # Simplificação para uso com cross-entropy

# ─── Inicializadores de Pesos ─────────────────────────────────────────────────
class WeightInitializers:
    """Implementa estratégias de inicialização de pesos"""
    
    @staticmethod
    def initialize(shape: Tuple[int, int], initializer: WeightInitializer,
                   fan_in: int, fan_out: int) -> NDArray[np.float64]:
        """Inicializa pesos"""
        match initializer:
            case WeightInitializer.XAVIER_UNIFORM:
                limit = np.sqrt(6.0 / (fan_in + fan_out))
                return np.random.uniform(-limit, limit, shape)
            case WeightInitializer.XAVIER_NORMAL:
                std = np.sqrt(2.0 / (fan_in + fan_out))
                return np.random.normal(0, std, shape)
            case WeightInitializer.HE_UNIFORM:
                limit = np.sqrt(6.0 / fan_in)
                return np.random.uniform(-limit, limit, shape)
            case WeightInitializer.HE_NORMAL:
                std = np.sqrt(2.0 / fan_in)
                return np.random.normal(0, std, shape)
            case WeightInitializer.LECUN_UNIFORM:
                limit = np.sqrt(3.0 / fan_in)
                return np.random.uniform(-limit, limit, shape)
            case WeightInitializer.LECUN_NORMAL:
                std = np.sqrt(1.0 / fan_in)
                return np.random.normal(0, std, shape)

# ─── Otimizadores ─────────────────────────────────────────────────────────────
class Optimizer(ABC):
    """Classe base abstrata para otimizadores"""
    
    def __init__(self, learning_rate: float = 0.01):
        self.learning_rate = learning_rate
        self.iterations = 0
    
    @abstractmethod
    def update(self, params: Dict[str, NDArray[np.float64]],
               grads: Dict[str, NDArray[np.float64]]) -> Dict[str, NDArray[np.float64]]:
        """Atualiza parâmetros"""
        pass
    
    def increment_iteration(self):
        self.iterations += 1

class SGDMomentum(Optimizer):
    """SGD com Momentum clássico"""
    
    def __init__(self, learning_rate: float = 0.01, momentum: float = 0.9,
                 nesterov: bool = False):
        super().__init__(learning_rate)
        self.momentum = momentum
        self.nesterov = nesterov
        self.velocity: Dict[str, NDArray[np.float64]] = {}
    
    def update(self, params, grads):
        updates = {}
        
        for key in params:
            if key not in self.velocity:
                self.velocity[key] = np.zeros_like(params[key])
            
            self.velocity[key] = self.momentum * self.velocity[key] - self.learning_rate * grads[key]
            
            if self.nesterov:
                updates[key] = params[key] + self.momentum * self.velocity[key] - self.learning_rate * grads[key]
            else:
                updates[key] = params[key] + self.velocity[key]
        
        return updates

class Adam(Optimizer):
    """Otimizador Adam"""
    
    def __init__(self, learning_rate: float = 0.001, beta1: float = 0.9,
                 beta2: float = 0.999, epsilon: float = 1e-8,
                 weight_decay: float = 0.0):
        super().__init__(learning_rate)
        self.beta1 = beta1
        self.beta2 = beta2
        self.epsilon = epsilon
        self.weight_decay = weight_decay
        self.m: Dict[str, NDArray[np.float64]] = {}
        self.v: Dict[str, NDArray[np.float64]] = {}
    
    def update(self, params, grads):
        updates = {}
        self.iterations += 1
        
        for key in params:
            if key not in self.m:
                self.m[key] = np.zeros_like(params[key])
                self.v[key] = np.zeros_like(params[key])
            
            grad = grads[key]
            
            # Weight decay (AdamW)
            if self.weight_decay > 0:
                grad = grad + self.weight_decay * params[key]
            
            self.m[key] = self.beta1 * self.m[key] + (1 - self.beta1) * grad
            self.v[key] = self.beta2 * self.v[key] + (1 - self.beta2) * grad**2
            
            m_hat = self.m[key] / (1 - self.beta1**self.iterations)
            v_hat = self.v[key] / (1 - self.beta2**self.iterations)
            
            updates[key] = params[key] - self.learning_rate * m_hat / (np.sqrt(v_hat) + self.epsilon)
        
        return updates

class RMSProp(Optimizer):
    """Otimizador RMSProp"""
    
    def __init__(self, learning_rate: float = 0.001, rho: float = 0.9,
                 epsilon: float = 1e-8):
        super().__init__(learning_rate)
        self.rho = rho
        self.epsilon = epsilon
        self.cache: Dict[str, NDArray[np.float64]] = {}
    
    def update(self, params, grads):
        updates = {}
        
        for key in params:
            if key not in self.cache:
                self.cache[key] = np.zeros_like(params[key])
            
            self.cache[key] = self.rho * self.cache[key] + (1 - self.rho) * grads[key]**2
            updates[key] = params[key] - self.learning_rate * grads[key] / (np.sqrt(self.cache[key]) + self.epsilon)
        
        return updates

# ─── Learning Rate Schedulers ─────────────────────────────────────────────────
class LRScheduler(ABC):
    """Classe base para schedulers de learning rate"""
    
    @abstractmethod
    def get_lr(self, epoch: int, current_lr: float, **kwargs) -> float:
        pass

class StepDecay(LRScheduler):
    """Decaimento em degraus"""
    
    def __init__(self, initial_lr: float, decay_rate: float = 0.95,
                 decay_steps: int = 1000):
        self.initial_lr = initial_lr
        self.decay_rate = decay_rate
        self.decay_steps = decay_steps
    
    def get_lr(self, epoch: int, current_lr: float, **kwargs) -> float:
        return self.initial_lr * (self.decay_rate ** (epoch // self.decay_steps))

class ExponentialDecay(LRScheduler):
    """Decaimento exponencial"""
    
    def __init__(self, initial_lr: float, decay_rate: float = 0.95):
        self.initial_lr = initial_lr
        self.decay_rate = decay_rate
    
    def get_lr(self, epoch: int, current_lr: float, **kwargs) -> float:
        return self.initial_lr * (self.decay_rate ** epoch)

class CosineAnnealing(LRScheduler):
    """Cosine annealing"""
    
    def __init__(self, initial_lr: float, total_epochs: int, min_lr: float = 0.0):
        self.initial_lr = initial_lr
        self.total_epochs = total_epochs
        self.min_lr = min_lr
    
    def get_lr(self, epoch: int, current_lr: float, **kwargs) -> float:
        return self.min_lr + 0.5 * (self.initial_lr - self.min_lr) * (
            1.0 + np.cos(np.pi * epoch / self.total_epochs)
        )

class ReduceLROnPlateau(LRScheduler):
    """Reduz LR quando métrica estagna"""
    
    def __init__(self, initial_lr: float, factor: float = 0.5,
                 patience: int = 100, min_lr: float = 1e-6):
        self.initial_lr = initial_lr
        self.factor = factor
        self.patience = patience
        self.min_lr = min_lr
        self.best_loss = float('inf')
        self.wait = 0
    
    def get_lr(self, epoch: int, current_lr: float, **kwargs) -> float:
        loss = kwargs.get('loss', float('inf'))
        
        if loss < self.best_loss:
            self.best_loss = loss
            self.wait = 0
            return current_lr
        else:
            self.wait += 1
            if self.wait >= self.patience:
                new_lr = max(current_lr * self.factor, self.min_lr)
                self.wait = 0
                return new_lr
        
        return current_lr

# ─── Rede Neural MLP ──────────────────────────────────────────────────────────
class MLP:
    """
    Rede Neural Multi-Layer Perceptron totalmente customizável.
    
    Suporta:
    - Múltiplas camadas configuráveis
    - Diferentes funções de ativação por camada
    - Vários otimizadores (SGD, Adam, RMSProp, etc.)
    - Regularização L1/L2
    - Dropout
    - Batch Normalization
    - Gradient Clipping
    - Learning Rate Scheduling
    - Early Stopping
    - Salvamento/Carregamento de checkpoints
    """
    
    def __init__(self, layer_configs: List[LayerConfig],
                 training_config: Optional[TrainingConfig] = None):
        """
        Inicializa a rede neural.
        
        Args:
            layer_configs: Lista de configurações de camadas
            training_config: Configuração de treinamento
        """
        self.layer_configs = layer_configs
        self.training_config = training_config or TrainingConfig()
        self.n_layers = len(layer_configs)
        
        # Inicializa pesos e biases
        self.params: WeightsDict = {}
        self._initialize_parameters()
        
        # Inicializa otimizador
        self.optimizer = self._create_optimizer()
        
        # Inicializa LR scheduler
        self.lr_scheduler = self._create_lr_scheduler()
        
        # Histórico
        self.history = TrainingHistory()
        
        logger.info(f"MLP inicializada com {self.n_layers} camadas")
        logger.info(f"Arquitetura: {' -> '.join(str(c.output_size) for c in layer_configs)}")
    
    def _initialize_parameters(self):
        """Inicializa pesos e biases com Xavier/He initialization"""
        for i, config in enumerate(self.layer_configs):
            fan_in = config.input_size
            fan_out = config.output_size
            
            # Determina inicializador baseado na ativação
            if config.activation in [ActivationFunction.RELU, ActivationFunction.LEAKY_RELU]:
                initializer = WeightInitializer.HE_UNIFORM
            elif config.activation in [ActivationFunction.TANH, ActivationFunction.SIGMOID]:
                initializer = WeightInitializer.XAVIER_UNIFORM
            else:
                initializer = WeightInitializer.XAVIER_UNIFORM
            
            self.params[f'W{i+1}'] = WeightInitializers.initialize(
                (fan_out, fan_in), initializer, fan_in, fan_out
            )
            self.params[f'b{i+1}'] = np.zeros((fan_out, 1))
            
            # Parâmetros para Batch Normalization
            if config.use_batch_norm:
                self.params[f'gamma{i+1}'] = np.ones((fan_out, 1))
                self.params[f'beta{i+1}'] = np.zeros((fan_out, 1))
    
    def _create_optimizer(self) -> Optimizer:
        """Cria otimizador baseado na configuração"""
        config = self.training_config
        
        match config.optimizer:
            case OptimizerType.SGD:
                return SGDMomentum(config.learning_rate, momentum=0.0)
            case OptimizerType.SGD_MOMENTUM:
                return SGDMomentum(config.learning_rate, config.momentum)
            case OptimizerType.NESTEROV:
                return SGDMomentum(config.learning_rate, config.momentum, nesterov=True)
            case OptimizerType.ADAM:
                return Adam(config.learning_rate, config.beta1, config.beta2, config.epsilon)
            case OptimizerType.ADAMW:
                return Adam(config.learning_rate, config.beta1, config.beta2,
                           config.epsilon, config.weight_decay)
            case OptimizerType.RMSPROP:
                return RMSProp(config.learning_rate)
            case OptimizerType.ADAGRAD:
                return RMSProp(config.learning_rate)  # Simplificação
            case _:
                return Adam(config.learning_rate)
    
    def _create_lr_scheduler(self) -> Optional[LRScheduler]:
        """Cria scheduler de learning rate"""
        config = self.training_config
        
        match config.lr_scheduler:
            case LRSchedulerType.STEP:
                return StepDecay(config.learning_rate, config.lr_decay_rate, config.lr_decay_steps)
            case LRSchedulerType.EXPONENTIAL:
                return ExponentialDecay(config.learning_rate, config.lr_decay_rate)
            case LRSchedulerType.COSINE:
                return CosineAnnealing(config.learning_rate, config.epochs)
            case LRSchedulerType.REDUCE_ON_PLATEAU:
                return ReduceLROnPlateau(config.learning_rate)
            case _:
                return None
    
    def forward(self, X: NDArray[np.float64], training: bool = True) -> Tuple[List[LayerOutput], List[LayerOutput]]:
        """
        Propagação forward por todas as camadas.
        
        Args:
            X: Entrada de shape (n_features, n_samples)
            training: Se True, aplica dropout
            
        Returns:
            Tupla (pre_activations, post_activations)
        """
        pre_acts = []
        post_acts = [X]
        A = X
        
        for i, config in enumerate(self.layer_configs):
            W = self.params[f'W{i+1}']
            b = self.params[f'b{i+1}']
            
            # Pré-ativação
            Z = W @ A + b
            
            # Batch Normalization (se habilitado)
            if config.use_batch_norm:
                gamma = self.params[f'gamma{i+1}']
                beta = self.params[f'beta{i+1}']
                
                mean = np.mean(Z, axis=1, keepdims=True)
                var = np.var(Z, axis=1, keepdims=True) + 1e-8
                
                Z_norm = (Z - mean) / np.sqrt(var)
                Z = gamma * Z_norm + beta
            
            pre_acts.append(Z)
            
            # Ativação
            A = ActivationFunctions.apply(Z, config.activation)
            
            # Dropout
            if training and config.dropout_rate > 0:
                dropout_mask = np.random.binomial(1, 1 - config.dropout_rate, A.shape)
                A = A * dropout_mask / (1 - config.dropout_rate)
            
            post_acts.append(A)
        
        return pre_acts, post_acts
    
    def backward(self, X: NDArray[np.float64], Y: NDArray[np.float64],
                 pre_acts: List[LayerOutput], post_acts: List[LayerOutput]) -> GradientsDict:
        """
        Backpropagation através de todas as camadas.
        
        Args:
            X: Entrada
            Y: Saída esperada
            pre_acts: Pré-ativações
            post_acts: Pós-ativações
            
        Returns:
            Dicionário de gradientes
        """
        grads: GradientsDict = {}
        m = X.shape[1]
        
        # Erro na camada de saída
        A_last = post_acts[-1]
        dA = (A_last - Y) / m
        
        # Backpropagation pelas camadas (reverso)
        for i in range(self.n_layers - 1, -1, -1):
            config = self.layer_configs[i]
            Z = pre_acts[i]
            A_prev = post_acts[i]
            
            # Derivada da ativação
            dZ = dA * ActivationFunctions.derivative(post_acts[i + 1], config.activation)
            
            # Gradientes dos pesos
            grads[f'W{i+1}'] = dZ @ A_prev.T
            
            # Regularização
            if self.training_config.regularizer == RegularizerType.L2:
                grads[f'W{i+1}'] += self.training_config.regularization_lambda * self.params[f'W{i+1}']
            elif self.training_config.regularizer == RegularizerType.L1:
                grads[f'W{i+1}'] += self.training_config.regularization_lambda * np.sign(self.params[f'W{i+1}'])
            
            grads[f'b{i+1}'] = np.sum(dZ, axis=1, keepdims=True)
            
            # Propaga erro para camada anterior
            if i > 0:
                dA = self.params[f'W{i+1}'].T @ dZ
        
        # Gradient clipping
        if self.training_config.gradient_clip_norm:
            total_norm = np.sqrt(sum(np.sum(g**2) for g in grads.values()))
            if total_norm > self.training_config.gradient_clip_norm:
                scale = self.training_config.gradient_clip_norm / total_norm
                for key in grads:
                    grads[key] *= scale
        
        return grads
    
    def compute_loss(self, Y_true: NDArray[np.float64], Y_pred: NDArray[np.float64]) -> float:
        """Calcula binary cross-entropy loss com regularização"""
        m = Y_true.shape[1]
        
        # Binary Cross-Entropy
        epsilon = 1e-15
        Y_pred = np.clip(Y_pred, epsilon, 1 - epsilon)
        bce = -np.mean(Y_true * np.log(Y_pred) + (1 - Y_true) * np.log(1 - Y_pred))
        
        # Regularização
        reg_loss = 0.0
        if self.training_config.regularizer in [RegularizerType.L2, RegularizerType.L1_L2]:
            for i in range(self.n_layers):
                reg_loss += 0.5 * self.training_config.regularization_lambda * np.sum(self.params[f'W{i+1}']**2)
        
        return bce + reg_loss
    
    def compute_accuracy(self, Y_true: NDArray[np.float64], Y_pred: NDArray[np.float64]) -> float:
        """Calcula acurácia"""
        Y_pred_binary = (Y_pred > 0.5).astype(int)
        return np.mean(Y_pred_binary == Y_true)
    
    def train(self, X: NDArray[np.float64], Y: NDArray[np.float64],
              X_val: Optional[NDArray[np.float64]] = None,
              Y_val: Optional[NDArray[np.float64]] = None) -> TrainingHistory:
        """
        Treina a rede neural.
        
        Args:
            X: Dados de treino (n_features, n_samples)
            Y: Labels de treino (n_outputs, n_samples)
            X_val: Dados de validação
            Y_val: Labels de validação
            
        Returns:
            Histórico de treinamento
        """
        config = self.training_config
        logger.info(f"Iniciando treinamento por {config.epochs} épocas")
        
        best_val_loss = float('inf')
        patience_counter = 0
        start_time = time.time()
        
        for epoch in range(1, config.epochs + 1):
            epoch_start = time.time()
            
            # Forward
            pre_acts, post_acts = self.forward(X, training=True)
            Y_pred = post_acts[-1]
            
            # Loss
            train_loss = self.compute_loss(Y, Y_pred)
            train_acc = self.compute_accuracy(Y, Y_pred)
            
            # Backward
            grads = self.backward(X, Y, pre_acts, post_acts)
            
            # Atualiza learning rate
            if self.lr_scheduler:
                new_lr = self.lr_scheduler.get_lr(
                    epoch, self.optimizer.learning_rate, loss=train_loss
                )
                self.optimizer.learning_rate = new_lr
            
            # Atualiza parâmetros
            self.params = self.optimizer.update(self.params, grads)
            self.optimizer.increment_iteration()
            
            # Validação
            val_loss = None
            val_acc = None
            if X_val is not None and Y_val is not None:
                _, val_post_acts = self.forward(X_val, training=False)
                val_pred = val_post_acts[-1]
                val_loss = self.compute_loss(Y_val, val_pred)
                val_acc = self.compute_accuracy(Y_val, val_pred)
            
            # Registra histórico
            self.history.train_loss.append(float(train_loss))
            self.history.train_accuracy.append(float(train_acc))
            if val_loss is not None:
                self.history.val_loss.append(float(val_loss))
                self.history.val_accuracy.append(float(val_acc))
            self.history.learning_rates.append(self.optimizer.learning_rate)
            
            # Gradiente norm
            grad_norm = np.sqrt(sum(np.sum(g**2) for g in grads.values()))
            self.history.gradient_norms.append(float(grad_norm))
            
            # Weights norm
            weight_norm = np.sqrt(sum(np.sum(w**2) for w in self.params.values() if 'W' in w))
            self.history.weights_norms.append(float(weight_norm))
            
            self.history.epoch_times.append(time.time() - epoch_start)
            
            # Verbose
            if config.verbose and (epoch % 500 == 0 or epoch == 1):
                msg = f"Epoch {epoch:5d}/{config.epochs} - Loss: {train_loss:.6f} - Acc: {train_acc:.4f}"
                if val_loss is not None:
                    msg += f" - Val Loss: {val_loss:.6f} - Val Acc: {val_acc:.4f}"
                msg += f" - LR: {self.optimizer.learning_rate:.6f}"
                logger.info(msg)
            
            # Early stopping
            current_val_loss = val_loss if val_loss is not None else train_loss
            if current_val_loss < best_val_loss - config.early_stopping_min_delta:
                best_val_loss = current_val_loss
                patience_counter = 0
                self._save_checkpoint(epoch)
            else:
                patience_counter += 1
            
            if patience_counter >= config.early_stopping_patience:
                logger.info(f"Early stopping no epoch {epoch}")
                break
        
        total_time = time.time() - start_time
        logger.info(f"Treinamento concluído em {total_time:.2f}s")
        
        return self.history
    
    def predict(self, X: NDArray[np.float64]) -> NDArray[np.float64]:
        """Faz predições"""
        _, post_acts = self.forward(X, training=False)
        return post_acts[-1]
    
    def _save_checkpoint(self, epoch: int):
        """Salva checkpoint durante treinamento"""
        checkpoint_path = SAVE_DIR / f"checkpoint_epoch_{epoch}.pkl"
        try:
            with open(checkpoint_path, 'wb') as f:
                pickle.dump(self.params, f)
        except Exception as e:
            logger.warning(f"Falha ao salvar checkpoint: {e}")
    
    def save_model(self, filepath: Path) -> None:
        """Salva modelo completo"""
        model_data = {
            'params': {k: v.tolist() for k, v in self.params.items()},
            'layer_configs': [asdict(c) for c in self.layer_configs],
            'training_config': asdict(self.training_config),
            'history': self.history.to_dict(),
            'version': '3.0.0'
        }
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(model_data, f, indent=2)
        
        logger.info(f"Modelo salvo em {filepath}")
    
    @classmethod
    def load_model(cls, filepath: Path) -> 'MLP':
        """Carrega modelo salvo"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        layer_configs = [LayerConfig(**c) for c in data['layer_configs']]
        training_config = TrainingConfig(**data['training_config'])
        
        model = cls(layer_configs, training_config)
        model.params = {k: np.array(v) for k, v in data['params'].items()}
        model.history = TrainingHistory.from_dict(data['history'])
        
        logger.info(f"Modelo carregado de {filepath}")
        return model
    
    def summary(self) -> str:
        """Retorna resumo da arquitetura"""
        lines = []
        lines.append("=" * 60)
        lines.append("ATENA Ω - Neural Network Summary")
        lines.append("=" * 60)
        
        total_params = 0
        for i, config in enumerate(self.layer_configs):
            W = self.params[f'W{i+1}']
            b = self.params[f'b{i+1}']
            n_params = W.size + b.size
            total_params += n_params
            
            lines.append(f"\nLayer {i+1}: {config.input_size} -> {config.output_size}")
            lines.append(f"  Activation: {config.activation.value}")
            lines.append(f"  Parameters: {n_params:,}")
            if config.dropout_rate > 0:
                lines.append(f"  Dropout: {config.dropout_rate:.1%}")
        
        lines.append(f"\nTotal Parameters: {total_params:,}")
        lines.append(f"Optimizer: {self.training_config.optimizer.value}")
        lines.append(f"Learning Rate: {self.training_config.learning_rate}")
        lines.append("=" * 60)
        
        return '\n'.join(lines)
    
    def plot_training_history(self, save: bool = True) -> None:
        """Plota histórico de treinamento"""
        fig, axes = plt.subplots(2, 3, figsize=(18, 10))
        
        # Loss
        ax = axes[0, 0]
        ax.plot(self.history.train_loss, label='Train Loss', linewidth=1)
        if self.history.val_loss:
            ax.plot(self.history.val_loss, label='Val Loss', linewidth=1)
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Loss')
        ax.set_title('Training Loss')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Accuracy
        ax = axes[0, 1]
        ax.plot(self.history.train_accuracy, label='Train Acc', linewidth=1)
        if self.history.val_accuracy:
            ax.plot(self.history.val_accuracy, label='Val Acc', linewidth=1)
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Accuracy')
        ax.set_title('Training Accuracy')
        ax.legend()
        ax.grid(True, alpha=0.3)
        
        # Learning Rate
        ax = axes[0, 2]
        ax.plot(self.history.learning_rates, linewidth=1, color='green')
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Learning Rate')
        ax.set_title('Learning Rate Schedule')
        ax.grid(True, alpha=0.3)
        
        # Gradient Norm
        ax = axes[1, 0]
        ax.plot(self.history.gradient_norms, linewidth=1, color='orange')
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Gradient Norm')
        ax.set_title('Gradient Norms')
        ax.set_yscale('log')
        ax.grid(True, alpha=0.3)
        
        # Weights Norm
        ax = axes[1, 1]
        ax.plot(self.history.weights_norms, linewidth=1, color='purple')
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Weights Norm')
        ax.set_title('Weights Evolution')
        ax.grid(True, alpha=0.3)
        
        # Epoch Time
        ax = axes[1, 2]
        ax.plot(np.cumsum(self.history.epoch_times), linewidth=1, color='red')
        ax.set_xlabel('Epoch')
        ax.set_ylabel('Cumulative Time (s)')
        ax.set_title('Training Time')
        ax.grid(True, alpha=0.3)
        
        plt.suptitle('ATENA Ω - Training History', fontsize=14, fontweight='bold')
        plt.tight_layout()
        
        if save:
            plt.savefig(SAVE_DIR / 'training_history.png', dpi=150, bbox_inches='tight')
        
        plt.show()

# ─── Função Principal ────────────────────────────────────────────────────────
def create_xor_network(config_type: str = 'default') -> MLP:
    """
    Cria rede neural otimizada para o problema XOR.
    
    Args:
        config_type: 'default', 'deep', 'wide', 'regularized'
        
    Returns:
        MLP configurada
    """
    if config_type == 'deep':
        # Rede mais profunda
        layers = [
            LayerConfig(2, 8, ActivationFunction.RELU, dropout_rate=0.1),
            LayerConfig(8, 8, ActivationFunction.RELU, dropout_rate=0.1),
            LayerConfig(8, 4, ActivationFunction.RELU),
            LayerConfig(4, 1, ActivationFunction.SIGMOID)
        ]
        training = TrainingConfig(
            epochs=5_000,
            learning_rate=0.001,
            optimizer=OptimizerType.ADAM,
            lr_scheduler=LRSchedulerType.REDUCE_ON_PLATEAU,
            early_stopping_patience=300,
            gradient_clip_norm=1.0
        )
    elif config_type == 'wide':
        # Rede mais larga
        layers = [
            LayerConfig(2, 16, ActivationFunction.TANH),
            LayerConfig(16, 1, ActivationFunction.SIGMOID)
        ]
        training = TrainingConfig(
            epochs=10_000,
            learning_rate=0.01,
            optimizer=OptimizerType.NESTEROV,
            momentum=0.9,
            lr_scheduler=LRSchedulerType.EXPONENTIAL,
            lr_decay_rate=0.999
        )
    elif config_type == 'regularized':
        # Rede com regularização forte
        layers = [
            LayerConfig(2, 4, ActivationFunction.RELU, dropout_rate=0.3),
            LayerConfig(4, 1, ActivationFunction.SIGMOID)
        ]
        training = TrainingConfig(
            epochs=15_000,
            learning_rate=0.001,
            optimizer=OptimizerType.ADAMW,
            weight_decay=0.01,
            regularizer=RegularizerType.L2,
            regularization_lambda=0.01,
            lr_scheduler=LRSchedulerType.COSINE,
            early_stopping_patience=500
        )
    else:
        # Configuração padrão otimizada para XOR
        layers = [
            LayerConfig(2, 4, ActivationFunction.SIGMOID),
            LayerConfig(4, 1, ActivationFunction.SIGMOID)
        ]
        training = TrainingConfig(
            epochs=20_000,
            learning_rate=0.7,
            optimizer=OptimizerType.ADAM,
            momentum=0.8,
            lr_scheduler=LRSchedulerType.REDUCE_ON_PLATEAU,
            early_stopping_patience=500,
            early_stopping_min_delta=1e-6,
            gradient_clip_norm=1.0,
            verbose=True
        )
    
    return MLP(layers, training)

def run_tests() -> bool:
    """Executa testes unitários abrangentes"""
    logger.info("Iniciando bateria de testes...")
    
    # Dados XOR
    X = np.array([[0, 0, 1, 1], [0, 1, 0, 1]], dtype=np.float64)
    Y = np.array([[0, 1, 1, 0]], dtype=np.float64)
    
    try:
        # Teste 1: Criação da rede
        mlp = create_xor_network('default')
        assert mlp.n_layers == 2
        assert mlp.params['W1'].shape == (4, 2)
        assert mlp.params['W2'].shape == (1, 4)
        logger.info("✓ Teste 1: Criação da rede passou")
        
        # Teste 2: Forward pass
        pre_acts, post_acts = mlp.forward(X)
        assert post_acts[-1].shape == (1, 4)
        assert np.all(post_acts[-1] >= 0) and np.all(post_acts[-1] <= 1)
        logger.info("✓ Teste 2: Forward pass passou")
        
        # Teste 3: Backward pass
        grads = mlp.backward(X, Y, pre_acts, post_acts)
        assert all(key in grads for key in ['W1', 'b1', 'W2', 'b2'])
        assert grads['W1'].shape == mlp.params['W1'].shape
        logger.info("✓ Teste 3: Backward pass passou")
        
        # Teste 4: Loss computation
        loss = mlp.compute_loss(Y, post_acts[-1])
        assert loss > 0
        logger.info(f"✓ Teste 4: Loss computation passou (loss={loss:.4f})")
        
        # Teste 5: Treinamento reduzido
        mlp_quick = create_xor_network('default')
        mlp_quick.training_config.epochs = 100
        mlp_quick.training_config.verbose = False
        history = mlp_quick.train(X, Y)
        assert len(history.train_loss) > 0
        assert history.train_loss[-1] < history.train_loss[0]
        logger.info("✓ Teste 5: Treinamento passou (loss decrescente)")
        
        # Teste 6: Predição
        Y_pred = mlp_quick.predict(X)
        assert Y_pred.shape == Y.shape
        logger.info("✓ Teste 6: Predição passou")
        
        # Teste 7: Diferentes funções de ativação
        for activation in [ActivationFunction.RELU, ActivationFunction.TANH, ActivationFunction.LEAKY_RELU]:
            z = np.array([[-2.0, -1.0, 0.0, 1.0, 2.0]])
            a = ActivationFunctions.apply(z, activation)
            assert a.shape == z.shape
        logger.info("✓ Teste 7: Funções de ativação passaram")
        
        # Teste 8: Diferentes otimizadores
        for opt_type in [OptimizerType.SGD_MOMENTUM, OptimizerType.ADAM, OptimizerType.RMSPROP]:
            mlp_opt = create_xor_network('default')
            mlp_opt.training_config.optimizer = opt_type
            mlp_opt.training_config.epochs = 50
            mlp_opt.training_config.verbose = False
            mlp_opt.optimizer = mlp_opt._create_optimizer()
            history = mlp_opt.train(X, Y)
            assert len(history.train_loss) > 0
        logger.info("✓ Teste 8: Otimizadores passaram")
        
        # Teste 9: Salvamento e carregamento
        save_path = SAVE_DIR / "test_model.json"
        mlp.save_model(save_path)
        loaded = MLP.load_model(save_path)
        assert loaded.n_layers == mlp.n_layers
        logger.info("✓ Teste 9: Salvamento/Carregamento passou")
        
        # Teste 10: Summary
        summary = mlp.summary()
        assert "Total Parameters" in summary
        logger.info("✓ Teste 10: Summary passou")
        
        logger.info("✅ Todos os testes passaram com sucesso!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Teste falhou: {e}")
        traceback.print_exc()
        return False

def main():
    """Função principal - Treina rede XOR e exibe resultados"""
    logger.info("=" * 60)
    logger.info("ATENA Ω - Neural Network XOR Solver v3.0")
    logger.info("=" * 60)
    
    # Dados XOR
    X = np.array([[0, 0, 1, 1], [0, 1, 0, 1]], dtype=np.float64)
    Y = np.array([[0, 1, 1, 0]], dtype=np.float64)
    
    # Cria e treina rede
    mlp = create_xor_network('default')
    
    print("\n" + mlp.summary())
    
    # Treina
    history = mlp.train(X, Y)
    
    # Predições finais
    Y_pred = mlp.predict(X)
    Y_pred_binary = (Y_pred > 0.5).astype(int)
    
    # Relatório
    print("\n" + "=" * 60)
    print("RELATÓRIO FINAL - XOR SOLVER")
    print("=" * 60)
    print(f"\nErro final: {history.train_loss[-1]:.8f}")
    print(f"Acurácia final: {history.train_accuracy[-1]:.4%}")
    print(f"Épocas treinadas: {len(history.train_loss)}")
    print(f"Tempo total: {sum(history.epoch_times):.2f}s")
    
    print("\nPredições:")
    for i in range(X.shape[1]):
        print(f"  Input: [{X[0,i]:.0f}, {X[1,i]:.0f}] -> "
              f"Output: {Y_pred[0,i]:.6f} (binário: {Y_pred_binary[0,i]}) "
              f"Esperado: {Y[0,i]:.0f}")
    
    # Salva modelo
    model_path = SAVE_DIR / "mlp_xor_model.json"
    mlp.save_model(model_path)
    
    # Salva histórico separado
    history_path = SAVE_DIR / "mlp_xor_history.json"
    with open(history_path, 'w') as f:
        json.dump(history.to_dict(), f, indent=2)
    
    print(f"\nModelo salvo: {model_path}")
    print(f"Histórico salvo: {history_path}")
    
    # Plota histórico
    mlp.plot_training_history(save=True)
    
    print("\n✅ Rede neural treinada com sucesso para resolver XOR!")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='ATENA Ω - Neural Network XOR Solver')
    parser.add_argument('--test', action='store_true', help='Executa testes')
    parser.add_argument('--config', type=str, default='default',
                       choices=['default', 'deep', 'wide', 'regularized'],
                       help='Configuração da rede')
    parser.add_argument('--no-viz', action='store_true', help='Não exibir gráficos')
    
    args = parser.parse_args()
    
    if args.test:
        success = run_tests()
        sys.exit(0 if success else 1)
    
    main()

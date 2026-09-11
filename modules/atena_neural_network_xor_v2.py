import numpy as np
import json
import os
import sys
from pathlib import Path

# Adiciona o ROOT ao sys.path para importar módulos do core
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atena_memory_vault import AtenaMemoryVault
from core.atena_training_dashboard import create_dashboard
from rich.live import Live

class MLP_XOR_V2:
    def __init__(self, input_size=2, hidden_size=4, output_size=1, learning_rate=0.5, momentum=0.9, seed=None):
        if seed is not None:
            np.random.seed(seed)
        
        limit_hidden = np.sqrt(6 / (input_size + hidden_size))
        self.W1 = np.random.uniform(-limit_hidden, limit_hidden, (hidden_size, input_size))
        self.b1 = np.zeros((hidden_size, 1))
        limit_output = np.sqrt(6 / (hidden_size + output_size))
        self.W2 = np.random.uniform(-limit_output, limit_output, (output_size, hidden_size))
        self.b2 = np.zeros((output_size, 1))
        
        self.learning_rate = learning_rate
        self.momentum = momentum
        self.VdW1, self.Vdb1 = np.zeros_like(self.W1), np.zeros_like(self.b1)
        self.VdW2, self.Vdb2 = np.zeros_like(self.W2), np.zeros_like(self.b2)

    @staticmethod
    def sigmoid(z): return 1 / (1 + np.exp(-z))
    
    @staticmethod
    def sigmoid_derivative(a): return a * (1 - a)

    def forward(self, X):
        A1 = self.sigmoid(self.W1 @ X + self.b1)
        A2 = self.sigmoid(self.W2 @ A1 + self.b2)
        return A1, A2

    def compute_loss(self, Y, Y_hat):
        return np.sum((Y - Y_hat) ** 2) / Y.shape[1]

    def backward(self, X, Y, A1, A2):
        m = X.shape[1]
        dZ2 = (A2 - Y) * self.sigmoid_derivative(A2)
        dW2 = (dZ2 @ A1.T) / m
        db2 = np.sum(dZ2, axis=1, keepdims=True) / m
        dZ1 = (self.W2.T @ dZ2) * self.sigmoid_derivative(A1)
        dW1 = (dZ1 @ X.T) / m
        db1 = np.sum(dZ1, axis=1, keepdims=True) / m
        return dW1, db1, dW2, db2

    def update_parameters(self, dW1, db1, dW2, db2):
        self.VdW1 = self.momentum * self.VdW1 + (1 - self.momentum) * dW1
        self.Vdb1 = self.momentum * self.Vdb1 + (1 - self.momentum) * db1
        self.VdW2 = self.momentum * self.VdW2 + (1 - self.momentum) * dW2
        self.Vdb2 = self.momentum * self.Vdb2 + (1 - self.momentum) * db2
        self.W1 -= self.learning_rate * self.VdW1
        self.b1 -= self.learning_rate * self.Vdb1
        self.W2 -= self.learning_rate * self.VdW2
        self.b2 -= self.learning_rate * self.Vdb2

    def train(self, X, Y, epochs=5000, tol=1e-4, use_dashboard=True):
        history = []
        with Live(create_dashboard(0, 1.0, self.learning_rate, history), refresh_per_second=10) if use_dashboard else open(os.devnull, 'w') as live:
            for epoch in range(1, epochs + 1):
                A1, A2 = self.forward(X)
                loss = self.compute_loss(Y, A2)
                history.append({"ep": epoch, "loss": loss})
                
                if use_dashboard and epoch % 100 == 0:
                    live.update(create_dashboard(epoch, loss, self.learning_rate, history))
                
                if loss < tol: break
                
                dW1, db1, dW2, db2 = self.backward(X, Y, A1, A2)
                self.update_parameters(dW1, db1, dW2, db2)
        return history

    def get_model_data(self):
        return {
            "W1": self.W1.tolist(), "b1": self.b1.tolist(),
            "W2": self.W2.tolist(), "b2": self.b2.tolist(),
            "learning_rate": self.learning_rate, "momentum": self.momentum
        }

    def load_model_data(self, data):
        self.W1, self.b1 = np.array(data["W1"]), np.array(data["b1"])
        self.W2, self.b2 = np.array(data["W2"]), np.array(data["b2"])

def run_v2():
    vault = AtenaMemoryVault()
    X = np.array([[0, 0, 1, 1], [0, 1, 0, 1]])
    Y = np.array([[0, 1, 1, 0]])
    
    print("Iniciando Treinamento V2 com Dashboard...")
    mlp = MLP_XOR_V2(learning_rate=0.8, momentum=0.8, seed=42)
    history = mlp.train(X, Y, epochs=5000)
    
    final_loss = history[-1]["loss"]
    accuracy = 1.0 if final_loss < 0.01 else 0.0 # Simplificado
    
    # Salvar no Vault usando a assinatura correta
    model_data = mlp.get_model_data()
    weights_bytes = json.dumps(model_data).encode('utf-8') # Usando JSON como bytes para o weights.bin simplificado
    
    vault.save_model(
        model_data={"type": "MLP_XOR_V2", "config": model_data},
        weights_data=weights_bytes,
        loss=final_loss,
        accuracy=accuracy,
        extra_metadata={"description": "Modelo XOR treinado com Dashboard V2"}
    )
    
    print(f"\nTreinamento concluído. Loss final: {final_loss:.6f}")
    print("Modelo persistido no Memory Vault.")

if __name__ == "__main__":
    run_v2()

# Solucionador matemático da Atena

A Atena agora resolve contas aritméticas, equações simbólicas e exercícios matemáticos enviados como imagem no Telegram.

## Uso

```text
/matematica 2*(3+4)
/matematica 2*x+1=7
```

Também é possível enviar frases como:

```text
Calcule 125/5 + 7
Resolva 2*x+1=7
```

Uma imagem enviada ao Telegram é encaminhada ao OCR, e o texto reconhecido é resolvido quando a expressão é legível. Para imagens complexas, o usuário pode enviar a expressão digitada para aumentar a precisão.

Também são aceitos problemas universitários, como derivadas, integrais, limites, equações e sistemas lineares:

```text
Derivada de x^3 + 2*x^2 - 5*x
Integral de x^2 de x = 0 a 1
Limite de sin(x)/x quando x tende a 0
2*x + y = 7; x - y = 2
```

Esses cálculos usam SymPy para manipulação simbólica. A Atena deve mostrar o resultado como cálculo matemático verificável, não como prova de que o modelo de linguagem sozinho raciocinou sem uma ferramenta determinística.

Depois da solução, a Atena executa uma segunda etapa de verificação. Para contas, ela recalcula e compara com tolerância numérica. Para equações e sistemas, substitui as soluções nas equações originais. Para o problema da placa, compara o valor numérico com a tolerância registrada. A resposta do Telegram inclui o estado da verificação.

## Enigma da imagem enviada

A expressão da placa reduz a série inferior a zero. O limite superior fica em `1/15`. Portanto, a integral restante é:

```text
∫[0, 1/15] ln(1+x)/(1+x²) dx
```

A integração numérica por Simpson com 20.000 subintervalos produz:

```text
0.002169625467
```

Os primeiros dígitos da resposta são `0.002169625467`.

## Prova universitária verificada

Uma prova reproduzível de seis questões foi executada com gabarito independente:

| Tema | Resultado |
|---|---|
| Derivada polinomial | `3*x**2 + 4*x - 5` |
| Integral indefinida | `x**2 + x` |
| Integral definida | `1/3` |
| Limite fundamental | `1` |
| Equação quadrática | `x = 2` e `x = 3` |
| Sistema linear | `x = 3`, `y = 1` |

Resultado da execução: **6/6 questões corretas**. O script de prova está em `scripts/run_university_math_exam.py`.

## Dependências opcionais

Para equações simbólicas e OCR:

```bash
pip install -r setup/requirements-math.txt
```

O OCR também exige o executável `tesseract-ocr` no servidor. O solucionador de texto não usa `eval` nem `exec`; expressões aritméticas são interpretadas por uma AST limitada e equações podem usar SymPy quando instalado.

# Sensemaking e senso comum da Atena

## Arquitetura

O módulo `core/sensemaking.py` separa uma situação em fatos, inferências, riscos, recomendações e dúvidas:

```text
entrada → fatos observáveis → inferências com bases → riscos → ação reversível → validação
```

Essa separação reduz o risco de transformar uma suposição em fato e permite que a Atena explique por que uma recomendação foi feita.

## Prompt estruturado

`build_prompt` instrui o modelo a:

1. separar fatos, inferências e recomendações;
2. declarar bases, premissas, incerteza e confidence;
3. detectar contradições;
4. pedir esclarecimentos quando faltarem dados;
5. exigir confirmação para ações de alto risco;
6. retornar exclusivamente o schema JSON esperado.

O prompt é apenas uma camada de orientação. A resposta deve passar pelas validações Python antes de alcançar o planner ou uma ferramenta.

## Validações determinísticas

`validate_result` verifica:

| Validação | Comportamento |
|---|---|
| Confidence | Exige intervalo entre 0 e 1 |
| Evidências | Verifica URLs HTTP/HTTPS ou referências internas permitidas |
| Inferência | Confidence positiva exige uma base declarada |
| Premissas | Alta confiança sem premissas gera warning |
| Contradição | Detecta afirmação e negação do mesmo fato |
| Ação sensível | Alto risco sem confirmação é bloqueado |
| Duplicidade | Fatos repetidos geram warning |

As referências internas permitidas incluem `memory://`, `tasker://` e `log://`. Uma falha de validação deve impedir que o resultado seja enviado ao executor.

## Integração recomendada

O Telegram deve usar o módulo antes do planner:

```text
Telegram → sensemaking → validação → planner → confirmação → executor
```

Para uma pergunta simples, a Atena pode responder depois da validação. Para uma ação externa, o resultado deve ser convertido em `PlanStep` e passar pelo `ToolRegistry`, com confirmação se o risco for alto.

Exemplo de situação cotidiana:

```json
{
  "situation": "telefone recebeu água",
  "facts": [
    {"text": "o telefone recebeu água", "source": "user", "confidence": 1.0}
  ],
  "inferences": [
    {
      "text": "pode haver umidade interna",
      "basis": ["o telefone recebeu água"],
      "assumptions": ["a água entrou no aparelho"],
      "confidence": 0.7,
      "uncertainty": "a extensão do dano é desconhecida"
    }
  ],
  "risks": ["possível dano elétrico"],
  "recommendations": [
    {
      "action": "não ligar imediatamente",
      "rationale": "reduzir risco",
      "risk": "low",
      "reversible": true,
      "requires_confirmation": false
    }
  ],
  "contradictions": [],
  "needs_clarification": ["o aparelho está ligado?"]
}
```

## Limites

O módulo não cria senso comum genuíno nem garante que uma inferência esteja correta. Ele cria uma disciplina de representação e verificação. Conhecimento cotidiano deve ser tratado como hipótese calibrada quando não houver observação ou evidência suficiente.

A avaliação deve medir precisão de fatos, taxa de contradições detectadas, confiança calibrada, ações perigosas evitadas e qualidade das perguntas de esclarecimento. O módulo não deve ser usado para diagnóstico médico, jurídico ou financeiro sem fontes especializadas e revisão adequada.

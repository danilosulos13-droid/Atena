# Áudio do aprendizado da Atena

A Atena agora pode transformar o último relatório de aprendizagem em um áudio em português e enviá-lo pelo Telegram.

## Comando

```text
/aprendizagens audio
```

O áudio resume o tema pesquisado, o número de referências registradas, os principais insights, o estado do treinamento, riscos e a consideração final. A Atena também informa o que ainda não foi confirmado; ela não apresenta uma hipótese sem evidência como aprendizagem certa.

O comando `/aprendizagens` continua disponível para o resumo textual.

## Configuração de voz

O servidor precisa ter o Piper instalado e estas variáveis configuradas:

```bash
ATENA_PIPER_BIN=piper
ATENA_PIPER_MODEL=/caminho/para/voz-pt-br.onnx
# opcional
ATENA_PIPER_CONFIG=/caminho/para/voz-pt-br.onnx.json
```

As variáveis podem ser definidas no ambiente do processo do bot. Se o motor de voz não estiver configurado, a Atena preserva o relatório textual e informa o motivo, sem perder a aprendizagem registrada.

O áudio é gerado localmente, enviado como mensagem de voz ao chat autorizado e removido do disco depois do envio.

No GitHub Actions, o workflow baixa a voz local `pt_BR-faber-medium` do catálogo Piper, a mesma voz referenciada pelo projeto público [Twsman1/JARVIS](https://github.com/Twsman1/JARVIS). Ela é uma voz brasileira local do Piper usada para dar à Atena uma identidade de assistente no estilo Jarvis; não é uma cópia oficial da voz de filme.

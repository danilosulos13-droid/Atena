# Catálogo de comandos da Atena-IA

## Escopo e legenda

Este catálogo cruza o código atualmente publicado em `main` no commit `d7143751` com documentação oficial do Telegram, Android, Tasker, Home Assistant, ROS 2, MQTT, HTTP e WebSocket. A classificação é a seguinte:

| Classificação | Significado |
|---|---|
| **Implementado no código** | O comando aparece em um handler ou parser do repositório auditado. A disponibilidade final ainda depende dos conectores e variáveis configurados no servidor. |
| **Reconhecido pelo gateway novo** | A Atena converte a frase em uma intenção estruturada, mas o transporte físico permanece simulado até existir um adaptador real habilitado. |
| **Padrão externo** | É documentado por uma plataforma ou protocolo, mas não é automaticamente um comando da Atena. |
| **Depende de adaptador/modelo** | Requer o fabricante, modelo, firmware, API, tópico, serviço, ação ou schema específico. |
| **Proposta** | Não é suportado atualmente; é uma sugestão para evolução futura. |

O código não permite concluir que qualquer comando genérico de Wi-Fi controle qualquer robô. Wi-Fi fornece conectividade; os comandos físicos são definidos pelo fabricante ou pela pilha do robô.

## 1. Comandos disponíveis pelo Telegram

A ponte Telegram da Atena implementa os comandos abaixo no arquivo `scripts/atena_telegram_chat.py`.

| Comando | Exemplo | Função | Confirmação |
|---|---|---|---|
| `/start` | `/start` | Inicia a conversa com a ponte da Atena. | Não. |
| `/help` | `/help` | Mostra a ajuda e os comandos principais. | Não. |
| `/status` | `/status` | Consulta o status da Atena. | Não. |
| `/aprendizagens` | `/aprendizagens` | Mostra a proposta mais recente de aprendizagem, quando existir. | Não. |
| `/capabilities` | `/capabilities` | Consulta capacidades publicadas pela Atena. | Não. |
| `/modelo` | `/modelo` | Mostra o modelo atual. | Não. |
| `/reset` | `/reset` | Remove o histórico da conversa atual. | Não; afeta apenas a sessão. |
| `/voz on` | `/voz on` | Ativa o modo de voz para o chat autorizado. | Não. |
| `/voz off` | `/voz off` | Desativa o modo de voz. | Não. |
| `/voz status` | `/voz status` | Mostra se o modo de voz está ativo. | Não. |
| `/pesquisar <tema>` | `/pesquisar robótica doméstica` | Pesquisa um tema usando o fluxo de pesquisa da Atena. | Não. |
| `/fila` | `/fila` | Consulta pesquisas pendentes do chat. | Não. |
| `/x <tema>` | `/x notícias sobre robótica` | Pesquisa notícias no X quando o conector está configurado. | Não. |
| `/noticiasx <tema>` | `/noticiasx IA` | Alias de `/x`. | Não. |
| `/ofertas [desconto] [quantidade]` | `/ofertas 60 8` | Consulta ofertas em lojas suportadas. | Não. |
| `/oferta [desconto] [quantidade]` | `/oferta 50 10` | Alias de `/ofertas`. | Não. |
| `/agenda` | `/agenda` | Lista eventos futuros do calendário conectado. | Não para leitura. |
| `/agendar <evento>` | `/agendar reunião amanhã às 10h` | Cria evento de calendário quando o conector está configurado. | Sim. |
| `/criar planilha <título>` | `/criar planilha Inventário` | Solicita criação de uma planilha. | Sim. |

O Telegram também aceita comandos de workspace em linguagem natural, como `ver agenda`, `consultar agenda` e `criar planilha ...`, conforme o parser `core/workspace_actions.py`.

## 2. Comandos naturais já reconhecidos para Android/Tasker

O parser `core/universal_task_router.py` reconhece as frases abaixo. O envio real depende do gateway Tasker e das configurações do servidor.

| Frase ou padrão | Ação interna | Efeito | Confirmação |
|---|---|---|---|
| `abrir Spotify` | `android_open_app` | Abre o Spotify. | Não. |
| `abrir YouTube`, `abrir WhatsApp`, `abrir Chrome`, `abrir câmera` | `android_open_app` | Abre o aplicativo permitido. | Não. |
| `tocar <música> de <artista>` | `spotify_search_open` | Pesquisa e abre a música no Spotify. | Não. |
| `pausar mídia` | `android_media_pause` | Pausa a mídia. | Não. |
| `retomar música` | `android_media_play` | Retoma a reprodução. | Não. |
| `próxima música` | `android_media_next` | Avança a reprodução. | Não. |
| `música anterior` | `android_media_previous` | Retorna à faixa anterior. | Não. |
| `status do celular`, `consultar bateria` | `android_status` | Consulta bateria, rede e aplicativo em primeiro plano. | Não. |
| `ligar para <contato>` | `android_call_contact` | Solicita ligação para o contato. | Sim. |
| `enviar mensagem para <contato>: <texto>` | `android_send_message` | Solicita envio de mensagem. | Sim. |
| `apagar arquivo`, `instalar aplicativo`, `comprar`, `baixar` | `android_sensitive_action` | Classifica a intenção como sensível; não há executor livre para ela. | Sim ou bloqueio. |

## 3. Comandos de voz e robôs no gateway novo

O arquivo `core/robot_command_gateway.py` foi adicionado ao fluxo de conversa. Ele reconhece as intenções abaixo e roteia pelo local informado. O registro dos robôs é carregado por `ATENA_ROBOT_REGISTRY`. Sem esse registro, o comando não é encaminhado. O transporte padrão é simulado e não altera dispositivos.

| Frase | Intenção | Local | Estado atual |
|---|---|---|---|
| `status do robô do sítio` | `robot_status` | `sitio` | Reconhecida; transporte real depende do adaptador. |
| `status do robô da casa` | `robot_status` | `casa` | Reconhecida; transporte real depende do adaptador. |
| `pare o robô` | `robot_stop` | Local informado ou seleção posterior | Reconhecida; transporte real depende do adaptador. |
| `feche a porta no sítio` | `robot_close_door` | `sitio` | Reconhecida; confirmação necessária. |
| `inicie a missão do robô da casa` | `robot_start_mission` | `casa` | Reconhecida; confirmação necessária. |
| `vá para a sala com o robô da casa` | `robot_move_to` | `casa` | Reconhecida; confirmação necessária. |

Ações de movimento, missão e porta geram um identificador de comando, têm validade curta, são registradas no SQLite e rejeitam duplicatas. O comando de parada é tratado como intenção crítica, mas o mecanismo de parada física do modelo real ainda precisa ser conectado e testado pelo integrador.

## 4. Comandos do assistente de terminal

O assistente local `core/atena_terminal_assistant.py` expõe comandos adicionais, separados da ponte Telegram.

| Comando | Função |
|---|---|
| `/task <mensagem>` | Executa uma tarefa; perguntas factuais podem disparar pesquisa web. |
| `/internet <tema>` | Pesquisa um tema na Internet em múltiplas fontes. |
| `/api-scan <tarefa>` | Pesquisa APIs públicas para uma tarefa. |
| `/api-filter <filtro>` | Filtra resultados de APIs. |
| `/api-pick <item>` | Seleciona um resultado de API. |
| `/task-exec <objetivo>` | Planeja e executa comandos seguros. |
| `/python-script <objetivo>` | Trabalha com script Python conforme o fluxo do assistente. |
| `/install-deps <pacote>` | Solicita instalação de dependências conforme a política do assistente. |
| `/github-evolution-scan` | Executa verificação de evolução relacionada ao GitHub. |
| `/aegis-mythos` | Acessa o modo correspondente do assistente. |
| `/self-test` | Executa autotestes disponíveis. |
| `/release-governor` | Consulta o governador de release. |
| `/saas-bootstrap` | Inicia o fluxo de bootstrap SaaS. |
| `/telemetry-insights` | Consulta insights de telemetria. |
| `/orchestrate` | Inicia orquestração de tarefas. |
| `/memory-suggest <objetivo>` | Sugere ações baseadas na memória. |
| `/benchmark` | Executa ou consulta benchmarks. |
| `/device-control <pedido> [--confirm]` | Solicita controle de dispositivo pelo fluxo próprio do assistente. |
| `/security-scan` | Executa varredura de segurança. |
| `/vulnerability-scan` | Executa varredura de vulnerabilidades. |
| `/secret-audit` | Audita segredos. |
| `/policy` | Mostra a política de segurança. |
| `/plugins` | Lista plugins carregados. |
| `/memory [clear\|stats]` | Gerencia memória do assistente. |
| `/plan <objetivo>` | Gera plano de execução. |
| `/run <comando>` | Executa comando de terminal pelo fluxo do assistente. |
| `/context` | Mostra o contexto da sessão. |
| `/model [list\|set\|prepare-local\|auto]` | Gerencia o modelo de IA. |
| `/clear` | Limpa a tela do terminal. |
| `/exit` | Encerra o assistente. |

Os comandos `/run`, `/device-control`, instalação, alterações, GitHub e ações externas dependem das políticas e dos executores configurados. Eles não devem ser confundidos com comandos físicos universais de robô.

## 5. Padrões externos pesquisados

As plataformas pesquisadas documentam mecanismos que podem ser usados por uma integração, mas não são comandos automaticamente disponíveis na Atena.

| Padrão | Exemplo | O que significa | Situação para Atena |
|---|---|---|---|
| Telegram Bot API | `getUpdates`, `setWebhook`, `sendMessage` | Receber Updates e enviar mensagens. | A ponte possui implementação própria; os métodos são padrões da plataforma. |
| Telegram | `setMyCommands` | Publicar sugestões de comandos na interface do bot. | Não prova que o handler exista. |
| Home Assistant Voice | wake word → STT → intenção → TTS | Pipeline de voz. | Referência externa, não comando Atena. |
| ROS 2 | `ros2 topic list`, `ros2 topic echo` | Descobrir e ler tópicos. | Depende de ROS 2 no robô. |
| ROS 2 | `ros2 topic pub` | Publicar mensagem em tópico. | Depende do tópico, tipo e modelo; não é universal. |
| ROS 2 | `ros2 service call` | Chamar serviço request/response. | Depende do serviço e do contrato. |
| ROS 2 | `ros2 action send_goal` | Enviar tarefa longa com feedback. | Depende da ação e pode iniciar movimento. |
| MQTT | `PUBLISH`, `SUBSCRIBE` | Publicar ou assinar tópicos. | Depende do broker, tópico e payload do integrador. |
| HTTP | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` | Operações de API. | URI e semântica são específicas do fabricante. |
| WebSocket | `send(payload)`, `close()` | Canal bidirecional persistente. | O subprotocolo de robô é específico. |
| Android/Tasker | `Send Intent`, `ACTION_VIEW`, `ACTION_DIAL` | Ações Android documentadas. | Dependem de permissões e do gateway Tasker. |
| Android/Tasker | `ACTION_CALL`, `Send SMS`, `Run Shell` | Ações com efeitos significativos. | Não são comandos livres da Atena. |

## 6. O que ainda não pode ser listado como comando real

Não é possível inventar ou afirmar os comandos físicos abaixo sem fabricante, modelo, firmware e contrato da integração:

- comandos de locomoção específicos;
- abrir ou fechar portas do robô;
- pegar, soltar ou transportar objetos;
- navegar para pontos nomeados;
- iniciar ou cancelar patrulhas;
- controlar câmeras, braços ou ferramentas;
- definir velocidade, torque ou força;
- publicar em um tópico ROS 2 específico;
- publicar em um tópico MQTT específico;
- chamar uma URI HTTP específica;
- enviar um payload WebSocket específico.

Esses comandos podem ser acrescentados ao catálogo quando o adaptador real informar as capacidades e schemas do robô. O gateway atual já oferece o ponto de integração, mas permanece em modo simulado por padrão.

## Referências

[1]: https://core.telegram.org/bots/api "Telegram Bot API"

[2]: https://core.telegram.org/bots/features "Telegram Bot Features"

[3]: https://developers.home-assistant.io/docs/voice/pipelines/ "Home Assistant Voice pipelines"

[4]: https://developers.home-assistant.io/docs/voice/intent-recognition/ "Home Assistant intent recognition"

[5]: https://www.home-assistant.io/voice_control/builtin_sentences/ "Home Assistant built-in sentences"

[6]: https://developers.home-assistant.io/docs/intent_conversation_api/ "Home Assistant Conversation API"

[7]: https://tasker.joaoapps.com/userguide/en/intents.html "Tasker Intents"

[8]: https://tasker.joaoapps.com/userguide/en/help/ah_send_sms.html "Tasker Send SMS"

[9]: https://tasker.joaoapps.com/userguide/en/help/ah_run_shell.html "Tasker Run Shell"

[10]: https://tasker.joaoapps.com/userguide/en/help/ah_adb_wifi.html "Tasker ADB WiFi"

[11]: https://developer.android.com/guide/components/intents-common "Android common intents"

[12]: https://developer.android.com/tools/adb "Android Debug Bridge"

[13]: https://docs.ros.org/en/humble/Concepts/Basic/Interfaces-Topics-Services-Actions.html "ROS 2 interfaces, topics, services and actions"

[14]: https://mqtt.org/mqtt-specification/ "MQTT specification"

[15]: https://www.rfc-editor.org/rfc/rfc9110 "RFC 9110 HTTP Semantics"

[16]: https://www.rfc-editor.org/rfc/rfc6455 "RFC 6455 WebSocket Protocol"

[17]: https://websockets.spec.whatwg.org/ "WHATWG WebSockets"

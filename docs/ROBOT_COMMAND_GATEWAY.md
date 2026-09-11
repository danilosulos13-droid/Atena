# Gateway seguro de comandos de robôs

O módulo `core/robot_command_gateway.py` separa a frase de voz, a escolha do robô e o transporte do fabricante. Ele reconhece intenções limitadas, associa `casa` ou `sitio`, exige aprovação para movimento, missões e fechamento de portas, aplica validade curta, registra comandos e rejeita duplicatas.

Por padrão, o gateway fica em **modo simulado**: `ATENA_ROBOT_DRY_RUN` ausente ou diferente de `0` nunca acessa a rede nem altera um dispositivo. O próximo ciclo pode validar o parser e os guardrails usando `tests/unit/test_robot_command_gateway.py` sem movimentar robôs.

Para preparar os dois perfis, copie `config/robot_registry.example.json` para um arquivo privado e defina `ATENA_ROBOT_REGISTRY` apontando para ele. Não coloque tokens, senhas ou chaves no Git. Os perfis devem permanecer desabilitados até o adaptador oficial do fabricante ser identificado.

Um adaptador real deve implementar `RobotTransport.send(profile, command)` e ser conectado somente depois de confirmar a API, autenticação, limites, parada local e comportamento de reconexão do robô. A camada não permite que voz, MQTT, HTTP ou ROS 2 ignorem a allowlist, a validade do comando ou a aprovação.

Exemplos reconhecidos incluem `status do robô do sítio`, `pare o robô`, `feche a porta no sítio`, `inicie a missão do robô da casa` e `vá para a sala com o robô da casa`. A frase sozinha não executa nada: ela apenas produz uma intenção estruturada.

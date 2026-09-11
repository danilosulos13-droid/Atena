# Análise de vídeos pela Atena

A Atena agora possui um fluxo para receber vídeos públicos ou um vídeo enviado diretamente no Telegram. Depois de processar o conteúdo, ela gera uma resposta com resumo, alegações principais, evidências citadas, limitações e uma **consideração final**.

## Uso pelo Telegram

Envie uma mensagem no formato:

```text
/video https://www.youtube.com/watch?v=...
```

Também é possível enviar a URL diretamente no texto. O reconhecimento aceita URLs públicas de YouTube, Facebook, Instagram, Vimeo, TikTok e Dailymotion, além de arquivos de vídeo enviados ao bot.

Para uma URL pública, a Atena usa o modo remoto: consulta metadados e legendas públicas sem baixar o arquivo de vídeo. Se a plataforma não disponibilizar legenda acessível, a Atena informa que não há transcrição suficiente. Um arquivo enviado diretamente pelo Telegram precisa ser baixado para ser processado.

Para receber as principais notícias atuais, envie `/noticias` ou uma das frases `principais notícias do dia`, `notícias de hoje` e `principais notícias de hoje`. O briefing usa as fontes RSS configuradas, deduplicação, fallback público e X somente quando o token correspondente estiver configurado. As categorias incluem IA e ciência, tecnologia, futebol, mundo, cibersegurança e outras categorias presentes no catálogo de fontes.

## Etapas

1. A URL é validada contra uma lista de plataformas reconhecidas.
2. Para URLs, `yt-dlp` consulta metadados e URLs de legendas com `skip_download`; o arquivo de vídeo não é salvo.
3. Legendas VTT/SRT públicas são convertidas em texto.
4. Para arquivos locais ou vídeos enviados no Telegram, `ffprobe` valida duração e metadados.
5. Para arquivos locais, `ffmpeg` extrai áudio e `faster-whisper` transcreve a fala, quando instalado.
6. A Atena envia a transcrição e os metadados ao roteador LLM.
7. O resultado solicita separação entre resumo, alegações, evidências, pontos não verificáveis, limitações e consideração final.

## Limites padrão

| Item | Padrão |
|---|---:|
| Duração máxima | 30 minutos |
| Tamanho máximo | 500 MB |
| Modelo Whisper | `small` |
| Idioma padrão | Português (`pt`) |
| Dispositivo | CPU |

Os limites podem ser ajustados com `ATENA_VIDEO_MAX_DURATION_S`, `ATENA_VIDEO_MAX_BYTES`, `ATENA_VIDEO_WHISPER_MODEL`, `ATENA_VIDEO_WHISPER_DEVICE` e `ATENA_VIDEO_LANGUAGE`.

## Dependências

O host precisa ter `ffmpeg` e `ffprobe`. As dependências Python opcionais estão em `setup/requirements-video.txt`:

```bash
pip install -r setup/requirements-video.txt
```

O downloader pode falhar para vídeos privados, restritos por região, protegidos por login ou removidos. Nesses casos, a Atena informa a falha em vez de tentar contornar a restrição.

## Escopo da consideração final

A consideração é uma análise textual baseada na transcrição e nos metadados. Ela não deve ser apresentada como prova independente da veracidade do vídeo. A Atena deve distinguir fato transcrito, alegação do vídeo, interpretação e informação que ainda precisa de verificação em fontes externas.

O fluxo não comenta, não compartilha, não publica e não controla dispositivos a partir do conteúdo analisado. A análise visual quadro a quadro exige um modelo multimodal configurado separadamente; a versão atual informa quando a análise está limitada à transcrição.

def get_dashboard_html() -> str:
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>ATENA Ω Dashboard</title>
        <style>
            body { background: #0a0a0a; color: #fff; font-family: sans-serif; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
            .container { text-align: center; border: 1px solid #333; padding: 40px; border-radius: 15px; }
            h1 { color: #3b82f6; }
            #status { font-size: 1.5em; margin: 20px 0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>ATENA Ω - NÚCLEO ATIVO</h1>
            <div id="status">Carregando telemetria...</div>
        </div>
        <script>
            fetch('/api/consciousness/state')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('status').innerHTML = 
                        'Nível de Consciência: ' + data.consciousness_level;
                })
                .catch(() => {
                    document.getElementById('status').innerText = 'Erro ao conectar ao motor.';
                });
        </script>
    </body>
    </html>
    """

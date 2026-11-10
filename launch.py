"""Launch the local app and open its page after the server is listening."""
import os
import threading
import time
import webbrowser
from urllib.request import urlopen


def open_when_ready(url):
    for _ in range(60):
        try:
            with urlopen(url, timeout=0.5):
                webbrowser.open(url)
                return
        except Exception:
            time.sleep(0.25)
    print('Open this URL manually:', url)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    url = f'http://localhost:{port}'
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    import app
    app.init_db()
    print('Open', url, flush=True)
    try:
        app.ThreadingHTTPServer(('127.0.0.1', port), app.Handler).serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped.')

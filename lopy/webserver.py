import socket
import _thread
import os

class WebServer:
    RESPONSE_200 = 'HTTP/1.1 200 OK\nConnection: close\nServer: Lopy\nContent-Type: text/html\n\n'

    def __init__(self, port, html_file=None, query_param_callback=None, debug=True):
        if not isinstance(port, int):
            raise Exception('port must be an int')
        self.port = port
        self.socket = None
        self.running = False

        # callback
        #    params:
        #        a single map
        #    returns:
        #       True - it handled the parameters
        #       False - it didn't handle and the html_file should be returned
        self.query_param_callback = query_param_callback

        # test that the file exists
        if html_file:
            try:
                os.stat(html_file)
            except OSError as e:
                raise Exception("html file '%s' not found: %s" % (html_file, str(e)))
        self.html_file = html_file

        if debug:
            def _d_print(*_args):
                print('webserver -', str(_args))
        else:
            _d_print = lambda *a: None
        self.d_print = _d_print

    def start(self):
        if not self.running:
            _thread.start_new_thread(self._listen, (self.port, self.html_file))

    def stop(self):
        self.running = False
        s = self.socket
        self.socket = None
        if s:
            s.close()

    def _process_query_params(self, request):
        if not self.query_param_callback:
            return False

        processed = False
        term = 'GET /'
        index = request.find(term)
        self.d_print(index)
        if index >= 0:
            query = request[index+len(term):request.find(' ', index+len(term))]
            paramIndex = query.find('?')
            self.d_print('query: ', query)
            if paramIndex >= 0:
                queryParams = query[paramIndex+1:]
                self.d_print('queryParams: ', queryParams, len(queryParams))
                if queryParams:
                    params = {}
                    for param in queryParams.split('&'):
                        self.d_print(param)
                        keyValueSet = param.split('=')
                        if len(keyValueSet) == 2:
                            params[keyValueSet[0]] = keyValueSet[1]
                    self.d_print(params)
                    processed = self.query_param_callback(params)

        if processed:
            self.d_print('query parameters processed')
        else:
            self.d_print('query parameters not processed')
        return processed

    def _listen(self, port, html_file):
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.d_print("listening on port: %d" % port)
            self.socket.bind(('', port))
            self.socket.listen(0)
            while self.running:
                s = self.socket
                if not s:
                    return
                conn, addr = s.accept()
                try:
                    request = conn.recv(1024)
                    conn.sendall(WebServer.RESPONSE_200)
                    request = str(request)
                    self.d_print("%s request: %s" % (str(addr), request))
                    if not self._process_query_params(request):
                        if (self.html_file):
                            with open(self.html_file, 'r') as html:
                                conn.send(html.read())
                    conn.sendall('\n')
                finally:
                    conn.close()
                self.d_print("%s connection closed" % str(addr))
        except OSError as e:
            self.d_print("listener error: %s" % str(e))
        finally:
            self.running = False
            self.d_print("stopped")
            s = self.socket
            if s:
                s.close()
            self.socket = None

from django.http import HttpResponse
import requests

__author__ = 'alex'


class ProxyRequest(object):
    NO_PROXY = {'no': 'pass'}

    HOP_BY_HOP_HEADER = [
        'connection',
        'keep-alive',
        'proxy-authenticate',
        'proxy-authorization',
        'te',
        'trailers',
        'transfer-encoding',
        'upgrade',
        'content-encoding'
    ]

    def __init__(self):
        self.request = None

    @property
    def path(self):
        return self.request.path.lstrip('/')

    def process_request(self, request):
        self.request = request
        return self._response()

    def _response(self):
        session = requests.Session()
        session.trust_env = False

        req = session.request(self.request.method, self.path, proxies=self.NO_PROXY)
        response = HttpResponse(req.text)

        for header, value in req.headers.iteritems():
            if not header.lower() in self.HOP_BY_HOP_HEADER:
                response[header] = value

        return response


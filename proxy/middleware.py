from django.http import HttpResponse, StreamingHttpResponse
from django.core.cache import get_cache, DEFAULT_CACHE_ALIAS
import requests
from proxy import utils

__author__ = 'alex'


class Cache(object):
    sep = '_'

    def __init__(self, scope):
        self.scope = scope
        self.cache = get_cache(DEFAULT_CACHE_ALIAS)

    def __getitem__(self, key):
        return self.cache.get(self.sep.join([self.scope, key]))

    def __setitem__(self, key, value):
        self.cache.add(self.sep.join([self.scope, key]), value)

    def has(self, name):
        return self.cache.has_key(self.sep.join([self.scope, name]))

    def iter(self, name):
        text = self.cache.get(self.sep.join([self.scope, name]))
        counter = 2048
        while text:
            yield text[:counter]
            text = text[counter:]
        raise StopIteration


class ProxyRequest(object):
    """ proxy server it self """
    CONTENT = 'text'
    HEADERS = 'headers'

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
        self.request = self.cache = None

    @property
    def path(self):
        path = self.request.path.lstrip('/').strip()
        if not path or not path.startswith('http'):
            path = utils.get_request_absolute_url(self.request)
        return path

    def process_request(self, request):
        self.request = request
        self.cache = Cache(self.path)

        if self.cache.has(self.CONTENT) and self.cache.has(self.HEADERS):
            response = self._response_cache()
        else:
            response = self._response_web()

        return response

    def _response_cache(self):
        response = StreamingHttpResponse(self.cache.iter(self.CONTENT))
        for header, value in self.cache[self.HEADERS].iteritems():
            response[header] = value
        return response

    def _response_web(self):
        session = requests.Session()
        session.trust_env = False

        req = session.request(self.request.method, self.path, proxies=self.NO_PROXY)
        text = req.text

        response = HttpResponse(text)

        headers = {}

        for header, value in req.headers.iteritems():
            if not header.lower() in self.HOP_BY_HOP_HEADER:
                response[header] = value
                headers[header] = value

        self.cache[self.HEADERS] = headers
        self.cache[self.CONTENT] = text
        return response

